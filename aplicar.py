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
  [Enter]  continuar (preenche a tela e avança as etapas até o botão de envio)
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
    subprocess.Popen([caminho_edge(), perfil, f"--remote-debugging-port={PORTA}",
                      "--no-first-run", "--no-default-browser-check", "--start-maximized",
                      "--hide-crash-restore-bubble", *(urls or ["about:blank"])])
    return porta_aberta(15)


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
            pagina.goto(url, wait_until="domcontentloaded")
            return
        except Exception as e:
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
    for rotulo, valor in rel["preenchidos"]:
        print(f"   ✓ {rotulo}: {valor}")
    for pergunta, estado in rel["perguntas"]:
        print(f"   ✎ pergunta '{pergunta}': {estado}")
    for p in rel["pendentes"]:
        print(f"   ! obrigatório sem resposta: {p}")
    if rel["campos"] and not (rel["preenchidos"] or rel["perguntas"] or rel["pendentes"]):
        print(f"   ({rel['campos']} campo(s) na tela; nada para eu preencher aqui)")


def tentar_candidatar(ctx, pagina, preench, espera) -> tuple[bool, object]:
    """Clica no botão de candidatura. Devolve (clicou?, aba onde o formulário está)."""
    n_abas = len(ctx.pages)
    if not preench.clicar_candidatar(pagina, espera=espera):
        return False, pagina
    print("   cliquei no botão de candidatura")
    pagina.wait_for_timeout(1500)
    if len(ctx.pages) > n_abas:                 # o site abriu o formulário em outra aba
        pagina = aba_ativa(ctx)
    preench.esperar_campos(pagina, 10)          # o formulário costuma carregar depois
    return True, pagina


def explicar_sem_botao(pagina, preench) -> bool:
    """Explica por que não cliquei. Devolve True se o motivo é falta de login."""
    host = urlparse(pagina.url).netloc
    if preench.parece_deslogado(pagina):
        print(f"   🔑 parece que você não está logado em {host}: entre nessa janela "
              "(pode usar o Google) e aperte Enter aqui. Eu volto para a vaga sozinho.")
        return True
    print("   não reconheci o botão de candidatura: clique você no navegador e aperte Enter aqui")
    print("   (evite 'Candidatura rápida' / '1 clique': costuma enviar sem você revisar)")
    vistos = {b["texto"] for b in preench.textos_botoes(pagina)
              if re.search(r"candid|aplic|inscr|apply", b["texto"], re.I)}
    if vistos:
        print(f"   botões parecidos que vi na página: {sorted(vistos)}")
    return False


