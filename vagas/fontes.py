"""Coletores de vagas. Cada função recebe a config e devolve uma lista de Vaga.

Se um site mudar o layout, só a função dele quebra — as outras continuam.
"""
from __future__ import annotations

import time
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .modelo import Vaga, limpar_html

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
sessao = requests.Session()
sessao.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})


def _get(url, **kw):
    r = sessao.get(url, timeout=30, **kw)
    r.raise_for_status()
    time.sleep(1)  # educação com os sites
    return r


# ---------------------------------------------------------------- Gupy
def gupy(cfg) -> list[Vaga]:
    api = "https://portal.gupy.io/api/job-search/jobs"
    vagas: list[Vaga] = []

    def baixar(params):
        offset = 0
        while True:
            d = _get(api, params={**params, "limit": 100, "offset": offset}).json()
            for j in d.get("data", []):
                yield j
            offset += 100
            if offset >= d.get("pagination", {}).get("total", 0) or offset >= 1000:
                break

    def converter(j):
        modalidade = {"remote": "remoto", "hybrid": "híbrido", "on-site": "presencial"}.get(
            j.get("workplaceType"), j.get("workplaceType") or ""
        )
        return Vaga(
            fonte="gupy",
            id_fonte=str(j["id"]),
            titulo=j["name"],
            empresa=j.get("careerPageName", ""),
            local=f'{j.get("city") or ""} - {j.get("state") or ""}'.strip(" -"),
            url=j["jobUrl"].split("?")[0],
            descricao=limpar_html(j.get("description", "")),
            modalidade=modalidade,
            data=(j.get("publishedDate") or "")[:10],
            estagio_confirmado=j.get("type") == "vacancy_type_internship",
        )

    # 1) tudo que é estágio na cidade
    for termo in ("estágio", "estagiário"):
        for j in baixar({"jobName": termo, "city": cfg["gupy_cidade"]}):
            vagas.append(converter(j))
    # 2) vagas remotas de TI do Brasil inteiro
    for termo in cfg["termos_busca"]:
        for j in baixar({"jobName": termo}):
            if j.get("workplaceType") == "remote":
                vagas.append(converter(j))
    return vagas


# ---------------------------------------------------------------- vagas.com
def vagas_com(cfg) -> list[Vaga]:
    vagas = []
    for termo in cfg["termos_busca"]:
        slug = termo.lower().replace("á", "a").replace(" ", "-")
        url = f"https://www.vagas.com.br/vagas-de-{quote(slug)}-em-rio-de-janeiro?ordenar_por=mais_recentes"
        soup = BeautifulSoup(_get(url).text, "html.parser")
        for li in soup.select("li.vaga"):
            a = li.select_one("a.link-detalhes-vaga")
            if not a:
                continue
            txt = lambda sel: (li.select_one(sel).get_text(" ", strip=True) if li.select_one(sel) else "")
            local = txt(".vaga-local")
            vagas.append(Vaga(
                fonte="vagas.com",
                id_fonte=a.get("data-id-vaga", a["href"]),
                titulo=a.get("title") or a.get_text(strip=True),
                empresa=txt(".emprVaga"),
                local=local.split("A empresa aceita")[0].strip(),
                url=urljoin("https://www.vagas.com.br", a["href"]),
                descricao=txt(".detalhes"),
                data=txt(".data-publicacao"),
                estagio_confirmado="estágio" in txt(".nivelVaga").lower(),
            ))
    return vagas


