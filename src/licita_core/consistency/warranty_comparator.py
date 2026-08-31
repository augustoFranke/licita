"""Comparador de divergência de prazos de garantia técnica entre documentos (R7)."""

from __future__ import annotations

import re
from decimal import Decimal

from licita_core.consistency.base import ConsistencyComparator, build_bilateral_finding
from licita_core.schema import (
    Document,
    FieldType,
    FieldValue,
    Finding,
    ProcurementProcess,
    Severity,
)


def _norm_warranty_months(val: str | int | float | None) -> int | None:
    if val is None:
        return None
    s = str(val).lower().strip()
    match_ano = re.search(r"(\d+)\s*ano", s)
    if match_ano:
        return int(match_ano.group(1)) * 12
    match_mes = re.search(r"(\d+)\s*m[eê]s", s)
    if match_mes:
        return int(match_mes.group(1))
    match_num = re.search(r"^(\d+)$", s)
    if match_num:
        return int(match_num.group(1))
    return None


def _get_document_warranty(doc: Document) -> tuple[int | None, FieldValue | None]:
    for fv in doc.field_values:
        if fv.field_type == FieldType.WARRANTY_TERM and fv.value is not None:
            months = _norm_warranty_months(fv.value)
            if months is not None:
                return months, fv
    return None, None


class WarrantyComparator(ConsistencyComparator):
    """Detecta divergências no prazo de garantia técnica estipulado entre ETP e TR (CONST-004)."""

    @property
    def rule_id(self) -> str:
        return "CONST-004"

    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        findings: list[Finding] = []

        w_a, fv_a = _get_document_warranty(doc_a)
        w_b, fv_b = _get_document_warranty(doc_b)

        if w_a is not None and w_b is not None and w_a != w_b:
            ev_a = fv_a.evidence if fv_a and fv_a.evidence else []
            ev_b = fv_b.evidence if fv_b and fv_b.evidence else []

            if ev_a and ev_b:
                findings.append(
                    build_bilateral_finding(
                        rule_id=self.rule_id,
                        title="Divergência no Prazo de Garantia Técnica",
                        description=(
                            f"Prazo de garantia técnica divergente: {w_a} meses no {doc_a.type.value} "
                            f"vs {w_b} meses no {doc_b.type.value}."
                        ),
                        severity=Severity.HIGH,
                        evidence_a=ev_a,
                        evidence_b=ev_b,
                        process_id=process.id,
                    )
                )

        return findings
