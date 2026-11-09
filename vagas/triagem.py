"""Filtro barato (palavras-chave) + nota de aderência dada pelo Claude."""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from .modelo import Vaga, normalizar

RE_ESTAGIO = re.compile(r"\b(estag|intern)", re.I)
RE_REMOTO = re.compile(r"remot|home ?office|todo brasil|100% online", re.I)


def eh_estagio(v: Vaga) -> bool:
    return v.estagio_confirmado or bool(RE_ESTAGIO.search(normalizar(v.titulo)))


def local_ok(v: Vaga, cfg) -> bool:
    texto = normalizar(f"{v.local} {v.modalidade}")
    if RE_REMOTO.search(texto):
        return True
    return any(normalizar(c) in texto for c in cfg["cidades_aceitas"])


def contem(texto_normalizado: str, termo: str) -> bool:
    """'desenvolv*' casa com prefixo; sem asterisco, só a palavra inteira ('ti' não casa com 'time')."""
    t = normalizar(termo.rstrip("*"))
    fim = "" if termo.endswith("*") else " "
    return f" {t}{fim}" in f" {texto_normalizado} "


def parece_ti(v: Vaga, cfg) -> bool:
    """TI no título basta. Senão, a descrição precisa citar ao menos 2 tecnologias concretas
    (evita 'Estágio em Controladoria' que só menciona Excel e 'dados')."""
    if any(contem(normalizar(v.titulo), p) for p in cfg["palavras_ti_titulo"]):
        return True
    desc = normalizar(v.descricao)
    return sum(contem(desc, t) for t in cfg["tecnologias_descricao"]) >= 2


def pre_filtrar(vagas: list[Vaga], cfg) -> list[Vaga]:
    return [v for v in vagas if eh_estagio(v) and local_ok(v, cfg) and parece_ti(v, cfg)]


# ----------------------------------------------------------------- Claude
class Avaliacao(BaseModel):
    area_ti: bool = Field(description="A vaga é de fato da área de TI/tecnologia/dados?")
    nota: int = Field(description="Aderência de 0 a 10 do candidato a esta vaga")
    motivo: str = Field(description="1-2 frases em português explicando a nota")
    faltando: list[str] = Field(description="Requisitos da vaga que o candidato não demonstra (pode ser vazio)")


INSTRUCOES = """Você ajuda um estudante a priorizar vagas de estágio. Compare a vaga com o perfil
e dê uma nota de aderência de 0 a 10:
- 9-10: stack e atividades batem quase totalmente; candidato deveria aplicar hoje.
- 6-8: boa aderência, alguns requisitos faltando mas aprendíveis.
- 3-5: área de TI, mas foco diferente (ex.: suporte de hardware para quem é dev).
- 0-2: não é TI, exige formação/período incompatível, ou não é estágio.
Considere a previsão de formatura do candidato: vagas que exigem formatura antes dela ou
curso específico que ele não faz devem cair. A descrição pode estar incompleta (só um
resumo da listagem); nesse caso, avalie pelo título e pelo que houver, sem punir a falta
de detalhes."""


class Triador:
    def __init__(self, cfg, perfil: str):
        self.cfg = cfg
        self.perfil = perfil
        self.cliente = None
        if os.getenv("ANTHROPIC_API_KEY"):
            import anthropic
            self.cliente = anthropic.Anthropic()

    @property
    def usando_claude(self) -> bool:
        return self.cliente is not None

    def avaliar(self, v: Vaga) -> Vaga:
        if self.cliente:
            try:
                return self._avaliar_claude(v)
            except Exception as e:  # rede, limite, recusa... cai no plano B
                print(f"   [triagem] Claude falhou em '{v.titulo[:40]}': {e}. Usando palavras-chave.")
        return self._avaliar_palavras(v)

    def _avaliar_claude(self, v: Vaga) -> Vaga:
        vaga_txt = (f"Título: {v.titulo}\nEmpresa: {v.empresa}\nLocal: {v.local} {v.modalidade}\n"
                    f"Fonte: {v.fonte}\nDescrição:\n{v.descricao[:6000]}")
        resp = self.cliente.messages.parse(
            model=self.cfg["modelo_claude"],
            max_tokens=2000,
            output_config={"effort": "low"},
            system=INSTRUCOES,
            messages=[{"role": "user", "content":
                       f"<perfil>\n{self.perfil}\n</perfil>\n\n<vaga>\n{vaga_txt}\n</vaga>"}],
            output_format=Avaliacao,
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise RuntimeError(f"sem avaliação (stop_reason={resp.stop_reason})")
        a = resp.parsed_output
        v.nota = max(0, min(10, a.nota)) if a.area_ti else min(a.nota, 2)
        v.motivo = a.motivo
        v.faltando = a.faltando
        return v

    def _avaliar_palavras(self, v: Vaga) -> Vaga:
        texto = normalizar(f"{v.titulo} {v.descricao}")
        achadas = [s.rstrip("*") for s in self.cfg["minhas_skills"] if contem(texto, s)]
        ti_no_titulo = any(contem(normalizar(v.titulo), p) for p in self.cfg["palavras_ti_titulo"])
        v.nota = min(10 if ti_no_titulo else 5, (3 if ti_no_titulo else 1) + 2 * len(achadas))
        v.motivo = ("Nota por palavras-chave (sem Claude). Skills encontradas: "
                    + (", ".join(achadas) or "nenhuma"))
        return v

    def avaliar_todas(self, vagas: list[Vaga]) -> list[Vaga]:
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(self.avaliar, vagas))
