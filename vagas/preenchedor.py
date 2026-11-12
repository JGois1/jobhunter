"""Preenche formulários de candidatura em qualquer site, a partir do rótulo de cada campo.

Regras de segurança (de propósito):
- nunca clica em Enviar/Finalizar: quem envia é você;
- nunca marca caixas de aceite de termos ou LGPD;
- nunca mexe em campos de senha, CPF ou de busca;
- não sobrescreve um campo que já tem valor.
"""
from __future__ import annotations

import re
from pathlib import Path

from .modelo import normalizar

# (expressão no rótulo normalizado, chave em dados_pessoais.json). A primeira que casar vence.
MAPA = [
    (r"\b(primeiro nome|first name|nome proprio)\b", "primeiro_nome"),
    (r"\b(sobrenome|ultimo nome|last name|surname)\b", "sobrenome"),
    (r"\b(linkedin)\b", "linkedin"),
    (r"\b(github|portfolio|portifolio|site pessoal|website)\b", "github"),
    (r"\b(e ?mail)\b", "email"),
    (r"\b(telefone|celular|whatsapp|phone|mobile)\b", "telefone"),
    (r"\b(previsao|conclusao|formatura|graduation|termino)\b", "previsao_formatura"),
    (r"\b(instituicao|universidade|faculdade|university|college|escola)\b", "instituicao"),
    (r"\b(periodo|semestre)\b", "periodo"),
    (r"\b(curso|course|graduacao em|major)\b", "curso"),
    (r"\b(escolaridade|formacao academica|nivel de ensino)\b", "nivel_escolaridade"),
    (r"\b(pretensao|salario|salarial|remuneracao)\b", "pretensao_salarial"),
    (r"\b(coeficiente de rendimento|cr|cra|indice de rendimento|media geral|media global)\b", "cr"),
    (r"\b(ingles|english)\b", "ingles"),
    (r"\b(cidade|city|municipio)\b", "cidade"),
    (r"\b(estado|uf|state)\b", "estado"),
    (r"\b(pais|country)\b", "pais"),
    (r"\b(nome completo|full name|seu nome|^nome$|^name$|nome)\b", "nome_completo"),
]
# rótulos que parecem casar mas são outra coisa ("nome da mãe", "estado civil"...)
EXCECOES = {
    "nome_completo": r"\b(mae|pai|empresa|social|referencia|emergencia|responsavel|usuario)\b",
    "estado": r"\b(civil|conservacao)\b",
    "curso": r"\b(complementar|extracurricular|idioma)\b",
    "cidade": r"\b(nascimento|natal)\b",
    "pais": r"\b(nascimento)\b",
    "pretensao_salarial": r"\b(ultima|ultimo|atual|anterior|recebia|recebe|recebeu)\b",
    # confirmação de e-mail: você digita (muitos sites bloqueiam colar); e-mail secundário: não é o principal
    "email": r"(confirm|secondary|secundari|alternativ|recado|outro)",
}
PROIBIDO = re.compile(r"senha|password|cpf|rg\b|busca|pesquis|search|cupom|captcha", re.I)
RE_CURRICULO = re.compile(r"curr[ií]culo|curriculum|\bcv\b|resume|anexo|attach", re.I)
# Só botões que ABREM o formulário. "Candidatura rápida", "1 clique", "Easy apply" ficam de fora
# de propósito: costumam enviar na hora, sem você revisar.
RE_BOTAO_CANDIDATAR = re.compile(
    r"^\s*(candidat(ar|e)[- ]?(se|me)?( (a|à|para) (esta |essa )?vaga)?|quero me candidatar|"
    r"candidatura completa|candidatura simplificada|aplicar( para a vaga)?|apply( now)?|inscrever[- ]se)\s*$", re.I)
# Botões que só passam para a próxima etapa do formulário (o assistente pode clicar)...
RE_BOTAO_AVANCAR = re.compile(
    r"^\s*(avan[cç]ar|pr[oó]xim[oa]( etapa| passo)?|continuar|seguir|next|revisar( candidatura)?|review|"
    r"salvar e (continuar|avan[cç]ar|seguir))\s*(>|›|→)?\s*$", re.I)
# ...e botões de ENVIO: quando um destes aparece, o assistente para e quem clica é você.
RE_BOTAO_ENVIAR = re.compile(
    r"(^|[^a-z])(enviar|envie|finalizar|concluir|confirmar|submeter|submit|send|finish)([^a-z]|$)|"
    r"candidatar", re.I)
# "Entrar"/"Login" no cabeçalho = você não está logado naquele site
RE_BOTAO_ENTRAR = re.compile(
    r"^\s*(entrar|entre|login|log in|fazer login|acessar( conta| minha conta)?|sign in|"
    r"j[aá] tenho (conta|cadastro))\s*$", re.I)
# rótulos de etapa/título que aparecem e mudam quando o formulário avança
JS_ASSINATURA = r"""() => location.href + '|' +
  [...document.querySelectorAll('label, legend, h1, h2, h3, h4, [aria-current], [class*=active]')]
    .map(e => (e.innerText || '').trim()).join('|').slice(0, 4000)"""

