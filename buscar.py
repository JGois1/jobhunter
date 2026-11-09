"""Busca vagas de estágio de TI, dá nota com o Claude e manda as boas para o Trello.

Uso:
    python buscar.py                 # todas as fontes, envia ao Trello
    python buscar.py --sem-trello    # só gera o CSV (bom para testar)
    python buscar.py --fontes gupy jobzi
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from vagas.fontes import TODAS
from vagas.triagem import Triador, pre_filtrar

RAIZ = Path(__file__).parent
HISTORICO = RAIZ / "dados" / "historico.json"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(RAIZ / ".env")
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    perfil = (RAIZ / "perfil.md").read_text(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--fontes", nargs="*", default=cfg["fontes_ativas"], choices=list(TODAS))
    ap.add_argument("--sem-trello", action="store_true")
    ap.add_argument("--reavaliar", action="store_true", help="ignora o histórico e avalia tudo de novo")
    args = ap.parse_args()

    HISTORICO.parent.mkdir(exist_ok=True)
    historico = {} if args.reavaliar or not HISTORICO.exists() else json.loads(HISTORICO.read_text("utf-8"))

    # 1) coleta
    todas = []
    for nome in args.fontes:
        print(f"→ buscando em {nome}...")
        try:
            achadas = TODAS[nome](cfg)
            print(f"   {len(achadas)} vagas")
            todas += achadas
        except Exception as e:
            print(f"   [{nome}] falhou: {e}  (seguindo com as outras fontes)")

    # 2) remove duplicadas (mesma vaga em buscas/fontes diferentes) e já vistas
    unicas, vistas_conteudo = {}, set()
    for v in todas:
        if v.chave in unicas or v.chave_conteudo in vistas_conteudo:
            continue
        unicas[v.chave] = v
        vistas_conteudo.add(v.chave_conteudo)
    candidatas = pre_filtrar(list(unicas.values()), cfg)
    novas = [v for v in candidatas if v.chave not in historico]
    print(f"\n{len(todas)} coletadas → {len(unicas)} únicas → {len(candidatas)} estágios de TI no RJ/remotos "
          f"→ {len(novas)} novas")
    if not novas:
        print("Nada novo desta vez.")
        return

    # 3) triagem
    triador = Triador(cfg, perfil)
    print(f"→ avaliando {len(novas)} vagas "
          f"({'Claude ' + cfg['modelo_claude'] if triador.usando_claude else 'palavras-chave — sem ANTHROPIC_API_KEY'})...")
    novas = sorted(triador.avaliar_todas(novas), key=lambda v: -(v.nota or 0))

    # 4) CSV com tudo (abre no Excel)
    saida = RAIZ / "dados" / f"vagas_{datetime.now():%Y-%m-%d_%H%M}.csv"
    with saida.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nota", "titulo", "empresa", "local", "modalidade", "fonte", "data", "motivo", "faltando", "url"])
        for v in novas:
            w.writerow([v.nota, v.titulo, v.empresa, v.local, v.modalidade, v.fonte, v.data,
                        v.motivo, "; ".join(v.faltando), v.url])
    print(f"   planilha salva em {saida.relative_to(RAIZ)}")

    # 5) Trello
    boas = [v for v in novas if (v.nota or 0) >= cfg["nota_minima_trello"]]
    if args.sem_trello:
        print(f"   {len(boas)} vagas teriam ido ao Trello (nota ≥ {cfg['nota_minima_trello']}).")
    else:
        from vagas.trello import Trello
        t = Trello(cfg["quadro_trello"])
        ja_no_quadro = t.urls_existentes()
        enviadas = 0
        for v in boas:
            if v.url not in ja_no_quadro:
                t.adicionar(v)
                enviadas += 1
        print(f"   {enviadas} cartões novos no quadro '{cfg['quadro_trello']}'")

    # 6) histórico — só depois de tudo dar certo (e não em modo de teste)
    for v in ([] if args.sem_trello else novas):
        historico[v.chave] = {"nota": v.nota, "titulo": v.titulo, "visto_em": f"{datetime.now():%Y-%m-%d}"}
    HISTORICO.write_text(json.dumps(historico, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\nTop 10:")
    for v in novas[:10]:
        print(f"  [{v.nota:>2}] {v.titulo[:60]} — {v.empresa[:30]} ({v.fonte})")


if __name__ == "__main__":
    main()
