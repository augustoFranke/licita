"""Seleção determinística entre cadeias completas do coletor rarest-first."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Cotas:
    processos: int = 30
    orgaos_distintos: int = 5
    categorias_distintas: int = 3
    max_por_orgao: int = 6


@dataclass(slots=True)
class Candidato:
    registro: dict[str, Any]

    @property
    def numero(self) -> str:
        return self.registro["numero_controle_pncp"]

    @property
    def compra(self) -> dict[str, Any]:
        return self.registro["compra"]

    @property
    def contratos(self) -> list[dict[str, Any]]:
        return self.registro["contratos"]

    @property
    def documentos_compra(self) -> list[dict[str, Any]]:
        return self.registro["documentos_compra"]

    @property
    def documento_contrato(self) -> dict[str, Any]:
        return self.registro["documento_contrato"]

    @property
    def orgao(self) -> str:
        return self.compra.get("cnpj_orgao") or ""

    @property
    def categoria(self) -> str:
        return self.compra.get("categoria_objeto") or "outros_bens"


@dataclass(slots=True)
class Estado:
    cotas: Cotas
    selecionados: list[Candidato] = field(default_factory=list)

    def deficits(self) -> dict[str, int]:
        return {
            "processos": max(0, self.cotas.processos - len(self.selecionados)),
            "orgaos": max(
                0, self.cotas.orgaos_distintos - len({c.orgao for c in self.selecionados})
            ),
            "categorias": max(
                0,
                self.cotas.categorias_distintas
                - len({c.categoria for c in self.selecionados}),
            ),
        }

    def por_orgao(self, cnpj: str) -> int:
        return sum(c.orgao == cnpj for c in self.selecionados)


def selecionar(
    candidatos: Iterable[Candidato],
    cotas: Cotas = Cotas(),
    iniciais: Sequence[Candidato] = (),
) -> tuple[list[Candidato], dict[str, int]]:
    """Escolhe cadeias completas priorizando diversidade e ordem oficial."""
    ja = {c.numero for c in iniciais}
    restantes = sorted(
        (c for c in candidatos if c.numero not in ja),
        key=lambda c: (
            c.contratos[0].get("data_publicacao_pncp") or "",
            c.numero,
        ),
    )
    estado = Estado(cotas, list(iniciais))

    while len(estado.selecionados) < cotas.processos and restantes:
        permitidos = [
            c for c in restantes if estado.por_orgao(c.orgao) < cotas.max_por_orgao
        ]
        if not permitidos:
            break
        falta = estado.deficits()
        orgaos = {c.orgao for c in estado.selecionados}
        categorias = {c.categoria for c in estado.selecionados}
        melhor = max(
            permitidos,
            key=lambda c: (
                int(falta["orgaos"] > 0 and c.orgao not in orgaos),
                int(falta["categorias"] > 0 and c.categoria not in categorias),
                -estado.por_orgao(c.orgao),
                -(restantes.index(c)),
            ),
        )
        estado.selecionados.append(melhor)
        restantes.remove(melhor)

    return estado.selecionados, estado.deficits()
