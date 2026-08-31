"""Comparador de divergência quantitativa entre documentos (R7)."""

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


def _get_item_quantity(item: Item) -> tuple[float | None, FieldValue | None]:
    for fv in item.field_values:
        if fv.field_type == FieldType.QUANTITY and fv.value is not None:
            try:
                return float(fv.value), fv
            except (ValueError, TypeError):
                pass
    return None, None


class QuantityComparator(ConsistencyComparator):
    """Detecta divergências de quantidades entre itens correspondentes em ETP e TR (CONST-001)."""

    @property
    def rule_id(self) -> str:
        return "CONST-001"

    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        findings: list[Finding] = []

        matched_pairs = match_items_between_docs(doc_a, doc_b)
        for it_a, it_b in matched_pairs:
            qtd_a, fv_a = _get_item_quantity(it_a)
            qtd_b, fv_b = _get_item_quantity(it_b)

            if qtd_a is not None and qtd_b is not None and qtd_a != qtd_b:
                ev_a = fv_a.evidence if fv_a and fv_a.evidence else it_a.evidence
                ev_b = fv_b.evidence if fv_b and fv_b.evidence else it_b.evidence

                if ev_a and ev_b:
                    findings.append(
                        build_bilateral_finding(
                            rule_id=self.rule_id,
                            title=f"Divergência de Quantidade no Item ({it_a.id})",
                            description=(
                                f"Quantidade divergente para o Item {it_a.id}: "
                                f"{qtd_a} no {doc_a.type.value} vs {qtd_b} no {doc_b.type.value}."
                            ),
                            severity=Severity.HIGH,
                            evidence_a=ev_a,
                            evidence_b=ev_b,
                            process_id=process.id,
                        )
                    )

        return findings