# ---------------------------------------------------------------- InfoJobs
def infojobs(cfg) -> list[Vaga]:
    vagas = []
    for termo in cfg["termos_busca"]:
        url = ("https://www.infojobs.com.br/empregos.aspx?palabra="
               f"{quote(termo)}&provincia=19&campo=griddate&orden=desc")
        soup = BeautifulSoup(_get(url).text, "html.parser")
        for card in soup.select("div.js_vacancyLoad"):
            t = card.select_one(".js_vacancyTitle")
            if not t:
                continue
            emp = card.select_one('a[href*="/empresa-"]')
            linhas = [d.get_text(" ", strip=True) for d in card.select("div.small.text-medium, div.mb-8")]
            local = next((l for l in linhas if " - " in l and "Km" in l or l == "Todo Brasil"), "")
            vagas.append(Vaga(
                fonte="infojobs",
                id_fonte=card.get("data-id", ""),
                titulo=t.get_text(strip=True),
                empresa=emp.get_text(" ", strip=True) if emp else "",
                local=local.split(",")[0],
                url=urljoin("https://www.infojobs.com.br", card.get("data-href", "")),
                descricao=card.get_text(" ", strip=True)[:1500],
                modalidade=next((m for m in ("Home office", "Híbrido", "Presencial")
                                 if m in card.get_text()), ""),
            ))
    return vagas


# ---------------------------------------------------------------- Jobzi
def jobzi(cfg) -> list[Vaga]:
    vagas = []
    for termo in cfg["termos_busca"]:
        for offset in (0, 20, 40):
            d = _get("https://api.jobzi.com/job", params={
                "offset": offset, "sort": "most-recent", "q": termo, "l": "rio de janeiro",
            }).json()
            for j in d.get("jobs", []):
                end = (j.get("addresses") or [{}])[0]
                vagas.append(Vaga(
                    fonte="jobzi",
                    id_fonte=j["id"],
                    titulo=j["title"],
                    empresa=(j.get("company") or {}).get("name") or "",
                    local=f'{end.get("city", "")} - {end.get("stateAbbreviation", "")}'.strip(" -"),
                    url=j.get("url") or f'https://jobzi.com/vaga/{j["id"]}',
                    descricao=limpar_html(j.get("description", ""))[:4000],
                    data=(j.get("datePosted") or "")[:10],
                ))
            if len(d.get("jobs", [])) < 20:
                break
    return vagas


# ---------------------------------------------------------------- Indeed
def indeed(cfg) -> list[Vaga]:
    """O Indeed bloqueia requisições automáticas, então abrimos o Edge de verdade.

    Uma janela vai aparecer por alguns segundos — é normal. Se aparecer um
    desafio "confirme que você é humano", resolva na janela; o script espera.
    """
    from playwright.sync_api import sync_playwright

    vagas = []
    with sync_playwright() as p:
        nav = p.chromium.launch(channel=cfg.get("navegador", "msedge"), headless=False)
        pag = nav.new_page()
        for termo in cfg["termos_busca"]:
            url = f"https://br.indeed.com/jobs?q={quote(termo)}&l=Rio+de+Janeiro%2C+RJ&fromage=14"
            pag.goto(url, wait_until="domcontentloaded")
            try:
                pag.wait_for_selector("a.jcs-JobTitle", timeout=60_000)
            except Exception:
                print(f"   [indeed] nenhuma vaga carregou para '{termo}' (bloqueio ou zero resultados)")
                continue
            for item in pag.evaluate("""() => [...document.querySelectorAll('a.jcs-JobTitle')].map(a => {
                    const c = a.closest('.job_seen_beacon') || a.closest('td') || a.parentElement;
                    const q = s => (c.querySelector(s)?.innerText || '').trim();
                    return {jk: a.dataset.jk || new URL(a.href).searchParams.get('jk'),
                            titulo: a.innerText.trim(), empresa: q('[data-testid=company-name]'),
                            local: q('[data-testid=text-location]'), texto: (c.innerText || '').slice(0, 1500)};
                })"""):
                if not item["jk"]:
                    continue
                vagas.append(Vaga(
                    fonte="indeed", id_fonte=item["jk"], titulo=item["titulo"],
                    empresa=item["empresa"], local=item["local"],
                    url=f"https://br.indeed.com/viewjob?jk={item['jk']}",
                    descricao=item["texto"],
                ))
            pag.wait_for_timeout(2000)
        nav.close()
    return vagas


TODAS = {
    "gupy": gupy,
    "vagas.com": vagas_com,
    "infojobs": infojobs,
    "jobzi": jobzi,
    "indeed": indeed,
}
