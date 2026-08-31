"""Comparador de divergência de prazos de entrega entre documentos (R7)."""

from __future__ import annotations

from licita_core.consistency.base import ConsistencyComparator, build_bilateral_finding
from licita_core.schema import (
    Document,
    FieldType,
    FieldValue,
    Finding,
    ProcurementProcess,
    Severity,
)


def _get_document_deadline(doc: Document) -> tuple[int | None, FieldValue | None]:
    for fv in doc.field_values:
        if fv.field_type == FieldType.DELIVERY_DEADLINE and fv.value is not None:
            try:
                return int(fv.value), fv
            except (ValueError, TypeError):
                pass
    return None, None


class DeliveryDeadlineComparator(ConsistencyComparator):
    """Detecta divergências no prazo de entrega estipulado entre ETP e TR (CONST-003)."""

    @property
    def rule_id(self) -> str:
        return "CONST-003"

    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        findings: list[Finding] = []

        deadline_a, fv_a = _get_document_deadline(doc_a)
        deadline_b, fv_b = _get_document_deadline(doc_b)

        if deadline_a is not None and deadline_b is not None and deadline_a != deadline_b:
            ev_a = fv_a.evidence if fv_a and fv_a.evidence else []
            ev_b = fv_b.evidence if fv_b and fv_b.evidence else []

            if ev_a and ev_b:
                findings.append(
                    build_bilateral_finding(
                        rule_id=self.rule_id,
                        title="Divergência no Prazo de Entrega",
                        description=(
                            f"Prazo de entrega divergente: {deadline_a} dias no {doc_a.type.value} "
                            f"vs {deadline_b} dias no {doc_b.type.value}."
                        ),
                        severity=Severity.HIGH,
                        evidence_a=ev_a,
                        evidence_b=ev_b,
                        process_id=process.id,
                    )
                )

        return findings
