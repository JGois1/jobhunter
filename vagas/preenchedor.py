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
    "email": r"\b(confirm)",  # confirmação de e-mail: você digita (muitos sites bloqueiam colar)
}
PROIBIDO = re.compile(r"senha|password|cpf|rg\b|busca|pesquis|search|cupom|captcha", re.I)
RE_CURRICULO = re.compile(r"curr[ií]culo|curriculum|\bcv\b|resume|anexo|attach", re.I)
RE_BOTAO_CANDIDATAR = re.compile(r"^\s*(candidat(ar|e)[- ]?(se|me)?|quero me candidatar|aplicar( para a vaga)?|apply( now)?|inscrever[- ]se)\s*$", re.I)

# JS que lista os campos visíveis com o melhor rótulo possível para cada um.
JS_CAMPOS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const rotulo = e => {
    let t = [];
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) t.push(l.innerText); }
    const pai = e.closest('label'); if (pai) t.push(pai.innerText);
    for (const a of ['aria-label', 'placeholder', 'name', 'id', 'title']) if (e.getAttribute(a)) t.push(e.getAttribute(a));
    const lb = e.getAttribute('aria-labelledby');
    if (lb) lb.split(' ').forEach(i => { const x = document.getElementById(i); if (x) t.push(x.innerText); });
    if (t.join('').trim().length < 3) {           // procura texto logo acima do campo
      let n = e; for (let i = 0; i < 4 && n; i++) { n = n.parentElement;
        const txt = n && n.innerText && n.innerText.trim(); if (txt && txt.length < 300) { t.push(txt); break; } }
    }
    return t.join(' | ').replace(/\s+/g, ' ').slice(0, 300);
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
    out.push({ idx: String(i), tipo, rotulo: rotulo(e), valor,
               opcoes: tipo === 'select' ? [...e.options].map(o => o.text) : [] , obrigatorio: e.required });
  });
  return out;
}"""


def carregar_respostas(caminho: Path) -> list[tuple[list[str], str]]:
    """Lê respostas.md: '## kw1 | kw2' seguido do texto."""
    secoes, atual, texto = [], None, []
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


class Preenchedor:
    def __init__(self, dados: dict, respostas: list, escritor=None):
        self.dados = dados
        self.respostas = respostas
        self.escritor = escritor  # função (pergunta) -> texto, usando o Claude; opcional

    def clicar_candidatar(self, pagina) -> bool:
        """Na página da vaga, clica no botão de 'Candidatar-se' (só abre o formulário)."""
        for el in pagina.locator("button, a, [role=button]").all():
            try:
                if el.is_visible() and RE_BOTAO_CANDIDATAR.match(el.inner_text(timeout=500) or ""):
                    el.click()
                    pagina.wait_for_load_state("domcontentloaded")
                    return True
            except Exception:
                continue
        return False

    def preencher(self, pagina) -> dict:
        """Preenche todos os frames da página. Devolve um relatório do que fez."""
        rel = {"preenchidos": [], "perguntas": [], "pendentes": []}
        for frame in pagina.frames:
            try:
                campos = frame.evaluate(JS_CAMPOS)
            except Exception:
                continue
            for c in campos:
                self._campo(frame, c, rel)
        return rel

    def _campo(self, frame, c, rel):
        rotulo, norm = c["rotulo"], normalizar(c["rotulo"])
        el = frame.locator(f'[data-assistente="{c["idx"]}"]')
        if PROIBIDO.search(norm) or c["valor"]:
            return
        try:
            if c["tipo"] == "file":
                pdf = self.dados.get("curriculo_pdf", "")
                if RE_CURRICULO.search(rotulo) and pdf and Path(pdf).exists():
                    el.set_input_files(pdf)
                    rel["preenchidos"].append(("currículo", Path(pdf).name))
                return

            if c["tipo"] == "textarea":
                texto = self._resposta_aberta(rotulo)
                if texto:
                    el.fill(texto)
                    rel["perguntas"].append((rotulo[:80], "preenchida"))
                else:
                    rel["perguntas"].append((rotulo[:80], "EM BRANCO — responda você"))
                return

            chave = next((k for padrao, k in MAPA if re.search(padrao, norm)), None)
            if chave in EXCECOES and re.search(EXCECOES[chave], norm):
                chave = None
            valor = self.dados.get(chave, "") if chave else ""
            if not valor:
                if c["obrigatorio"]:
                    rel["pendentes"].append(rotulo[:80])
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

    def _resposta_aberta(self, pergunta: str) -> str:
        if self.escritor:
            try:
                return self.escritor(pergunta)
            except Exception as e:
                print(f"   [claude] falhou ({e}); usando respostas.md")
        palavras = set(normalizar(pergunta).split())
        for chaves, texto in self.respostas:
            # "conte sobre voce" casa com "Conte um pouco sobre você": basta ter todas as palavras
            if any(k and set(k.split()) <= palavras for k in chaves):
                return texto
        return ""
