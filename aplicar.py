"""Assistente de candidatura: pega os cartões em "Vou aplicar" no Trello, abre cada vaga,
preenche o formulário e espera VOCÊ revisar e enviar.

Uso:
    python aplicar.py           # processa a coluna "Vou aplicar"
    python aplicar.py --login   # só abre o navegador para você fazer login nos sites (1ª vez)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from vagas.preenchedor import Preenchedor, carregar_respostas
from vagas.trello import Trello

RAIZ = Path(__file__).parent
PERFIL_NAVEGADOR = RAIZ / "dados" / "navegador"   # guarda seus logins entre execuções
SESSAO = RAIZ / "dados" / "sessao.json"         # cópia dos cookies de login (inclui os "de sessão")
PORTA_LOGIN = 9333
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

AJUDA = """
  [Enter]  preencher de novo (use depois de avançar para a próxima etapa do formulário)
  s        já ENVIEI → move o cartão para "Aplicada"
  d        descartar → move para "Descartada / Recusada"
  p        pular por agora (o cartão fica em "Vou aplicar")
  q        sair
"""


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


def mostrar(rel):
    for rotulo, valor in rel["preenchidos"]:
        print(f"   ✓ {rotulo}: {valor}")
    for pergunta, estado in rel["perguntas"]:
        print(f"   ✎ pergunta '{pergunta}': {estado}")
    for p in rel["pendentes"]:
        print(f"   ! obrigatório sem resposta: {p}")
    if not any(rel.values()):
        print("   (nenhum campo de formulário encontrado nesta tela — faça login ou avance, depois Enter)")


def abrir_navegador(p, cfg):
    PERFIL_NAVEGADOR.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(PERFIL_NAVEGADOR), channel=cfg.get("navegador", "msedge"), headless=False,
        viewport=None, args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def caminho_edge() -> str:
    for c in [shutil.which("msedge"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
        if c and Path(c).exists():
            return c
    sys.exit("Não achei o Microsoft Edge instalado.")


def carregar_sessao(ctx):
    """Repõe os cookies salvos. Muitos sites (a Gupy, por exemplo) guardam o login num cookie
    "de sessão", que o navegador apaga ao fechar; por isso o assistente guarda uma cópia."""
    if SESSAO.exists():
        try:
            ctx.add_cookies(json.loads(SESSAO.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"(não consegui repor os logins salvos: {e})")


def salvar_sessao(ctx):
    try:
        SESSAO.write_text(json.dumps(ctx.cookies()), encoding="utf-8")
    except Exception:
        pass  # navegador já fechado: fica a última cópia salva


def porta_aberta(espera=10) -> bool:
    """O Edge de login responde na porta de depuração? (espera até `espera` segundos)"""
    import socket
    fim = time.time() + espera
    while time.time() < fim:
        try:
            socket.create_connection(("127.0.0.1", PORTA_LOGIN), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.5)
    return False


def login_manual():
    """Abre o Edge NORMAL no perfil do assistente, para você fazer login.

    O Google bloqueia login ("Esse navegador pode não ser seguro") em navegador controlado
    por automação. Aqui o Edge abre como um navegador comum; só depois que você termina e
    aperta Enter o script se conecta a ele para copiar os cookies de login.
    """
    PERFIL_NAVEGADOR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([caminho_edge(), f"--user-data-dir={PERFIL_NAVEGADOR}",
                      f"--remote-debugging-port={PORTA_LOGIN}",
                      "--no-first-run", "--new-window", *SITES_LOGIN])
    if not porta_aberta():
        # o Edge repassou as abas para uma janela do assistente que já estava aberta
        print("⚠ Já há uma janela do Edge do assistente aberta (de um aplicar.py anterior).")
        print("  Feche TODAS as janelas dela e rode de novo: python aplicar.py --login")
        return
    print("Abri o Edge com os sites. Faça login (pode usar 'Entrar com Google').")
    input("Quando terminar, volte aqui e aperte Enter (NÃO feche o Edge antes)... ")
    if not porta_aberta(1):
        print("O Edge foi fechado antes do Enter, então não deu para copiar os logins. Rode de novo.")
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTA_LOGIN}")
        salvar_sessao(nav.contexts[0])
        n = len(nav.contexts[0].cookies())
        for pg in nav.contexts[0].pages:      # fechar todas as abas fecha o Edge
            pg.close()
    print(f"Logins salvos ({n} cookies). Agora é só usar: python aplicar.py")


def processar_fila(ctx, cfg):
    dados = json.loads((RAIZ / "dados_pessoais.json").read_text(encoding="utf-8"))
    respostas = carregar_respostas(RAIZ / "respostas.md")
    perfil = (RAIZ / "perfil.md").read_text(encoding="utf-8")
    trello = Trello(cfg["quadro_trello"])
    fila = trello.cartoes("Vou aplicar")
    if not fila:
        print('Nenhum cartão em "Vou aplicar". Mova no Trello as vagas que você quer e rode de novo.')
        return

    print(f'{len(fila)} vaga(s) em "Vou aplicar".{AJUDA}')
    pagina = ctx.pages[0] if ctx.pages else ctx.new_page()

    for i, cartao in enumerate(fila, 1):
        print(f"\n━━━ [{i}/{len(fila)}] {cartao['name']}")
        if not cartao["url_vaga"]:
            print("   cartão sem link da vaga — pulando")
            continue
        print(f"   {cartao['url_vaga']}")
        pagina.goto(cartao["url_vaga"], wait_until="domcontentloaded")
        pagina.wait_for_timeout(2500)
        preench = Preenchedor(dados, respostas, escritor_claude(cfg, perfil, cartao["desc"]))

        n_abas = len(ctx.pages)
        if preench.clicar_candidatar(pagina):
            print("   cliquei no botão de candidatura")
            pagina.wait_for_timeout(3000)
        else:
            print("   não reconheci o botão de candidatura: clique você no navegador e aperte Enter aqui")
            print("   (evite 'Candidatura rápida' / '1 clique': costuma enviar sem você revisar)")
            vistos = {b["texto"] for b in preench.textos_botoes(pagina)
                      if re.search(r"candid|aplic|inscr|apply", b["texto"], re.I)}
            if vistos:
                print(f"   botões parecidos que vi na página: {sorted(vistos)}")
        if len(ctx.pages) > n_abas:      # o site abriu o formulário em outra aba
            pagina = ctx.pages[-1]

        while True:
            ativa = ctx.pages[-1]
            mostrar(preench.preencher(ativa))
            cmd = input("   revise no navegador → [Enter]=preencher de novo  s=enviei  d=descartar  p=pular  q=sair: ").strip().lower()
            salvar_sessao(ctx)           # guarda o login, caso você tenha entrado agora
            if cmd == "s":
                trello.mover(cartao["id"], "Aplicada", f"Candidatura enviada em {datetime.now():%d/%m/%Y %H:%M}")
                print("   → movido para Aplicada")
                break
            if cmd == "d":
                trello.mover(cartao["id"], "Descartada / Recusada", "Descartada antes de aplicar")
                print("   → movido para Descartada")
                break
            if cmd == "p":
                break
            if cmd == "q":
                return

        for extra in ctx.pages[1:]:      # fecha abas extras antes da próxima vaga
            extra.close()
        pagina = ctx.pages[0]

    print("\nFila concluída. Boa sorte! 🍀")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(RAIZ / ".env")
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    args = ap.parse_args()

    if args.login:
        login_manual()
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = abrir_navegador(p, cfg)
        carregar_sessao(ctx)
        try:
            processar_fila(ctx, cfg)
        finally:
            salvar_sessao(ctx)
            ctx.close()


if __name__ == "__main__":
    main()
