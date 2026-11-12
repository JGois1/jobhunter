"""Assistente de candidatura: pega os cartões em "Vou aplicar" no Trello, abre cada vaga,
preenche o formulário e espera VOCÊ revisar e enviar.

Uso:
    python aplicar.py              # processa a coluna "Vou aplicar"
    python aplicar.py --login      # abre os sites para você fazer login (e diz em quais entrou)
    python aplicar.py --url LINK   # testa uma vaga avulsa, sem mexer no Trello
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from vagas.preenchedor import Preenchedor, carregar_respostas
from vagas.trello import Trello

RAIZ = Path(__file__).parent
PERFIL_NAVEGADOR = RAIZ / "dados" / "navegador"   # perfil do Edge do assistente (logins, histórico)
SESSAO = RAIZ / "dados" / "sessao.json"         # cópia dos cookies de login (inclui os "de sessão")
APRENDIDAS = RAIZ / "respostas_aprendidas.md"   # respostas que você deu nos formulários
PORTA = 9333                                     # porta pela qual o script conversa com o Edge
MAX_ETAPAS = 10                                  # trava de segurança do avanço automático
SITES_LOGIN = [
    "https://login.gupy.io/candidates/signin",
    "https://www.vagas.com.br/login-candidatos",
    "https://login.infojobs.com.br/",
    "https://secure.indeed.com/auth",
    # o Jobzi não tem login: as vagas dele levam para estes sites, que têm
    "https://vagas.solides.com.br/",
    "https://www.catho.com.br/",
    "https://www.empregos.com.br/",
    "https://portal.ciee.org.br/",
    "https://www.linkedin.com/login",
]
RE_URL_LOGIN = re.compile(r"login|signin|sign-in|auth|entrar|acessar", re.I)
# Sites em que o botão "Candidatar-se" já ENVIA na hora, com o currículo cadastrado lá.
# Neles o assistente não clica: não há o que preencher e quem decide enviar é você.
ENVIO_DIRETO = ("vagas.com.br", "catho.com.br", "empregos.com.br", "infojobs.com.br", "ciee.org.br")


def envia_direto(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in ENVIO_DIRETO)


def mesma_vaga(a: str, b: str) -> bool:
    """As duas URLs são a mesma página de vaga? (ignora ?query, #, barra e 'slug' no fim)"""
    pa, pb = urlparse(a), urlparse(b)
    if pa.netloc != pb.netloc:
        return False
    xa, xb = pa.path.rstrip("/"), pb.path.rstrip("/")
    return xa.startswith(xb) or xb.startswith(xa)

AJUDA = """
  Na fase 2, para cada vaga:
  [Enter]  continuar (depois de você resolver o que eu pedi, eu sigo preenchendo e avançando)
  s        já ENVIEI → move o cartão para "Aplicada"
  d        descartar → move para "Descartada / Recusada"
  p        pular por agora (o cartão fica em "Vou aplicar")
  q        sair
"""


# ------------------------------------------------------------------ Claude (opcional)
def escritor_claude(cfg, perfil, descricao_vaga):
    """Devolve uma função que escreve respostas sob medida com o Claude (ou None sem chave)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    cliente = anthropic.Anthropic()

    def escrever(pergunta: str) -> str:
        resp = cliente.messages.create(
            model=cfg["modelo_claude"],
            max_tokens=4000,
            output_config={"effort": "low"},
            system=("Você escreve respostas de formulário de candidatura a estágio em nome do candidato, "
                    "em português, primeira pessoa, tom profissional e natural, no máximo ~120 palavras. "
                    "Use SOMENTE fatos do perfil; nunca invente experiências, notas ou números. "
                    "Se a pergunta pedir algo que o perfil não informa (salário, CPF, endereço...), "
                    "responda apenas: [PREENCHER]. Responda só com o texto da resposta."),
            messages=[{"role": "user", "content":
                       f"<perfil>\n{perfil}\n</perfil>\n<vaga>\n{descricao_vaga[:5000]}\n</vaga>\n"
                       f"<pergunta>\n{pergunta}\n</pergunta>"}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("recusado")
        texto = "".join(b.text for b in resp.content if b.type == "text").strip()
        return "" if "[PREENCHER]" in texto else texto

    return escrever


# ------------------------------------------------------------------ Edge do assistente
# O Edge é aberto como um navegador COMUM (sem automação) e o script se conecta a ele pela
# porta de depuração. Assim o "Entrar com Google" funciona até no meio do aplicar.py, e os
# sites não veem um navegador robô.
def caminho_edge() -> str:
    for c in [shutil.which("msedge"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
        if c and Path(c).exists():
            return c
    sys.exit("Não achei o Microsoft Edge instalado.")


def porta_aberta(espera=10.0) -> bool:
    """O Edge do assistente responde na porta? (espera até `espera` segundos)"""
    fim = time.time() + espera
    while True:
        try:
            socket.create_connection(("127.0.0.1", PORTA), timeout=1).close()
            return True
        except OSError:
            if time.time() >= fim:
                return False
            time.sleep(0.5)


def abrir_edge(urls=()) -> bool:
    """Abre o Edge do assistente (ou reaproveita um já aberto). False = perfil preso em outra janela."""
    PERFIL_NAVEGADOR.mkdir(parents=True, exist_ok=True)
    perfil = f"--user-data-dir={PERFIL_NAVEGADOR}"
    if porta_aberta(0.3):                              # já está aberto: só abre as abas pedidas
        if urls:
            subprocess.Popen([caminho_edge(), perfil, *urls])
        return True
    subprocess.Popen([caminho_edge(), perfil, f"--remote-debugging-port={PORTA}", *OPCOES_EDGE,
                      *(urls or ["about:blank"])])
    return porta_aberta(15)


# Só para o Edge do assistente (o seu Edge normal não muda):
# - sem sincronização e sem o Edge entrar sozinho na sua conta Microsoft. Sem isso ele abre a
#   tela "Agora estamos sincronizando seus dados..." e espera você clicar em "Entendi";
# - sem as telas de primeira execução e de "restaurar páginas".
OPCOES_EDGE = [
    "--no-first-run", "--no-default-browser-check", "--start-maximized", "--hide-crash-restore-bubble",
    "--disable-sync",
    "--disable-features=msImplicitSignin,msForceBrowserSignIn,msEdgeImplicitSignin",
]


AVISO_PERFIL_PRESO = """
⚠ O Edge do assistente já está aberto por outra execução (um aplicar.py antigo, talvez em
  outro terminal). Feche essa janela do Edge (e digite q no terminal antigo) e rode de novo.
"""


def conectar(p):
    """Conecta ao Edge do assistente. Se ele estava terminando de fechar (você saiu e rodou de
    novo logo em seguida), espera fechar e abre outro."""
    for tentativa in range(3):
        try:
            nav = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTA}", timeout=15000)
            ctx = nav.contexts[0] if nav.contexts else nav.new_context()
            return nav, ctx
        except Exception:
            if tentativa == 2:
                raise
            esperar_fechar(8)
            if not abrir_edge():
                sys.exit(AVISO_PERFIL_PRESO)


def esperar_fechar(espera=8.0):
    fim = time.time() + espera
    while time.time() < fim and porta_aberta(0):
        time.sleep(0.5)


def fechar_edge(ctx):
    try:
        for pg in list(ctx.pages):      # fechar todas as abas fecha o Edge
            pg.close()
    except Exception:
        pass
    esperar_fechar(8)                   # assim uma nova execução logo depois começa limpa


class NavegadorFechado(Exception):
    pass


class AbaFechada(Exception):
    pass


def aba_ativa(ctx):
    """A aba mais recente que é um site (ignora páginas internas do Edge, como edge://welcome)."""
    abas = ctx.pages
    if not abas:
        raise NavegadorFechado()
    sites = [pg for pg in abas if not pg.url.startswith(("edge://", "chrome://", "devtools://"))]
    return (sites or abas)[-1]


def abrir_link(pagina, url):
    """goto com nova tentativa: o Edge às vezes atravessa a 1ª navegação com páginas dele
    (boas-vindas, sincronização) logo depois de abrir."""
    for tentativa in range(3):
        try:
            pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
            return
        except Exception as e:
            if "Timeout" in str(e) and pagina.url.startswith("http"):
                return                    # site lento: sigo com o que já carregou
            if tentativa == 2 or not re.search(r"interrupted|ERR_ABORTED|detached", str(e)):
                raise
            pagina.wait_for_timeout(1500)


def navegador_fechado(e: Exception) -> bool:
    return bool(re.search(r"closed|disconnected|Connection closed", str(e), re.I))


# ------------------------------------------------------------------ logins (cookies)
def _chave(c):
    return c["name"], c["domain"], c.get("path", "/")


def carregar_sessao(ctx):
    """Repõe os cookies de login que o navegador PERDEU (os "de sessão", que somem ao fechar).

    Nunca sobrescreve um cookie que o navegador já tem: o do navegador é sempre o mais novo
    (ex.: você entrou de novo num site e fechou a janela sem voltar ao terminal)."""
    if not SESSAO.exists():
        return
    try:
        salvos = json.loads(SESSAO.read_text(encoding="utf-8"))
        tem = {_chave(c) for c in ctx.cookies()}
    except Exception as e:
        print(f"(não consegui ler os logins salvos: {e})")
        return
    faltando = [c for c in salvos if _chave(c) not in tem]
    try:
        ctx.add_cookies(faltando)
    except Exception:                      # um cookie esquisito não pode derrubar os outros
        for c in faltando:
            try:
                ctx.add_cookies([c])
            except Exception:
                pass


def salvar_sessao(ctx):
    """Junta os cookies atuais com os já salvos (os atuais vencem) e descarta os vencidos."""
    try:
        atuais = ctx.cookies()
    except Exception:
        return                             # navegador já fechado: fica a última cópia salva
    juntos = {}
    if SESSAO.exists():
        try:
            juntos = {_chave(c): c for c in json.loads(SESSAO.read_text(encoding="utf-8"))}
        except Exception:
            pass
    for c in atuais:
        juntos[_chave(c)] = c
    agora = time.time()
    vivos = [c for c in juntos.values() if c.get("expires", -1) < 0 or c["expires"] > agora]
    tmp = SESSAO.with_suffix(".tmp")
    tmp.write_text(json.dumps(vivos), encoding="utf-8")
    tmp.replace(SESSAO)                    # troca de uma vez: o arquivo nunca fica pela metade


def login_manual():
    """Abre o Edge com os sites para você entrar. O script só se conecta depois do seu Enter,
    então o Google não tem como implicar com nada durante o login."""
    if not abrir_edge(SITES_LOGIN):
        print(AVISO_PERFIL_PRESO)
        return
    print("Abri o Edge com os sites. Entre nos que você usa (pode usar 'Entrar com Google').")
    input("Quando terminar, volte aqui e aperte Enter (NÃO feche o Edge antes)... ")
    if not porta_aberta(1):
        print("O Edge foi fechado antes do Enter, então não deu para copiar os logins. Rode de novo.")
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        _, ctx = conectar(p)
        print("\nComo ficou cada aba:")
        for pg in ctx.pages:
            url = pg.url
            if not url.startswith("http"):
                continue
            host = urlparse(url).netloc
            try:
                senha = pg.locator("input[type=password]:visible").count() > 0
            except Exception:
                senha = False
            if senha or RE_URL_LOGIN.search(url):
                print(f"   ✗ {host}: ainda na tela de login")
            else:
                print(f"   ✓ {host}")
        salvar_sessao(ctx)
        n = len(ctx.cookies())
        fechar_edge(ctx)
    print(f"\nLogins salvos ({n} cookies). Os ✗ são sites em que você não entrou "
          "(tudo bem, se não usa).\nAgora é só usar: python aplicar.py")


# ------------------------------------------------------------------ candidatura
def mostrar(rel):
    for pergunta in rel.get("aprendidas", []):
        print(f"   📚 guardei a resposta que já estava na tela: \"{pergunta[:70]}\"")
    for rotulo, valor in rel["preenchidos"]:
        print(f"   ✓ {rotulo}: {valor}")
    for pergunta, estado in rel["perguntas"]:
        print(f"   ✎ pergunta '{pergunta}': {estado}")
    for p in rel["pendentes"]:
        print(f"   ! obrigatório sem resposta: {p}")
    if rel["campos"] and not (rel["preenchidos"] or rel["perguntas"] or rel["pendentes"]):
        print(f"   ({rel['campos']} campo(s) na tela; nada para eu preencher aqui)")


JS_AVISO = r"""(t) => {
  let d = document.getElementById('assistente-aviso');
  if (!t) { if (d) d.remove(); return; }
  if (!d) {
    d = document.createElement('div'); d.id = 'assistente-aviso';
    d.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;max-width:460px;' +
      'background:#111827;color:#f9fafb;font:15px/1.45 "Segoe UI",Arial,sans-serif;padding:12px 16px;' +
      'border-radius:10px;border-left:6px solid #f59e0b;box-shadow:0 8px 28px rgba(0,0,0,.4);' +
      'pointer-events:none';            // não atrapalha cliques na página
    document.documentElement.appendChild(d);
  }
  d.textContent = '🤖 Assistente: ' + t;
}"""


def aviso_na_pagina(pagina, texto: str):
    """Mostra (ou apaga, com texto vazio) uma caixinha no canto da página dizendo o que eu espero."""
    try:
        pagina.evaluate(JS_AVISO, texto)
    except Exception:
        pass


# ------------------------------------------------------------------ uma candidatura
# Cada vaga é uma Candidatura: tem a sua própria aba e lembra onde parou e por quê.
# Fase 1 (sem você): abro todas e levo cada uma até onde dá.
# Fase 2 (com você): mostro uma por uma, já no ponto em que precisa de você.
ETAPAS_GUPY = {}                     # id da candidatura na Gupy -> etapas da vaga (lidas da própria página)
RE_GUPY_ETAPAS = re.compile(r"/selection-process/candidate/application/(\d+)/step(\?|$)")
ICONES = {"envio": "✋ pronta p/ enviar", "perguntas": "❓ perguntas", "confira": "👀 conferir",
          "aceite": "☑ marcar aceite",
          "pendentes": "❗ campo obrigatório", "login": "🔑 precisa de login", "travou": "⚠ travou",
          "nada": "❔ próximo passo", "sem_botao": "❔ sem botão", "direto": "↗ envio direto",
          "erro": "💥 erro"}
ORDEM = ["envio", "aceite", "perguntas", "confira", "pendentes", "login", "travou", "nada", "sem_botao", "direto", "erro"]
STATUS_TRELLO = {"envio": "pronta", "direto": "direto"}       # o resto vira "precisa de você"


class Candidatura:
    conhecidas = set()        # abas que já pertencem a alguma vaga (para achar a aba nova de cada uma)

    def __init__(self, ctx, cfg, cartao, preench, aba):
        self.ctx, self.cfg, self.cartao, self.preench, self.aba = ctx, cfg, cartao, preench, aba
        Candidatura.conhecidas.add(aba)
        self.url = cartao["url_vaga"]
        self.clicou = self.direto = False
        self.etapas = 0
        self.parada = ("nada", "", "")             # (tipo, mensagem no terminal, mensagem na página)

    # ---------------------------------------------------------- avisos
    def parar(self, tipo, terminal, pagina=None):
        self.parada = (tipo, terminal, pagina or terminal)
        print(f"   {terminal}")
        aviso_na_pagina(self.aba, self.parada[2])

    def mostrar_parada(self):
        tipo, terminal, pagina = self.parada
        print(f"   {terminal}")
        aviso_na_pagina(self.aba, pagina)

    # ---------------------------------------------------------- abrir a vaga e clicar
    def tentar_candidatar(self, espera) -> bool:
        antes = set(self.ctx.pages)
        if not self.preench.clicar_candidatar(self.aba, espera=espera):
            return False
        print("   cliquei no botão de candidatura")
        self.aba.wait_for_timeout(1500)
        novas = [pg for pg in self.ctx.pages if pg not in antes]
        if novas:                                   # o site abriu o formulário em outra aba
            self.aba = novas[-1]
            Candidatura.conhecidas.add(self.aba)
        self.preench.esperar_tela(self.aba, 15)     # o formulário costuma carregar depois
        self.clicou = True
        return True

    def abrir(self):
        """Abre a vaga e clica em candidatar-se (quando é seguro). Define a parada se não der."""
        self.clicou, self.etapas = False, 0
        abrir_link(self.aba, self.url)
        self.aba.wait_for_timeout(2000)
        self.direto = envia_direto(self.aba.url)
        if self.direto:
            self.parar("direto",
                       f"↗ em {urlparse(self.aba.url).netloc} o botão de candidatura já ENVIA com o currículo "
                       "cadastrado lá, então não clico. Se quiser a vaga, clique você e digite s "
                       "(se aparecerem perguntas, aperte Enter que eu preencho).",
                       "neste site o botão 'Candidatar-se' já ENVIA o currículo que você tem cadastrado aqui, "
                       "então não clico nele. Se quiser a vaga, clique você e digite s no terminal.")
            return
        if self.tentar_candidatar(espera=10):
            return
        if self.preench.parece_deslogado(self.aba):
            self.parar("login",
                       f"🔑 você não está logado em {urlparse(self.aba.url).netloc}: entre nessa aba "
                       "(pode usar o Google) e aperte Enter. Eu volto para a vaga sozinho.",
                       "você não está logado neste site. Entre (pode usar o Google) e depois aperte Enter no terminal.")
            return
        vistos = sorted({b["texto"] for b in self.preench.textos_botoes(self.aba)
                         if re.search(r"candid|aplic|inscr|apply", b["texto"], re.I)})
        extra = f" (botões parecidos: {vistos})" if vistos else ""
        self.parar("sem_botao",
                   f"❔ não reconheci o botão de candidatura{extra}: clique você e aperte Enter. "
                   "Evite 'Candidatura rápida'/'1 clique': costuma enviar sem revisão.",
                   "não achei o botão de candidatura. Clique você e depois aperte Enter no terminal.")

    # ---------------------------------------------------------- preencher e avançar
    def checar_aba(self):
        if self.aba.is_closed():
            if not any(not pg.is_closed() for pg in self.ctx.pages):
                raise NavegadorFechado()
            raise AbaFechada()

    def trabalhar(self):
        """Preenche e avança etapas até precisar de você. Nunca clica em envio."""
        auto = self.cfg.get("avancar_etapas_sozinho", True) and not self.direto
        self._esperou = False
        while True:
            self.checar_aba()
            aviso_na_pagina(self.aba, "")           # apaga o aviso anterior: estou trabalhando
            login = self.preench.tela_de_login(self.aba)
            rel = self.preench.preencher(self.aba)
            mostrar(rel)
            if login:
                return self.parar("login", "🔑 tela de login: entre (pode usar o Google) e aperte Enter.",
                                  "entre na sua conta (pode usar o Google) e depois aperte Enter no terminal.")
            em_branco = [p for p, e in rel["perguntas"] if "BRANCO" in e]
            if em_branco:
                return self.parar("perguntas",
                                  f"❓ {len(em_branco)} pergunta(s) em branco: responda no site e aperte Enter "
                                  "(eu guardo suas respostas para as próximas vagas).",
                                  "responda as perguntas em branco e confira as que preenchi. Depois aperte Enter "
                                  "no terminal (eu guardo suas respostas para as próximas vagas).")
            if rel["pendentes"]:
                return self.parar("pendentes", "❗ falta campo obrigatório (veja acima): preencha no site e aperte Enter.",
                                  "falta preencher campo obrigatório. Preencha e aperte Enter no terminal.")
            # respostas da sua memória ou dos seus dados seguem direto; texto padrão/Claude você confere
            if any("confira" in e for _, e in rel["perguntas"]):
                return self.parar("confira", "👀 confira as respostas que escrevi (texto padrão) e aperte Enter.",
                                  "confira as respostas que escrevi e aperte Enter no terminal para eu continuar.")
            if rel["aceites"]:
                aceite = rel["aceites"][0][:80]
                envio = self.preench.botao_envio(self.aba)
                if envio:
                    return self.parar("envio", f"✋ última etapa: marque você '{aceite}' e clique VOCÊ em '{envio}'; "
                                      f"depois digite s.{self.aviso_testes()}",
                                      f"última etapa! Marque '{aceite}' e clique VOCÊ em '{envio}'. "
                                      "Depois digite s no terminal.")
                return self.parar("aceite", f"☑ marque você a caixinha '{aceite}' (aceite de termos eu não marco "
                                  "por você) e aperte Enter.",
                                  f"marque a caixinha '{aceite}' (aceite de termos é com você) e aperte Enter no terminal.")
            if not (auto and (rel["campos"] or self.clicou)):
                if self.direto:
                    return self.parar("direto", "↗ nada para eu preencher aqui. Se você já se candidatou, digite s.",
                                      "nada para eu preencher aqui. Se você já se candidatou, digite s no terminal.")
                return self.parar("nada", "❔ siga você no navegador e aperte Enter.",
                                  "não sei o próximo passo aqui. Siga você e aperte Enter no terminal.")
            if self.etapas >= MAX_ETAPAS:
                return self.parar("travou", f"⚠ já avancei {MAX_ETAPAS} etapas; siga você e aperte Enter.")
            res, txt = self.preench.avancar(self.aba)
            if res == "avancou":
                self.etapas += 1
                print(f"   ➜ cliquei em '{txt}' (etapa {self.etapas + 1})")
                self.preench.esperar_tela(self.aba, 15)
                continue
            if res == "envio":
                return self.parar("envio", f"✋ última etapa: confira e clique VOCÊ em '{txt}'; depois digite s."
                                  f"{self.aviso_testes()}",
                                  f"última etapa! Confira tudo e clique VOCÊ em '{txt}'. Depois digite s no terminal.")
            if res == "travou":
                return self.parar("travou", f"⚠ cliquei em '{txt}' mas nada mudou: veja o que o site pediu e aperte Enter.",
                                  f"cliquei em '{txt}' mas nada mudou. Veja o que o site pediu, resolva e aperte Enter no terminal.")
            if not getattr(self, "_esperou", False):     # talvez a tela ainda estivesse carregando
                self._esperou = True
                if self.preench.esperar_tela(self.aba, 15):
                    continue
            return self.parar("nada", "❔ não achei campos nem botão de próxima etapa: siga você e aperte Enter.",
                              "não sei o próximo passo aqui. Siga você e aperte Enter no terminal.")

    def testes_gupy(self) -> list[str]:
        """Etapas online (testes) que a Gupy tem depois da candidatura, lidas dos dados da própria página."""
        m = re.search(r"/applications/(\d+)", self.aba.url)
        dados = ETAPAS_GUPY.get(m.group(1)) if m else None
        if not dados:
            return []
        etapas = sorted((dados.get("job") or {}).get("jobSteps") or [], key=lambda e: float(e.get("order") or 0))
        return [e.get("name", "") for e in etapas if e.get("type") == "online" and e.get("status") != "done"]

    def aviso_testes(self) -> str:
        testes = self.testes_gupy()
        return (f"\n      Depois de finalizar, a Gupy tem etapas online que são com você: {', '.join(testes)}."
                if testes else "")

    def preparar(self):
        """Fase 1: abre e vai até onde dá, sem perguntar nada."""
        self.abrir()
        if self.clicou:
            self.trabalhar()

    def continuar(self):
        """Depois do seu Enter: retoma de onde parou."""
        tipo = self.parada[0]
        if not self.clicou:
            # você mesmo clicou e o site abriu o formulário numa aba nova: passo a usar essa aba
            novas = [pg for pg in self.ctx.pages if pg not in Candidatura.conhecidas and not pg.is_closed()
                     and not pg.url.startswith(("edge://", "chrome://", "about:"))]
            if novas:
                self.aba = novas[-1]
                Candidatura.conhecidas.add(self.aba)
                print("   (achei o formulário na aba nova)")
        if tipo == "login" and not self.preench.tela_de_login(self.aba):
            print("   voltando para a vaga...")         # você entrou: recomeço pela página da vaga
            self.preparar()
            return
        if not (self.clicou or self.direto) and mesma_vaga(self.aba.url, self.url) \
                and not self.preench.esperar_campos(self.aba, 0.1):
            # ainda na página da vaga e sem formulário: o botão pode ter aparecido agora.
            # (dentro de um formulário eu NÃO procuro "Candidatar-se": lá ele pode ser o envio)
            self.tentar_candidatar(espera=3)
        self.trabalhar()


# ------------------------------------------------------------------ a fila inteira
def marcar_trello(trello, cartao, c: "Candidatura | None", final: str = ""):
    if not (trello and cartao.get("id")):
        return
    try:
        if final:
            trello.limpar_status(cartao)
            return
        tipo, terminal, _ = c.parada
        status = STATUS_TRELLO.get(tipo, "voce")
        texto = re.sub(r"^\W+\s*", "", terminal)
        trello.marcar_status(cartao, status, f"🤖 {datetime.now():%d/%m %H:%M} — {texto}")
    except Exception as e:
        print(f"   (não consegui atualizar o Trello: {e})")


def decidir(c: Candidatura, trello, ctx) -> str:
    """Fase 2 de uma vaga: espera você, retoma depois de cada Enter. Devolve s/d/p/q."""
    while True:
        cmd = input("   [Enter]=continuar  s=enviei  d=descartar  p=pular  q=sair: ").strip().lower()
        salvar_sessao(ctx)                       # guarda o login, caso você tenha entrado agora
        try:
            for pergunta in c.preench.aprender(c.aba):
                print(f"   📚 guardei sua resposta para \"{pergunta[:70]}\"")
        except Exception:
            pass                                 # aprender é bônus: nunca atrapalha a candidatura
        if cmd in ("s", "d", "p", "q"):
            if cmd in ("s", "d") and not (trello and c.cartao.get("id")):
                print("   (vaga avulsa: não mexi no Trello)")
            elif cmd == "s":
                testes = c.testes_gupy()
                extra = f"\nPróximas etapas online na Gupy (com você): {', '.join(testes)}" if testes else ""
                trello.mover(c.cartao["id"], "Aplicada", f"Candidatura enviada em {datetime.now():%d/%m/%Y %H:%M}{extra}")
                marcar_trello(trello, c.cartao, c, final="s")
                print("   → movido para Aplicada")
            elif cmd == "d":
                trello.mover(c.cartao["id"], "Descartada / Recusada", "Descartada antes de aplicar")
                marcar_trello(trello, c.cartao, c, final="d")
                print("   → movido para Descartada")
            return cmd
        try:
            c.checar_aba()
            c.continuar()
        except AbaFechada:
            print("   (a aba desta vaga foi fechada; deixei o cartão em 'Vou aplicar')")
            return "p"


def processar_fila(ctx, cfg, fila, trello):
    from playwright.sync_api import Error as ErroNavegador
    dados = json.loads((RAIZ / "dados_pessoais.json").read_text(encoding="utf-8"))
    respostas = carregar_respostas(RAIZ / "respostas.md")
    aprendidas = carregar_respostas(APRENDIDAS)          # cresce durante a execução
    perfil = (RAIZ / "perfil.md").read_text(encoding="utf-8")
    fila = [c for c in fila if c.get("url_vaga")]
    print(f"{len(fila)} vaga(s).\n"
          "FASE 1: vou abrir cada vaga numa aba e levar até onde der, sem te perguntar nada\n"
          "        (pode deixar rodando e ir fazer outra coisa).\n"
          f"FASE 2: te mostro uma por uma, já no ponto em que precisa de você.{AJUDA}")

    Candidatura.conhecidas = set()
    ETAPAS_GUPY.clear()

    def ouvir(resposta):                     # a Gupy carrega as etapas da vaga: guardo para avisar dos testes
        m = RE_GUPY_ETAPAS.search(resposta.url)
        if m:
            try:
                ETAPAS_GUPY[m.group(1)] = resposta.json()
            except Exception:
                pass
    ctx.on("response", ouvir)
    iniciais = list(ctx.pages)                   # abas que o Edge abriu sozinho: fecho depois
    cands = []
    for i, cartao in enumerate(fila, 1):
        print(f"\n━━━ FASE 1 [{i}/{len(fila)}] {cartao['name']}\n   {cartao['url_vaga']}")
        preench = Preenchedor(dados, respostas, escritor_claude(cfg, perfil, cartao.get("desc", "")),
                              aprendidas, APRENDIDAS)
        preench.autorizar_dados = cfg.get("autorizar_uso_de_dados", False)
        c = Candidatura(ctx, cfg, cartao, preench, ctx.new_page())
        if i == 1:
            for pg in iniciais:
                try:
                    pg.close()
                except Exception:
                    pass
        try:
            c.preparar()
        except ErroNavegador as e:
            if not ctx.pages or navegador_fechado(e) and not any(not pg.is_closed() for pg in ctx.pages):
                raise NavegadorFechado()
            c.parada = ("erro", f"💥 deu erro nesta vaga ({str(e).splitlines()[0][:90]}). "
                                "Veja a aba e siga você, ou digite p.", "")
            print(f"   {c.parada[1]}")
        marcar_trello(trello, cartao, c)
        cands.append(c)

    print("\n══════ RESUMO DA FASE 1 ══════")
    cands.sort(key=lambda c: ORDEM.index(c.parada[0]))
    for c in cands:
        print(f"   {ICONES[c.parada[0]]:<22} {c.cartao['name'][:70]}")
    prontas = sum(c.parada[0] == "envio" for c in cands)
    print(f"\n{prontas} pronta(s) para você só conferir e enviar. Vamos uma por uma.")

    for i, c in enumerate(cands, 1):
        print(f"\n━━━ FASE 2 [{i}/{len(cands)}] {c.cartao['name']}")
        try:
            if c.aba.is_closed():
                print("   (a aba desta vaga foi fechada; pulando)")
                continue
            c.aba.bring_to_front()
            if c.parada[0] == "login" and not c.preench.tela_de_login(c.aba):
                c.preparar()                     # talvez você já tenha entrado nesse site em outra aba
            else:
                c.mostrar_parada()
            cmd = decidir(c, trello, ctx)
        except ErroNavegador as e:
            if not ctx.pages:
                raise NavegadorFechado()
            print(f"   (problema nesta aba: {str(e).splitlines()[0][:90]}; pulando)")
            continue
        if cmd == "q":
            return
        if cmd in ("s", "d"):
            try:
                c.aba.close()
            except Exception:
                pass

    print("\nFila concluída. Boa sorte! 🍀")


TRAVA = RAIZ / "dados" / "aplicar.lock"


def trava_execucao() -> bool:
    """Impede dois aplicar.py ao mesmo tempo (um fecharia as abas do outro no mesmo Edge)."""
    import atexit
    if TRAVA.exists():
        try:
            pid = int(TRAVA.read_text().strip())
            vivo = str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                              capture_output=True, text=True).stdout
        except Exception:
            vivo = False
        if vivo and pid != os.getpid():
            print("⚠ Já tem um aplicar.py rodando (em outro terminal). Termine aquele (digite q) e rode de novo.")
            return False
    TRAVA.parent.mkdir(parents=True, exist_ok=True)
    TRAVA.write_text(str(os.getpid()))
    atexit.register(lambda: TRAVA.unlink(missing_ok=True))
    return True


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(RAIZ / ".env")
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser(description="Preenche candidaturas das vagas em 'Vou aplicar'.")
    ap.add_argument("--login", action="store_true", help="abrir os sites para você fazer login")
    ap.add_argument("--url", help="testar uma vaga avulsa (não mexe no Trello)")
    args = ap.parse_args()

    if args.login:
        login_manual()
        return

    if args.url:
        trello, fila = None, [{"id": None, "name": "vaga avulsa", "url_vaga": args.url, "desc": ""}]
    else:
        trello = Trello(cfg["quadro_trello"])
        fila = trello.cartoes("Vou aplicar")
        if not fila:
            print('Nenhum cartão em "Vou aplicar". Mova no Trello as vagas que você quer e rode de novo.')
            return

    if not trava_execucao():
        return
    if not abrir_edge():
        print(AVISO_PERFIL_PRESO)
        return

    from playwright.sync_api import Error as ErroNavegador, sync_playwright
    with sync_playwright() as p:
        _, ctx = conectar(p)
        carregar_sessao(ctx)
        try:
            processar_fila(ctx, cfg, fila, trello)
        except KeyboardInterrupt:
            print("\nInterrompido.")
        except (ErroNavegador, NavegadorFechado) as e:
            if isinstance(e, ErroNavegador) and not navegador_fechado(e):
                raise
            print("\nO Edge foi fechado, então parei. Os cartões que você não marcou continuam "
                  "em 'Vou aplicar'; é só rodar de novo.")
        finally:
            salvar_sessao(ctx)
            fechar_edge(ctx)


if __name__ == "__main__":
    main()
