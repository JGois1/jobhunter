from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Vaga:
    fonte: str          # gupy, vagas.com, infojobs, jobzi, indeed
    id_fonte: str       # id dentro da fonte
    titulo: str
    empresa: str
    local: str
    url: str
    descricao: str = ""
    modalidade: str = ""   # presencial / híbrido / remoto (quando a fonte informa)
    data: str = ""
    estagio_confirmado: bool = False  # a própria fonte marcou como estágio

    # preenchidos pela triagem
    nota: int | None = None
    motivo: str = ""
    faltando: list[str] = field(default_factory=list)

    @property
    def chave(self) -> str:
        return f"{self.fonte}:{self.id_fonte}"

    @property
    def chave_conteudo(self) -> str:
        """Usada para detectar a mesma vaga publicada em fontes diferentes."""
        # empresa reduzida às 4 primeiras letras: "IBEU" e "Ibeu - Inglês Global" viram a mesma
        empresa = normalizar(self.empresa).replace(" ", "")[:4]
        return f"{normalizar(self.titulo)}|{empresa}"


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9|]+", " ", texto.lower()).strip()


def limpar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = texto.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", texto).strip()