# JS que lista os campos visíveis com o melhor rótulo possível para cada um.
JS_CAMPOS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const LETRAS = /[A-Za-zÀ-ú]{3,}/;
  const rotulo = e => {
    let forte = [], fraco = [];               // forte: rótulo de verdade; fraco: placeholder, name, id
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) forte.push(l.innerText); }
    const pai = e.closest('label'); if (pai) forte.push(pai.innerText);
    if (e.getAttribute('aria-label')) forte.push(e.getAttribute('aria-label'));
    const lb = e.getAttribute('aria-labelledby');
    if (lb) lb.split(' ').forEach(i => { const x = document.getElementById(i); if (x) forte.push(x.innerText); });
    for (const a of ['placeholder', 'name', 'id', 'title']) if (e.getAttribute(a)) fraco.push(e.getAttribute(a));
    forte = forte.filter(t => t && LETRAS.test(t));
    if (!forte.length) {   // sem rótulo: a pergunta costuma ser o texto logo acima ("1. Qual a sua...?")
      let n = e;
      for (let i = 0; i < 5 && n; i++) {
        n = n.parentElement;
        const txt = n && n.innerText ? n.innerText.trim() : '';
        if (txt.length >= 400) break;          // já pegou o formulário inteiro: desiste
        if (LETRAS.test(txt)) { forte.push(txt); break; }   // ignora textos tipo "0/250"
      }
    }
    return [...forte, ...fraco].join(' | ').replace(/\s+/g, ' ').slice(0, 300);
  };
  const out = [];
  document.querySelectorAll('input, textarea, select').forEach((e, i) => {
    const tipo = (e.tagName === 'INPUT' ? (e.type || 'text') : e.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'checkbox', 'radio', 'password', 'image', 'reset', 'search'].includes(tipo)) return;
    if (tipo !== 'file' && !vis(e)) return;
    if (e.disabled || e.readOnly) return;
    e.setAttribute('data-assistente', String(i));
    const valor = tipo === 'file' ? (e.files.length ? 'x' : '')
                : tipo === 'select' ? (e.selectedIndex > 0 ? e.value : '')   // 1ª opção costuma ser "Selecione"
                : (e.value || '');
    const combo = tipo !== 'select' && tipo !== 'textarea' && !!(
      e.getAttribute('role') === 'combobox' || e.getAttribute('aria-autocomplete') ||
      ['listbox', 'true', 'menu'].includes(e.getAttribute('aria-haspopup') || '') ||
      e.closest('[role=combobox], [aria-haspopup=listbox]') ||
      /escolha|selecione|select an option/i.test(e.getAttribute('placeholder') || ''));
    out.push({ idx: String(i), tipo, rotulo: rotulo(e), valor, combo,
               selecionado: tipo === 'select' && e.selectedIndex > 0 ? (e.selectedOptions[0] || {}).text || '' : '',
               opcoes: tipo === 'select' ? [...e.options].map(o => o.text) : [] ,
               obrigatorio: e.required || e.getAttribute('aria-required') === 'true' });
  });
  return out;
}"""


# JS que acha perguntas de escolha: Sim/Não e múltipla escolha (radio), "marque as que se aplicam"
# (checkbox em grupo) e caixinhas sozinhas (aceites). Para cada grupo: pergunta, opções e o que está marcado.
JS_GRUPOS = r"""() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const LETRAS = /[A-Za-zÀ-ú]{3,}/;
  const limpa = t => (t || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-assistente-op]').forEach(e => e.removeAttribute('data-assistente-op'));
  const textoOpcao = e => {
    const l = e.closest('label') || (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`));
    if (l && limpa(l.innerText)) return limpa(l.innerText);
    if (e.getAttribute('aria-label')) return limpa(e.getAttribute('aria-label'));
    const lb = e.getAttribute('aria-labelledby');
    if (lb) return limpa(lb.split(' ').map(i => (document.getElementById(i) || {}).innerText || '').join(' '));
    return limpa(e.innerText || e.value);
  };
  const marcado = e => e.tagName === 'INPUT' ? e.checked : e.getAttribute('aria-checked') === 'true';
  const aparece = e => vis(e) || vis(e.closest('label')) || vis(e.parentElement);
  const grupos = new Map();
  let solto = 0;
  for (const e of document.querySelectorAll('input[type=radio], input[type=checkbox], [role=radio], [role=checkbox]')) {
    if (!aparece(e) || e.disabled || e.getAttribute('aria-disabled') === 'true') continue;
    const tipo = (e.type === 'radio' || e.getAttribute('role') === 'radio') ? 'radio' : 'checkbox';
    const cont = e.closest('fieldset, [role=radiogroup], [role=group]');
    let chave = e.name ? 'n:' + tipo + ':' + e.name : null;
    if (!chave && cont) chave = 'c:' + ([...document.querySelectorAll('fieldset, [role=radiogroup], [role=group]')].indexOf(cont));
    if (!chave) chave = 's:' + (solto++);
    if (!grupos.has(chave)) grupos.set(chave, { tipo, els: [] });
    grupos.get(chave).els.push(e);
  }
  const out = []; let g = 0;
  for (const grp of grupos.values()) {
    const els = grp.els, opcoes = els.map(textoOpcao);
    let pergunta = '';
    const cont = els[0].closest('fieldset, [role=radiogroup], [role=group]');
    if (cont) {
      const lg = cont.querySelector('legend'); if (lg) pergunta = limpa(lg.innerText);
      if (!pergunta && cont.getAttribute('aria-label')) pergunta = limpa(cont.getAttribute('aria-label'));
      const lb = cont.getAttribute('aria-labelledby');
      if (!pergunta && lb) pergunta = limpa(lb.split(' ').map(i => (document.getElementById(i) || {}).innerText || '').join(' '));
    }
    if (!pergunta) {   // sobe até um ancestral com todas as opções e algum texto além delas: é a pergunta
      let n = els[0];
      for (let i = 0; i < 8 && n; i++) {
        n = n.parentElement; if (!n) break;
        if (!els.every(x => n.contains(x))) continue;
        let t = limpa(n.innerText);
        for (const o of [...opcoes].sort((a, b) => b.length - a.length)) if (o) t = t.split(o).join(' ');
        t = limpa(t);
        if (t.length > 400) break;
        if (LETRAS.test(t)) { pergunta = t; break; }
      }
    }
    const id = 'g' + (g++);
    els.forEach((e, i) => e.setAttribute('data-assistente-op', id + ':' + i));
    out.push({ gid: id, tipo: grp.tipo, sozinho: els.length === 1, pergunta: pergunta.slice(0, 300), opcoes,
               marcados: els.map(marcado),
               obrigatorio: els.some(e => e.required || e.getAttribute('aria-required') === 'true') ||
                            !!(cont && cont.getAttribute('aria-required') === 'true') });
  }
  return out;
}"""

# o que está marcado agora num grupo (para aprender o que você escolheu)
JS_MARCADOS = r"""(gid) => {
  const els = [...document.querySelectorAll(`[data-assistente-op^="${gid}:"]`)];
  const texto = e => { const l = e.closest('label') || (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`));
                       return ((l && l.innerText) || e.getAttribute('aria-label') || e.innerText || e.value || '').replace(/\s+/g, ' ').trim(); };
  const marcado = e => e.tagName === 'INPUT' ? e.checked : e.getAttribute('aria-checked') === 'true';
  return { opcoes: els.map(texto), marcadas: els.filter(marcado).map(texto) };
}"""

RE_ACEITE = re.compile(r"aceito|concordo|(^|\s)li e\s|li os|termos|pol[ií]tica|declaro|autorizo|consinto|lgpd|"
                       r"privacidade|estou ciente|confirmo que|consentimento", re.I)
# origens em que eu confio sem parar (o Claude, quando tiver a chave, escreve e você confere)
ORIGEM = {"memoria": "da sua memória", "dados": "dos seus dados", "padrao": "do seu respostas.md",
          "regra": "pela sua regra de autorizar uso de dados"}


JS_TEXTOS = r"""() => {
  const out = []; let i = 0;
  document.querySelectorAll('[data-assistente-txt]').forEach(e => e.removeAttribute('data-assistente-txt'));
  // ícones feitos com fonte (Material Icons etc.) aparecem como texto: "edit_document", "send"...
  const ICONE = /icon|material|symbol|\bfa-|glyph/i;
  const texto = e => { if (!e.querySelector('*')) return e.innerText || '';
    const c = e.cloneNode(true); c.querySelectorAll('*').forEach(x => {
      if (ICONE.test(x.getAttribute('class') || '')) x.remove(); });
    return c.textContent || ''; };
  for (const e of document.querySelectorAll('button, a, [role=button], span, div, p')) {
    if (ICONE.test(e.getAttribute('class') || '')) continue;
    const t = texto(e).replace(/\s+/g, ' ').replace(/^([a-z0-9]+_[a-z0-9_]+ )+/, '').trim();
    if (!t || t.length > 50) continue;
    const r = e.getBoundingClientRect(); if (!r.width || !r.height) continue;
    // fica só com o elemento mais interno que tem esse texto
    if ([...e.children].some(c => texto(c).replace(/\s+/g, ' ').replace(/^([a-z0-9]+_[a-z0-9_]+ )+/, '').trim() === t)) continue;
    e.setAttribute('data-assistente-txt', String(i));
    out.push({ idx: String(i++), texto: t, clicavel: !!e.closest('button, a, [role=button]') });
  }
  for (const e of document.querySelectorAll('input[type=submit], input[type=button]')) {
    const r = e.getBoundingClientRect(); if (!r.width || !r.height || !e.value) continue;
    e.setAttribute('data-assistente-txt', String(i)); out.push({ idx: String(i++), texto: e.value.trim(), clicavel: true });
  }
  return out;
}"""


def carregar_respostas(caminho: Path) -> list[tuple[list[str], str]]:
    """Lê respostas.md: '## kw1 | kw2' seguido do texto."""
    secoes, atual, texto = [], None, []
    if not caminho.exists():
        return secoes
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith("## "):
            if atual:
                secoes.append((atual, "\n".join(texto).strip()))
            atual, texto = [normalizar(k) for k in linha[3:].split("|")], []
        elif atual is not None:
            texto.append(linha)
    if atual:
        secoes.append((atual, "\n".join(texto).strip()))
    return secoes


# palavras que não dizem nada sobre o assunto da pergunta
STOP = set("""a o as os um uma uns umas de da do das dos em no na nos nas para pra por com e ou
que qual quais quanto quanta quantos quantas sua seu suas seus voce voces tem teria possui ja ao
aos se sobre como me lhe isso esta este essa esse nesta neste nessa nesse ate mais muito sim nao
favor descreva informe digite responda""".split())
RE_PLACEHOLDER = re.compile(r"digite|escreva|sua resposta|type here|insira|responda aqui", re.I)
# dados que fazem sentido como resposta curta a uma pergunta ("Qual sua pretensão salarial?")
SEGUROS_EM_PERGUNTA = {"pretensao_salarial", "ingles", "previsao_formatura", "periodo", "linkedin", "github", "cr"}


def pergunta_de(rotulo: str) -> str:
    """O pedaço do rótulo que é a pergunta (tira placeholder, name, contador '0/250', '1.')."""
    rotulo = re.sub(r"^\s*\d+\s*[.)\-–]\s*", "", rotulo)
    for parte in rotulo.split("|"):
        p = parte.strip()
        if re.search(r"[A-Za-zÀ-ú]{3,}", p) and not RE_PLACEHOLDER.search(p) and "." not in p.replace(". ", ""):
            return re.sub(r"\b\d+\s*/\s*\d+\b", "", p).strip().rstrip("* ").strip()   # tira "0/250" e o "*"
    return rotulo.split("|")[0].strip()


def palavras_chave(texto: str) -> list[str]:
    return [w for w in normalizar(texto).split() if w not in STOP and len(w) > 1 and not w.isdigit()]


RE_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numero(t: str):
    m = RE_NUM.fullmatch(t.strip().replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _faixa(opcao: str):
    """'Entre 7 e 8' -> (7, 8); 'Menor que 5' -> (-inf, 5); 'Acima de 9' -> (9, inf); senão None."""
    nums = [float(x.replace(",", ".")) for x in RE_NUM.findall(opcao)]
    o = normalizar(opcao)
    if len(nums) >= 2 and re.search(r"entre|\ba\b|ate|de|-", o + " " + opcao):
        return min(nums[:2]), max(nums[:2])
    if len(nums) == 1:
        if re.search(r"menor|abaixo|inferior|ate|menos", o):
            return float("-inf"), nums[0]
        if re.search(r"maior|acima|superior|mais|ou mais", o):
            return nums[0], float("inf")
    return None


def casar_numero(valor: float, opcoes: list[str]) -> list[int]:
    for i, o in enumerate(opcoes):
        f = _faixa(o)
        if f and f[0] <= valor < f[1] or (f and valor == f[1] and f[1] == float("inf")):
            return [i]
    for i, o in enumerate(opcoes):                      # limite de cima fechado ("Entre 9 e 10" com 10)
        f = _faixa(o)
        if f and f[0] <= valor <= f[1]:
            return [i]
    return []


RE_USO_DADOS = re.compile(r"(autoriz|consent|concord|aceit).*(dados|privacidade|lgpd)|"
                          r"(dados|privacidade|lgpd).*(autoriz|consent|concord|aceit)")
RE_AFIRMATIVA = re.compile(r"^(sim|eu )?(autorizo|concordo|aceito|sim)")


def casar_opcoes(resposta: str, opcoes: list[str], multipla: bool = False) -> list[int]:
    """Quais opções correspondem à resposta ("Sim, tenho..." → "Sim"; "Avançado" → "Avançado";
    "Python; C#" → as duas, se for de marcar várias)."""
    def variantes(a):
        vs = {a}
        if "cursando" in a:
            vs |= {a.replace("cursando", "incompleto"), a.replace("cursando", "em andamento")}
        return vs
    n = _numero(resposta)
    if n is not None and not multipla and any(_faixa(o) for o in opcoes):
        return casar_numero(n, opcoes)                 # "7.6" -> "Entre 7 e 8"
    alvos = [normalizar(x) for x in (resposta.split(";") if multipla else [resposta]) if normalizar(x)]
    escolhidas = []
    for alvo in alvos:
        for i, o in enumerate(normalizar(x) for x in opcoes):
            if not o or i in escolhidas:
                continue
            if any(a == o or o.startswith(a + " ") or a.startswith(o + " ")
                   or (o in ("sim", "nao") and a.split()[0] == o)
                   or (len(o) >= 4 and o in a.split()) for a in variantes(alvo)):
                escolhidas.append(i)
                break
        if escolhidas and not multipla:
            break
    return escolhidas


def salvar_aprendida(caminho: Path, secoes: list, pergunta: str, resposta: str):
    """Guarda (ou atualiza) a sua resposta para uma pergunta em respostas_aprendidas.md."""
    chave = " ".join(palavras_chave(pergunta))
    completa = normalizar(pergunta)
    secoes[:] = [(ks, t) for ks, t in secoes if chave not in ks]      # resposta nova substitui
    secoes.insert(0, ([chave, completa], resposta))
    linhas = ["# Respostas que você deu nos formulários (o assistente aprende sozinho).",
              "# Edite ou apague à vontade. Formato: '## palavras da pergunta', depois a resposta.", ""]
    for ks, t in secoes:
        linhas.append("## " + " | ".join(k for k in ks if k))
        linhas += [(" " + l if l.startswith("#") else l) for l in t.splitlines()]
        linhas.append("")
    caminho.write_text("\n".join(linhas), encoding="utf-8")


class Preenchedor:
    def __init__(self, dados: dict, respostas: list, escritor=None,
                 aprendidas: list | None = None, arquivo_aprendidas: Path | None = None):
        self.dados = dados
        self.respostas = respostas
        self.escritor = escritor  # função (pergunta) -> texto, usando o Claude; opcional
        self.aprendidas = aprendidas if aprendidas is not None else []   # compartilhada entre vagas
        self.arquivo_aprendidas = arquivo_aprendidas
        self.abertas = {}         # perguntas abertas desta tela: (frame, idx) -> (pergunta, o que eu escrevi)
        self.autorizar_dados = False   # config "autorizar_uso_de_dados": responde "Autorizo" nessas perguntas
        self.escritos = set()          # perguntas que EU respondi nesta execução (não confundir com as suas)

    def textos_botoes(self, pagina) -> list[dict]:
        """Textos curtos visíveis da página (o elemento mais interno com cada texto)."""
        try:
            return pagina.evaluate(JS_TEXTOS)
        except Exception:
            return []

    def clicar_candidatar(self, pagina, espera=10) -> bool:
        """Na página da vaga, clica no botão de candidatura (só abre o formulário).
        Espera até `espera` s: muitos sites só mostram o botão depois de carregar o login."""
        import time
        fim = time.time() + espera
        while True:
            botoes = sorted(self.textos_botoes(pagina), key=lambda b: not b.get("clicavel"))
            for b in botoes:                     # botões de verdade primeiro
                if RE_BOTAO_CANDIDATAR.match(b["texto"]):
                    try:
                        pagina.locator(f'[data-assistente-txt="{b["idx"]}"]').click(timeout=3000)
                        pagina.wait_for_load_state("domcontentloaded")
                        return True
                    except Exception:
                        continue
            if time.time() > fim:
                return False
            pagina.wait_for_timeout(1000)

    def tela_de_login(self, pagina) -> bool:
        """A tela atual é de login (tem campo de senha visível)?"""
        for frame in pagina.frames:
            try:
                if frame.locator("input[type=password]:visible").count():
                    return True
            except Exception:
                pass
        return False

    def parece_deslogado(self, pagina) -> bool:
        """Há um botão/link "Entrar"/"Login" à vista (você não está logado neste site)?"""
        return any(b.get("clicavel") and RE_BOTAO_ENTRAR.match(b["texto"])
                   for b in self.textos_botoes(pagina))

    def esperar_tela(self, pagina, espera=15) -> bool:
        """Espera a próxima tela aparecer: campos, perguntas de escolha ou um botão de avançar/enviar.
        (A Gupy leva uns segundos para salvar e trazer as perguntas da empresa.)"""
        import time
        fim = time.time() + espera
        while time.time() < fim:
            for frame in pagina.frames:
                try:
                    if frame.evaluate(JS_CAMPOS) or frame.evaluate(JS_GRUPOS):
                        pagina.wait_for_timeout(800)          # deixa terminar de desenhar
                        return True
                except Exception:
                    pass
            if any(b.get("clicavel") and (RE_BOTAO_AVANCAR.match(b["texto"]) or RE_BOTAO_ENVIAR.search(b["texto"]))
                   for b in self.textos_botoes(pagina)):
                pagina.wait_for_timeout(800)
                return True
            pagina.wait_for_timeout(700)
        return False

    def esperar_campos(self, pagina, espera=10) -> bool:
        """Espera o formulário aparecer (muitos sites carregam os campos depois da página)."""
        import time
        fim = time.time() + espera
        while time.time() < fim:
            for frame in pagina.frames:
                try:
                    if frame.evaluate(JS_CAMPOS):
                        return True
                except Exception:
                    pass
            pagina.wait_for_timeout(700)
        return False

    def assinatura(self, pagina) -> str:
        try:
            return pagina.evaluate(JS_ASSINATURA)
        except Exception:
            return ""

    def botao_envio(self, pagina) -> str:
        """Texto do botão de envio que está na tela ("Finalizar candidatura"), ou "" se não há."""
        for b in self.textos_botoes(pagina):
            if b.get("clicavel") and RE_BOTAO_ENVIAR.search(b["texto"]) and not RE_BOTAO_AVANCAR.match(b["texto"]):
                return b["texto"]
        return ""

    def avancar(self, pagina) -> tuple[str, str]:
        """Tenta passar para a próxima etapa do formulário.

        Devolve (resultado, texto do botão):
          ("envio", "Enviar candidatura")  botão de envio à vista: é a última etapa, quem clica é você
          ("avancou", "Avançar")           cliquei e a página mudou
          ("travou", "Avançar")            cliquei mas nada mudou (o site deve estar pedindo algo)
          ("nada", "")                     não achei botão de próxima etapa
        """
        botoes = [b for b in self.textos_botoes(pagina) if b.get("clicavel")]
        for b in botoes:
            if RE_BOTAO_ENVIAR.search(b["texto"]) and not RE_BOTAO_AVANCAR.match(b["texto"]):
                return "envio", b["texto"]
        alvo = next((b for b in botoes if RE_BOTAO_AVANCAR.match(b["texto"])), None)
        if not alvo:
            return "nada", ""
        antes = self.assinatura(pagina)
        try:
            pagina.locator(f'[data-assistente-txt="{alvo["idx"]}"]').click(timeout=3000)
        except Exception:
            return "travou", alvo["texto"]
        for _ in range(12):                     # até ~6 s para a próxima etapa aparecer
            pagina.wait_for_timeout(500)
            if self.assinatura(pagina) != antes:
                return "avancou", alvo["texto"]
        return "travou", alvo["texto"]

    def preencher(self, pagina) -> dict:
        """Preenche todos os frames da página. Devolve um relatório do que fez."""
        rel = {"preenchidos": [], "perguntas": [], "pendentes": [], "aceites": [], "aprendidas": [], "campos": 0}
        self.abertas = {}      # só a tela atual: é ela que você pode mexer antes do próximo Enter
        for frame in pagina.frames:
            try:
                campos = frame.evaluate(JS_CAMPOS)
                grupos = frame.evaluate(JS_GRUPOS)
            except Exception:
                continue
            rel["campos"] += len(campos) + len(grupos)
            for c in campos:
                self._campo(frame, c, rel)
            for g in grupos:
                self._grupo(frame, g, rel)
        return rel

    def _aprender_visto(self, pergunta: str, valor: str, rel):
        """Pergunta que já chegou respondida (por você ou pelo site): guardo, se ainda não sei."""
        valor = (valor or "").strip()
        if not (self.arquivo_aprendidas and valor) or pergunta in self.escritos:
            return
        if RE_PLACEHOLDER.search(pergunta) or not palavras_chave(pergunta):
            return
        if self._melhor(self.aprendidas, pergunta):
            return                                   # já sei responder: não troco pelo que está na tela
        salvar_aprendida(self.arquivo_aprendidas, self.aprendidas, pergunta, valor)
        rel["aprendidas"].append(pergunta)

    def _resposta_curta(self, pergunta: str, chave_dado: str | None = None) -> tuple[str, str]:
        """Resposta para pergunta de escolha: sua memória ou seus dados (nada de texto genérico)."""
        texto = self._melhor(self.aprendidas, pergunta)
        if texto:
            return texto, "memoria"
        if chave_dado is None:
            norm = normalizar(pergunta)
            chave_dado = next((k for padrao, k in MAPA if re.search(padrao, norm)), None)
            if chave_dado in EXCECOES and re.search(EXCECOES[chave_dado], norm):
                chave_dado = None
        if chave_dado and self.dados.get(chave_dado):
            return self.dados[chave_dado], "dados"
        return "", ""

    def _grupo(self, frame, g, rel):
        """Sim/Não, múltipla escolha, 'marque as que se aplicam' e caixinhas de aceite."""
        pergunta = pergunta_de(g["pergunta"]) if g["pergunta"] else ""
        if g["tipo"] == "checkbox" and g["sozinho"]:
            texto = g["opcoes"][0] or pergunta
            if not g["marcados"][0] and (RE_ACEITE.search(texto) or g["obrigatorio"]):
                rel["aceites"].append(texto[:100])      # aceite de termos: quem marca é você
            return
        if not pergunta:
            if g["obrigatorio"] and not any(g["marcados"]):
                rel["pendentes"].append("pergunta de escolha sem texto (" + " / ".join(g["opcoes"])[:60] + ")")
            return
        chave = ("g", g["gid"])
        if any(g["marcados"]):     # já respondida (pelo site ou por você): guardo, se ainda não sei
            marcadas = "; ".join(o for o, m in zip(g["opcoes"], g["marcados"]) if m)
            self._aprender_visto(pergunta, marcadas, rel)
            self.abertas[(frame.url, chave + (tuple(g["opcoes"]),))] = (pergunta, marcadas, "grupo")
            return
        opcional = bool(re.search(r"opcional|optional", normalizar(pergunta)))
        resp, origem = self._resposta_curta(pergunta)
        escolhidas = casar_opcoes(resp, g["opcoes"], multipla=g["tipo"] == "checkbox") if resp else []
        if not escolhidas and self.autorizar_dados and g["tipo"] == "radio" and RE_USO_DADOS.search(normalizar(pergunta)):
            sim = [i for i, o in enumerate(g["opcoes"]) if RE_AFIRMATIVA.search(normalizar(o)) and "nao" not in normalizar(o)]
            if sim:
                escolhidas, origem = sim[:1], "regra"
        if escolhidas:
            try:
                for i in escolhidas:
                    frame.locator(f'[data-assistente-op="{g["gid"]}:{i}"]').evaluate("e => e.click()")
                txt = "; ".join(g["opcoes"][i] for i in escolhidas)
                self.escritos.add(pergunta)
                rel["perguntas"].append((pergunta[:80], f"escolhi '{txt[:50]}' ({ORIGEM[origem]})"))
                self.abertas[(frame.url, chave + (tuple(g["opcoes"]),))] = (pergunta, txt, "grupo")
                return
            except Exception as e:
                rel["pendentes"].append(f"{pergunta[:60]} (erro ao marcar: {str(e)[:40]})")
                return
        if not opcional:
            rel["perguntas"].append((pergunta[:80], "EM BRANCO — escolha no site"))
        self.abertas[(frame.url, chave + (tuple(g["opcoes"]),))] = (pergunta, "", "grupo")

    def _escolher_na_lista(self, frame, el, resposta: str) -> str:
        """Lista suspensa feita com <input> (role=combobox): abre, acha a opção e clica."""
        el.click()
        frame.wait_for_timeout(400)
        opcoes = frame.locator("[role=option]")
        if not opcoes.count():
            el.fill(resposta[:4])
            frame.wait_for_timeout(600)
        textos = [t.strip() for t in opcoes.all_inner_texts()]
        idx = casar_opcoes(resposta, textos)
        if not idx:
            el.press("Escape")
            return ""
        opcoes.nth(idx[0]).click()
        frame.wait_for_timeout(300)
        return textos[idx[0]]

    def _campo(self, frame, c, rel):
        rotulo, norm = c["rotulo"], normalizar(c["rotulo"])
        el = frame.locator(f'[data-assistente="{c["idx"]}"]')
        if PROIBIDO.search(norm):
            return
        if c["valor"]:
            chave_v = next((k for padrao, k in MAPA if re.search(padrao, norm)), None)
            pergunta_v = pergunta_de(rotulo)
            if c["tipo"] != "file" and not chave_v and (c["tipo"] in ("textarea", "select") or c.get("combo")
                                                         or "?" in pergunta_v):
                self._aprender_visto(pergunta_v, c.get("selecionado") or c["valor"], rel)
            return
        try:
            if c["tipo"] == "file":
                pdf = self.dados.get("curriculo_pdf", "")
                if RE_CURRICULO.search(rotulo) and pdf and Path(pdf).exists():
                    el.set_input_files(pdf)
                    rel["preenchidos"].append(("currículo", Path(pdf).name))
                return

            chave = next((k for padrao, k in MAPA if re.search(padrao, norm)), None)
            if chave in EXCECOES and re.search(EXCECOES[chave], norm):
                chave = None
            pergunta = pergunta_de(rotulo)
            opcional = bool(re.search(r"opcional|optional|nao obrigatori", norm))
            if c.get("combo"):
                # lista suspensa feita com <input> (Gupy etc.): não digito texto livre; escolho uma opção
                resp, origem = self._resposta_curta(pergunta, chave)
                escolhida = self._escolher_na_lista(frame, el, resp) if resp else ""
                if escolhida:
                    self.escritos.add(pergunta)
                    rel["perguntas"].append((pergunta[:80], f"escolhi '{escolhida[:50]}' ({ORIGEM[origem]})"))
                elif c["obrigatorio"] and not opcional:
                    rel["perguntas"].append((pergunta[:80], "EM BRANCO — escolha na lista no site"))
                self.abertas[(frame.url, c["idx"])] = (pergunta, escolhida, "campo")
                return
            # textarea, ou campo de texto sem dado conhecido cuja "etiqueta" é uma pergunta
            if c["tipo"] == "textarea" or (c["tipo"] != "select" and not chave and "?" in pergunta):
                texto, origem = self._resposta_aberta(pergunta, chave)
                if texto:
                    el.fill(texto)
                    self.escritos.add(pergunta)
                    # da sua memória ou dos seus dados: sigo sem parar. Texto padrão/Claude: você confere.
                    rel["perguntas"].append((pergunta[:80], f"preenchida ({ORIGEM[origem]})" if origem in ORIGEM
                                             else "preenchida — confira"))
                elif not opcional:        # opcional em branco: deixo quieto e sigo em frente
                    rel["perguntas"].append((pergunta[:80], "EM BRANCO — responda no site"))
                self.abertas[(frame.url, c["idx"])] = (pergunta, texto, "campo")   # se você responder, eu aprendo
                return
            if c["tipo"] == "select" and not chave:
                resp, origem = self._resposta_curta(pergunta)
                idx = casar_opcoes(resp, c["opcoes"]) if resp else []
                if idx:
                    el.select_option(label=c["opcoes"][idx[0]])
                    self.escritos.add(pergunta)
                    rel["perguntas"].append((pergunta[:80], f"escolhi '{c['opcoes'][idx[0]][:50]}' ({ORIGEM[origem]})"))
                elif c["obrigatorio"] and not opcional:
                    rel["perguntas"].append((pergunta[:80], "EM BRANCO — escolha no site"))
                self.abertas[(frame.url, c["idx"])] = (pergunta, c["opcoes"][idx[0]] if idx else "", "select")
                return

            valor = self.dados.get(chave, "") if chave else ""
            if not valor:
                if c["obrigatorio"] and not opcional:
                    rel["pendentes"].append(pergunta[:80])
                return

            if c["tipo"] == "select":
                alvo = normalizar(valor)
                opcao = next((o for o in c["opcoes"] if normalizar(o) == alvo), None) or \
                        next((o for o in c["opcoes"] if alvo and alvo in normalizar(o)), None)
                if opcao:
                    el.select_option(label=opcao)
                    rel["preenchidos"].append((rotulo[:50], opcao))
                elif c["obrigatorio"]:
                    rel["pendentes"].append(rotulo[:80])
                return

            el.fill(valor)
            rel["preenchidos"].append((rotulo[:50], valor if len(valor) < 50 else valor[:47] + "..."))
        except Exception as e:
            rel["pendentes"].append(f"{rotulo[:60]} (erro: {str(e)[:60]})")

    @staticmethod
    def _melhor(secoes, pergunta: str) -> str:
        """A seção cuja chave mais combina com a pergunta. Todas as palavras da chave precisam
        aparecer (ou 75% delas, em chaves de 3+ palavras). Chave mais específica vence."""
        raiz = lambda w: w[:-1] if len(w) > 3 and w.endswith("s") else w    # "aulas" = "aula"
        palavras = {raiz(w) for w in normalizar(pergunta).split()}
        melhor, nota = "", 0.0
        for chaves, texto in secoes:
            for k in chaves:
                kw = [raiz(w) for w in k.split()]
                if not kw or not texto:
                    continue
                dentro = sum(w in palavras for w in kw)
                if dentro == len(kw) or (len(kw) >= 3 and dentro / len(kw) >= 0.75):
                    n = dentro + (0.5 if dentro == len(kw) else 0)
                    if n > nota:
                        melhor, nota = texto, n
        return melhor

    def _resposta_aberta(self, pergunta: str, chave_dado: str | None = None) -> str:
        # 1) o que você já respondeu antes numa pergunta parecida
        texto = self._melhor(self.aprendidas, pergunta)
        if texto:
            return texto, "memoria"
        # 2) um dado seu, se a pergunta é curta e direta ("Qual sua pretensão salarial?")
        if chave_dado and (chave_dado in SEGUROS_EM_PERGUNTA or len(palavras_chave(pergunta)) <= 5):
            valor = self.dados.get(chave_dado, "")
            if valor:
                return valor, "dados"
        # 3) Claude (se tiver a chave), 4) textos padrão do respostas.md
        if self.escritor:
            try:
                texto = self.escritor(pergunta)
                if texto:
                    return texto, "claude"
            except Exception as e:
                print(f"   [claude] falhou ({e}); usando respostas.md")
        texto = self._melhor(self.respostas, pergunta)
        return texto, ("padrao" if texto else "")

    def aprender(self, pagina) -> list[str]:
        """Lê o que você escreveu nas perguntas abertas desta tela e guarda para as próximas vagas.
        Só guarda quando você escreveu algo diferente do que eu tinha posto."""
        if not self.arquivo_aprendidas:
            return []
        novas = []
        for frame in pagina.frames:
            for (furl, idx), (pergunta, meu, tipo) in list(self.abertas.items()):
                if furl != frame.url:
                    continue
                try:
                    if tipo == "grupo":
                        r = frame.evaluate(JS_MARCADOS, idx[1])
                        if tuple(r["opcoes"]) != idx[2]:
                            continue          # o grupo mudou (outra tela): não é a mesma pergunta
                        valor = "; ".join(r["marcadas"])
                    elif tipo == "select":
                        valor = frame.locator(f'[data-assistente="{idx}"]').evaluate(
                            "e => (e.selectedIndex > 0 && e.selectedOptions[0]) ? e.selectedOptions[0].text : ''").strip()
                    else:
                        valor = frame.locator(f'[data-assistente="{idx}"]').input_value(timeout=800).strip()
                except Exception:
                    continue
                if not valor or valor == (meu or "").strip():
                    continue
                if RE_PLACEHOLDER.search(pergunta) or not palavras_chave(pergunta):
                    continue          # não sei qual é a pergunta: guardar viraria uma chave genérica
                salvar_aprendida(self.arquivo_aprendidas, self.aprendidas, pergunta, valor)
                self.abertas[(furl, idx)] = (pergunta, valor, tipo)
                novas.append(pergunta)
        return novas
