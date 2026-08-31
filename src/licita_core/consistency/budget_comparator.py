"""Comparador de divergência de estimativa de preços e orçamento entre documentos (R7)."""

from __future__ import annotations

import re
from decimal import Decimal

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


def _to_decimal(val: str | float | int | Decimal | None) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _get_item_total_price(item: Item) -> tuple[Decimal | None, FieldValue | None]:
    for fv in item.field_values:
        if fv.field_type == FieldType.TOTAL_PRICE and fv.value is not None:
            d = _to_decimal(fv.value)
            if d is not None:
                return d, fv
    return None, None


def _get_doc_budget(doc: Document) -> tuple[Decimal | None, FieldValue | None]:
    for fv in doc.field_values:
        if fv.field_type == FieldType.TOTAL_PRICE and fv.value is not None:
            d = _to_decimal(fv.value)
            if d is not None:
                return d, fv
    return None, None


class BudgetComparator(ConsistencyComparator):
    """Detecta divergências de valores estimados e preços totais entre ETP e TR (CONST-005)."""

    @property
    def rule_id(self) -> str:
        return "CONST-005"

    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        findings: list[Finding] = []

        # 1. Compara orçamento global se presente em ambos no nível documental
        b_a, fv_a = _get_doc_budget(doc_a)
        b_b, fv_b = _get_doc_budget(doc_b)

        if b_a is not None and b_b is not None and b_a != b_b:
            ev_a = fv_a.evidence if fv_a and fv_a.evidence else []
            ev_b = fv_b.evidence if fv_b and fv_b.evidence else []
            if ev_a and ev_b:
                findings.append(
                    build_bilateral_finding(
                        rule_id=self.rule_id,
                        title="Divergência no Orçamento Global Estimado",
                        description=(
                            f"Orçamento global estimado divergente: R$ {b_a} no {doc_a.type.value} "
                            f"vs R$ {b_b} no {doc_b.type.value}."
                        ),
                        severity=Severity.HIGH,
                        evidence_a=ev_a,
                        evidence_b=ev_b,
                        process_id=process.id,
                    )
                )

        # 2. Compara preços totais por item correspondente
        matched_pairs = match_items_between_docs(doc_a, doc_b)
        for it_a, it_b in matched_pairs:
            tp_a, fv_tp_a = _get_item_total_price(it_a)
            tp_b, fv_tp_b = _get_item_total_price(it_b)

            if tp_a is not None and tp_b is not None and tp_a != tp_b:
                ev_a = fv_tp_a.evidence if fv_tp_a and fv_tp_a.evidence else it_a.evidence
                ev_b = fv_tp_b.evidence if fv_tp_b and fv_tp_b.evidence else it_b.evidence
                if ev_a and ev_b:
                    findings.append(
                        build_bilateral_finding(
                            rule_id=self.rule_id,
                            title=f"Divergência no Preço Total do Item ({it_a.id})",
                            description=(
                                f"Preço total estimado divergente para o Item {it_a.id}: "
                                f"R$ {tp_a} no {doc_a.type.value} vs R$ {tp_b} no {doc_b.type.value}."
                            ),
                            severity=Severity.HIGH,
                            evidence_a=ev_a,
                            evidence_b=ev_b,
                            process_id=process.id,
                        )
                    )

        return findings