def processar_vaga(ctx, cfg, cartao, preench, trello, pagina) -> str:
    """Uma vaga, do link até você decidir. Devolve o comando final (s/d/p/q)."""
    url = cartao["url_vaga"]
    abrir_link(pagina, url)
    pagina.wait_for_timeout(2000)
    direto = envia_direto(pagina.url)
    if direto:
        clicou = False
        print(f"   ✋ em {urlparse(pagina.url).netloc} o botão de candidatura já ENVIA com o currículo "
              "cadastrado lá.\n      Confira a vaga, clique você se quiser e digite s aqui "
              "(se aparecerem perguntas, aperte Enter que eu preencho).")
    else:
        clicou, pagina = tentar_candidatar(ctx, pagina, preench, espera=10)
    # sem o botão, a primeira coisa é esperar você (login ou clique); não mexo na página da vaga
    esperar_voce = not clicou
    voltar_para_vaga = (not clicou and not direto) and explicar_sem_botao(pagina, preench)

    auto = cfg.get("avancar_etapas_sozinho", True) and not direto
    etapas = 0
    while True:
        ativa = aba_ativa(ctx)
        if not esperar_voce:
            login = preench.tela_de_login(ativa)
            rel = preench.preencher(ativa)
            mostrar(rel)
            # para e espera você quando falta algo ou quando escrevi texto que você deve revisar
            revisar = bool(rel["pendentes"] or rel["perguntas"])
            if login:
                print("   🔑 tela de login: entre (pode usar o Google) e aperte Enter aqui")
            elif auto and (rel["campos"] or clicou) and not revisar and etapas < MAX_ETAPAS:
                res, txt = preench.avancar(ativa)
                if res == "avancou":
                    etapas += 1
                    print(f"   ➜ cliquei em '{txt}' (etapa {etapas + 1})")
                    preench.esperar_campos(aba_ativa(ctx), 5)
                    continue
                if res == "envio":
                    print(f"   ✋ última etapa: confira e clique VOCÊ em '{txt}' no site; depois digite s aqui")
                elif res == "travou":
                    print(f"   cliquei em '{txt}' mas a página não mudou: veja o que o site pediu, resolva e aperte Enter")
                elif clicou and not rel["campos"]:
                    print("   (não achei campos nem botão de próxima etapa: siga no navegador e aperte Enter)")
            elif revisar:
                print("   revise o que marquei acima no navegador e aperte Enter para eu continuar")
        esperar_voce = False

        cmd = input("   [Enter]=continuar  s=enviei  d=descartar  p=pular  q=sair: ").strip().lower()
        salvar_sessao(ctx)                       # guarda o login, caso você tenha entrado agora
        if cmd in ("s", "d", "p", "q"):
            if cmd in ("s", "d") and not (trello and cartao.get("id")):
                print("   (vaga avulsa: não mexi no Trello)")
            elif cmd == "s":
                trello.mover(cartao["id"], "Aplicada", f"Candidatura enviada em {datetime.now():%d/%m/%Y %H:%M}")
                print("   → movido para Aplicada")
            elif cmd == "d":
                trello.mover(cartao["id"], "Descartada / Recusada", "Descartada antes de aplicar")
                print("   → movido para Descartada")
            return cmd
        if clicou or direto:
            continue
        ativa = aba_ativa(ctx)
        if voltar_para_vaga and not preench.tela_de_login(ativa):
            # você acabou de entrar no site: o site pode ter te levado para outra página
            voltar_para_vaga = False
            if ativa.url.split("#")[0] != url:
                print("   voltando para a vaga...")
                abrir_link(ativa, url)
                ativa.wait_for_timeout(2000)
            clicou, _ = tentar_candidatar(ctx, ativa, preench, espera=10)
            if not clicou:
                voltar_para_vaga = explicar_sem_botao(ativa, preench)
                esperar_voce = True
        elif mesma_vaga(ativa.url, url) and not preench.esperar_campos(ativa, 0.1):
            # ainda na página da vaga e sem formulário aberto: o botão pode ter aparecido agora.
            # (dentro de um formulário eu NÃO procuro "Candidatar-se": lá ele pode ser o envio)
            clicou, _ = tentar_candidatar(ctx, ativa, preench, espera=3)


def processar_fila(ctx, cfg, fila, trello):
    dados = json.loads((RAIZ / "dados_pessoais.json").read_text(encoding="utf-8"))
    respostas = carregar_respostas(RAIZ / "respostas.md")
    perfil = (RAIZ / "perfil.md").read_text(encoding="utf-8")
    print(f"{len(fila)} vaga(s) para processar.{AJUDA}")

    # trabalha numa aba própria (as que o Edge abre sozinho ao iniciar podem sumir a qualquer hora)
    aba = ctx.new_page()
    for outra in ctx.pages:
        if outra != aba:
            outra.close()

    for i, cartao in enumerate(fila, 1):
        print(f"\n━━━ [{i}/{len(fila)}] {cartao['name']}")
        if not cartao["url_vaga"]:
            print("   cartão sem link da vaga — pulando")
            continue
        print(f"   {cartao['url_vaga']}")
        preench = Preenchedor(dados, respostas, escritor_claude(cfg, perfil, cartao["desc"]))
        if processar_vaga(ctx, cfg, cartao, preench, trello, aba) == "q":
            return
        for outra in ctx.pages:                  # fecha abas extras antes da próxima vaga
            if outra != aba:
                outra.close()

    print("\nFila concluída. Boa sorte! 🍀")


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
