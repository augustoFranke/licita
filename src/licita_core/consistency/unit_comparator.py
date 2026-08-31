"""Comparador de divergência de unidade de fornecimento entre documentos (R7)."""

from __future__ import annotations

import re
from typing import Sequence

from licita_core.consistency.base import (
    ConsistencyComparator,
    build_bilateral_finding,
    match_items_between_docs,
)
from licita_core.schema import (
    Document,
    FieldType,
    FieldValue,
    Finding,
    Item,
    ProcurementProcess,
    Severity,
)

_UNIT_ALIASES = {
    "UN": "UNIDADE",
    "UND": "UNIDADE",
    "UNID": "UNIDADE",
    "UNIDADE": "UNIDADE",
    "UNIDADES": "UNIDADE",
    "PC": "PECA",
    "PCA": "PECA",
    "PECA": "PECA",
    "PECAS": "PECA",
    "PÇ": "PECA",
    "PÇA": "PECA",
    "CX": "CAIXA",
    "CXA": "CAIXA",
    "CAIXA": "CAIXA",
    "CAIXAS": "CAIXA",
    "PCT": "PACOTE",
    "PCTE": "PACOTE",
    "PACOTE": "PACOTE",
    "PACOTES": "PACOTE",
    "KG": "QUILOGRAMA",
    "KILO": "QUILOGRAMA",
    "QUILOGRAMA": "QUILOGRAMA",
    "L": "LITRO",
    "LT": "LITRO",
    "LITRO": "LITRO",
    "LITROS": "LITRO",
    "M": "METRO",
    "MT": "METRO",
    "METRO": "METRO",
    "M2": "METRO_QUADRADO",
    "M3": "METRO_CUBICO",
    "RL": "ROLO",
    "ROLO": "ROLO",
    "PAR": "PAR",
    "PARES": "PAR",
    "CJ": "CONJUNTO",
    "CONJUNTO": "CONJUNTO",
    "EMB": "EMBALAGEM",
    "EMBALAGEM": "EMBALAGEM",
}


def _norm_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = re.sub(r"[^\w]", "", unit.upper().strip())
    return _UNIT_ALIASES.get(u, u)


def _get_item_unit(item: Item) -> tuple[str | None, FieldValue | None]:
    for fv in item.field_values:
        if fv.field_type == FieldType.QUANTITY and fv.unit:
            return _norm_unit(fv.unit), fv
    return None, None


class UnitComparator(ConsistencyComparator):
    """Detecta divergências de unidade de fornecimento entre itens correspondentes em ETP e TR (CONST-002)."""

    @property
    def rule_id(self) -> str:
        return "CONST-002"

    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        findings: list[Finding] = []

        matched_pairs = match_items_between_docs(doc_a, doc_b)
        for it_a, it_b in matched_pairs:
            un_a, fv_a = _get_item_unit(it_a)
            un_b, fv_b = _get_item_unit(it_b)

            if un_a is not None and un_b is not None and un_a != un_b:
                ev_a = fv_a.evidence if fv_a and fv_a.evidence else it_a.evidence
                ev_b = fv_b.evidence if fv_b and fv_b.evidence else it_b.evidence

                if ev_a and ev_b:
                    findings.append(
                        build_bilateral_finding(
                            rule_id=self.rule_id,
                            title=f"Divergência de Unidade de Medida no Item ({it_a.id})",
                            description=(
                                f"Unidade de fornecimento divergente para o Item {it_a.id}: "
                                f"'{un_a}' no {doc_a.type.value} vs '{un_b}' no {doc_b.type.value}."
                            ),
                            severity=Severity.HIGH,
                            evidence_a=ev_a,
                            evidence_b=ev_b,
                            process_id=process.id,
                        )
                    )

        return findings
