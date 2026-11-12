"""Integração com o Trello: cria o quadro na primeira vez e adiciona um cartão por vaga."""
from __future__ import annotations

import os
import re

import requests

from .modelo import Vaga

API = "https://api.trello.com/1"
COLUNAS = ["Encontradas", "Vou aplicar", "Aplicada", "Entrevista", "Descartada / Recusada"]
CORES_FONTE = {"gupy": "green", "vagas.com": "blue", "infojobs": "orange",
               "jobzi": "purple", "indeed": "sky", "solides": "pink", "linkedin": "black"}
# etiquetas que o aplicar.py coloca nos cartões de "Vou aplicar" (dá pra ver no quadro sem abrir)
STATUS = {"pronta": ("🤖 pronta p/ enviar", "green"),
          "voce": ("🤖 precisa de você", "orange"),
          "direto": ("🤖 envio direto no site", "yellow")}


class Trello:
    def __init__(self, nome_quadro: str):
        self.auth = {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}
        self.quadro = self._quadro(nome_quadro)
        self.colunas = self._colunas()
        self.coluna_nova = self.colunas[COLUNAS[0]]
        self.etiquetas = self._etiquetas()

    def _req(self, metodo, caminho, **params):
        r = requests.request(metodo, f"{API}{caminho}", params={**self.auth, **params}, timeout=30)
        r.raise_for_status()
        return r.json()

    def _quadro(self, nome):
        for q in self._req("GET", "/members/me/boards", fields="name,closed"):
            if q["name"] == nome and not q["closed"]:
                return q["id"]
        print(f"   [trello] criando quadro '{nome}'")
        return self._req("POST", "/boards", name=nome, defaultLists="false")["id"]

    def _colunas(self):
        existentes = {l["name"]: l["id"] for l in self._req("GET", f"/boards/{self.quadro}/lists")}
        for pos, nome in enumerate(COLUNAS):
            if nome not in existentes:
                existentes[nome] = self._req("POST", "/lists", name=nome,
                                             idBoard=self.quadro, pos=(pos + 1) * 1000)["id"]
        return existentes

    def _etiquetas(self):
        existentes = {l["name"]: l["id"] for l in self._req("GET", f"/boards/{self.quadro}/labels")}
        for fonte, cor in CORES_FONTE.items():
            if fonte not in existentes:
                existentes[fonte] = self._req("POST", "/labels", name=fonte, color=cor,
                                              idBoard=self.quadro)["id"]
        return existentes

    def urls_existentes(self) -> set[str]:
        """Evita duplicar cartões mesmo se o arquivo de histórico for apagado."""
        cartoes = self._req("GET", f"/boards/{self.quadro}/cards", fields="desc")
        return {linha.split("](")[-1].rstrip(")") for c in cartoes
                for linha in c["desc"].splitlines() if linha.startswith("**Link:**")}

    # ------------------------------------------------------------ fase 2
    def cartoes(self, coluna: str) -> list[dict]:
        """Cartões de uma coluna, já com a URL da vaga extraída da descrição."""
        lista = self._req("GET", f"/lists/{self.colunas[coluna]}/cards", fields="name,desc,url,idLabels")
        for c in lista:
            m = re.search(r"\*\*Link:\*\*\s*\[[^\]]*\]\(([^)]+)\)", c["desc"]) or \
                re.search(r"https?://\S+", c["desc"] + " " + c["name"])
            c["url_vaga"] = (m.group(1) if m.groups() else m.group(0)) if m else ""
        return lista

    def _etiqueta_status(self, status: str) -> str:
        nome, cor = STATUS[status]
        if nome not in self.etiquetas:
            self.etiquetas[nome] = self._req("POST", "/labels", name=nome, color=cor, idBoard=self.quadro)["id"]
        return self.etiquetas[nome]

    def limpar_status(self, cartao: dict):
        """Tira as etiquetas de status do assistente (as de fonte, tipo 'gupy', ficam)."""
        ids = {self.etiquetas.get(nome) for nome, _ in STATUS.values()}
        for lid in list(cartao.get("idLabels", [])):
            if lid in ids:
                self._req("DELETE", f"/cards/{cartao['id']}/idLabels/{lid}")
                cartao["idLabels"].remove(lid)

    def marcar_status(self, cartao: dict, status: str, comentario: str = ""):
        """Troca a etiqueta de status do cartão e deixa um comentário com o detalhe."""
        alvo = self._etiqueta_status(status)
        for outro in STATUS:                     # garante que as 3 existem (para limpar depois)
            self._etiqueta_status(outro)
        if alvo not in cartao.get("idLabels", []):
            self.limpar_status(cartao)
            self._req("POST", f"/cards/{cartao['id']}/idLabels", value=alvo)
            cartao.setdefault("idLabels", []).append(alvo)
        if comentario:
            self._req("POST", f"/cards/{cartao['id']}/actions/comments", text=comentario)

    def mover(self, cartao_id: str, coluna: str, comentario: str = ""):
        self._req("PUT", f"/cards/{cartao_id}", idList=self.colunas[coluna], pos="top")
        if comentario:
            self._req("POST", f"/cards/{cartao_id}/actions/comments", text=comentario)

    def adicionar(self, v: Vaga):
        faltando = "\n".join(f"- {f}" for f in v.faltando) or "- nada relevante"
        desc = (
            f"**Nota:** {v.nota}/10 — {v.motivo}\n\n"
            f"**Empresa:** {v.empresa or '—'}\n"
            f"**Local:** {v.local or '—'} {('(' + v.modalidade + ')') if v.modalidade else ''}\n"
            f"**Publicada:** {v.data or '—'}\n"
            f"**Fonte:** {v.fonte}\n"
            f"**Link:** [abrir vaga]({v.url})\n\n"
            f"**O que pode faltar:**\n{faltando}\n\n"
            f"---\n{v.descricao[:3000]}"
        )
        nome = f"[{v.nota}] {v.titulo} — {v.empresa}".strip(" —")
        self._req("POST", "/cards", idList=self.coluna_nova, name=nome[:250], desc=desc,
                  idLabels=self.etiquetas.get(v.fonte, ""), pos="bottom")
