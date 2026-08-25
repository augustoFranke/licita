"""Detecção de documentos copiados ou reutilizados.

O R1 pede para "marcar documentos explicitamente copiados/reutilizados quando
identificáveis". Três evidências são consideradas identificáveis, em ordem
decrescente de certeza:

``arquivo_identico``
    Mesmo SHA-256. Não há interpretação possível: é o mesmo arquivo.
``texto_quase_identico``
    Jaccard alto entre os conjuntos de *shingles* dos dois textos. Mesmo
    documento reeditado (cabeçalho, número do processo e datas trocados).
``contido_em``
    Quase todos os shingles de A aparecem em B, sem o inverso. É o padrão
    "Anexo I — Termo de Referência" embutido no corpo do edital.

Similaridade meramente estilística (dois TRs do mesmo órgão que compartilham
boilerplate) fica abaixo dos limiares de propósito: o objetivo é marcar cópia
identificável, não medir parentesco textual.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Sequence

#: Tamanho do n-grama de palavras. 8 é longo o bastante para que coincidências
#: entre textos jurídicos distintos sejam raras, e curto o bastante para
#: sobreviver a pequenas edições.
TAMANHO_SHINGLE = 8

#: Textos menores que isto não têm massa para sustentar uma conclusão de cópia.
MIN_SHINGLES = 40

LIMIAR_QUASE_IDENTICO = 0.80
LIMIAR_CONTENCAO = 0.80
LIMIAR_REUSO_PARCIAL = 0.35


def _palavras(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    # Números somem: quantidades, datas e valores são justamente o que muda
    # entre um documento e sua cópia, e mantê-los mascararia a cópia.
    return re.findall(r"[a-z]+", re.sub(r"\d+", " ", sem_acento.lower()))


def shingles(texto: str, tamanho: int = TAMANHO_SHINGLE) -> frozenset[int]:
    """Conjunto de impressões dos n-gramas do texto.

    O hash é o BLAKE2b truncado, não o ``hash()`` embutido: este último é
    aleatorizado por processo, e um corpus cujas marcas de cópia mudam a cada
    execução não é auditável.
    """
    palavras = _palavras(texto)
    if len(palavras) < tamanho:
        return frozenset()
    return frozenset(
        int.from_bytes(
            hashlib.blake2b(
                " ".join(palavras[i : i + tamanho]).encode("utf-8"), digest_size=8
            ).digest(),
            "big",
        )
        for i in range(len(palavras) - tamanho + 1)
    )


def jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    intersecao = len(a & b)
    return intersecao / (len(a) + len(b) - intersecao)


def contencao(a: frozenset[int], b: frozenset[int]) -> float:
    """Fração de ``a`` presente em ``b``."""
    return len(a & b) / len(a) if a else 0.0


@dataclass(slots=True)
class DocumentoTexto:
    """Identificação mínima de um documento para a análise de reuso."""

    documento_id: str
    processo_id: str
    papel: str
    sha256: str
    texto: str


@dataclass(slots=True)
class Marca:
    tipo: str
    documento_id: str
    outro_documento_id: str
    processo_id: str
    outro_processo_id: str
    mesmo_processo: bool
    jaccard: float
    contencao: float
    detalhe: str


def _marca(
    tipo: str, a: DocumentoTexto, b: DocumentoTexto, j: float, c: float, detalhe: str
) -> Marca:
    return Marca(
        tipo=tipo,
        documento_id=a.documento_id,
        outro_documento_id=b.documento_id,
        processo_id=a.processo_id,
        outro_processo_id=b.processo_id,
        mesmo_processo=a.processo_id == b.processo_id,
        jaccard=round(j, 4),
        contencao=round(c, 4),
        detalhe=detalhe,
    )


def detectar(documentos: Sequence[DocumentoTexto]) -> list[Marca]:
    """Compara todos os pares e devolve as marcas de cópia/reuso encontradas."""
    marcas: list[Marca] = []

    por_hash: dict[str, list[DocumentoTexto]] = {}
    for documento in documentos:
        por_hash.setdefault(documento.sha256, []).append(documento)
    identicos: set[tuple[str, str]] = set()
    for iguais in por_hash.values():
        for a, b in combinations(sorted(iguais, key=lambda d: d.documento_id), 2):
            identicos.add((a.documento_id, b.documento_id))
            marcas.append(
                _marca("arquivo_identico", a, b, 1.0, 1.0, f"SHA-256 idêntico ({a.sha256[:12]}…)")
            )

    impressoes = {d.documento_id: shingles(d.texto) for d in documentos}
    comparaveis = [d for d in documentos if len(impressoes[d.documento_id]) >= MIN_SHINGLES]

    for a, b in combinations(sorted(comparaveis, key=lambda d: d.documento_id), 2):
        if (a.documento_id, b.documento_id) in identicos:
            continue
        sa, sb = impressoes[a.documento_id], impressoes[b.documento_id]
        j = jaccard(sa, sb)
        ca, cb = contencao(sa, sb), contencao(sb, sa)

        if j >= LIMIAR_QUASE_IDENTICO:
            marcas.append(
                _marca("texto_quase_identico", a, b, j, max(ca, cb), f"Jaccard {j:.2f}")
            )
        elif ca >= LIMIAR_CONTENCAO or cb >= LIMIAR_CONTENCAO:
            dentro, fora, valor = (a, b, ca) if ca >= cb else (b, a, cb)
            marcas.append(
                _marca(
                    "contido_em",
                    dentro,
                    fora,
                    j,
                    valor,
                    f"{valor:.0%} do texto de {dentro.papel} aparece em {fora.papel}",
                )
            )
        elif j >= LIMIAR_REUSO_PARCIAL:
            marcas.append(_marca("reuso_parcial", a, b, j, max(ca, cb), f"Jaccard {j:.2f}"))

    return marcas


def resumir(marcas: Iterable[Marca]) -> dict[str, int]:
    resumo: dict[str, int] = {}
    for marca in marcas:
        chave = f"{marca.tipo}:{'intra' if marca.mesmo_processo else 'entre'}_processos"
        resumo[chave] = resumo.get(chave, 0) + 1
    return resumo
