"""Comparador de divergência de especificações e requisitos técnicos entre documentos (R7)."""

from __future__ import annotations

import re

from licita_core.consistency.base import (
    ConsistencyComparator,
    build_bilateral_finding,
    match_items_between_docs,
)
from licita_core.schema import (
    Document,
    Finding,
    Item,
    ProcurementProcess,
    Requirement,
    Severity,
)


def _get_requirements_map(item: Item) -> dict[str, Requirement]:
    return {req.attribute.lower().strip(): req for req in item.requirements}


class SpecificationComparator(ConsistencyComparator):
    """Detecta divergências de especificações técnicas e requisitos (ex: CATMAT, voltagem) entre ETP e TR (CONST-006)."""

    @property
    def rule_id(self) -> str:
        return "CONST-006"

    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        findings: list[Finding] = []

        matched_pairs = match_items_between_docs(doc_a, doc_b)
        for it_a, it_b in matched_pairs:
            reqs_a = _get_requirements_map(it_a)
            reqs_b = _get_requirements_map(it_b)

            common_attrs = set(reqs_a.keys()).intersection(set(reqs_b.keys()))
            for attr in sorted(common_attrs):
                r_a = reqs_a[attr]
                r_b = reqs_b[attr]

                val_a_str = str(r_a.value).strip().lower()
                val_b_str = str(r_b.value).strip().lower()

                if val_a_str != val_b_str:
                    ev_a = r_a.evidence if r_a.evidence else it_a.evidence
                    ev_b = r_b.evidence if r_b.evidence else it_b.evidence

                    if ev_a and ev_b:
                        findings.append(
                            build_bilateral_finding(
                                rule_id=self.rule_id,
                                title=f"Divergência de Requisito '{attr.upper()}' no Item ({it_a.id})",
                                description=(
                                    f"Requisito '{attr}' divergente para o Item {it_a.id}: "
                                    f"'{r_a.value}' no {doc_a.type.value} vs '{r_b.value}' no {doc_b.type.value}."
                                ),
                                severity=Severity.HIGH if attr == "catmat" else Severity.MEDIUM,
                                evidence_a=ev_a,
                                evidence_b=ev_b,
                                process_id=process.id,
                            )
                        )

        return findings
