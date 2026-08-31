"""Motor central de Consistência Cruzada entre Documentos (Fase R7)."""

from __future__ import annotations

from typing import Sequence

from licita_core.consistency.base import ConsistencyComparator
from licita_core.consistency.budget_comparator import BudgetComparator
from licita_core.consistency.deadline_comparator import DeliveryDeadlineComparator
from licita_core.consistency.quantity_comparator import QuantityComparator
from licita_core.consistency.specification_comparator import (
    SpecificationComparator,
)
from licita_core.consistency.unit_comparator import UnitComparator
from licita_core.consistency.warranty_comparator import WarrantyComparator
from licita_core.schema import (
    Document,
    DocumentType,
    Finding,
    ProcurementProcess,
)


class ConsistencyEngine:
    """Motor de análise de consistência entre pares de documentos da contratação."""

    def __init__(
        self,
        comparators: Sequence[ConsistencyComparator] | None = None,
    ) -> None:
        self.comparators: list[ConsistencyComparator] = (
            list(comparators)
            if comparators is not None
            else [
                QuantityComparator(),
                UnitComparator(),
                DeliveryDeadlineComparator(),
                WarrantyComparator(),
                BudgetComparator(),
                SpecificationComparator(),
            ]
        )

    def compare_documents(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        """Executa todos os comparadores entre um par de documentos."""
        findings: list[Finding] = []
        for comp in self.comparators:
            comp_findings = comp.compare(doc_a, doc_b, process)
            findings.extend(comp_findings)
        return findings

    def run(self, process: ProcurementProcess) -> list[Finding]:
        """Analisa todos os pares relevantes de documentos presentes no processo."""
        findings: list[Finding] = []
        docs_by_type: dict[DocumentType, Document] = {d.type: d for d in process.documents}

        # 1. Par principal: ETP ↔ TR
        if DocumentType.ETP in docs_by_type and DocumentType.TR in docs_by_type:
            etp = docs_by_type[DocumentType.ETP]
            tr = docs_by_type[DocumentType.TR]
            findings.extend(self.compare_documents(etp, tr, process))

        # 2. Par secundário: TR ↔ EDITAL
        if DocumentType.TR in docs_by_type and DocumentType.EDITAL in docs_by_type:
            tr = docs_by_type[DocumentType.TR]
            edital = docs_by_type[DocumentType.EDITAL]
            findings.extend(self.compare_documents(tr, edital, process))

        # 3. Par secundário: TR ↔ CONTRATO
        if DocumentType.TR in docs_by_type and DocumentType.CONTRATO in docs_by_type:
            tr = docs_by_type[DocumentType.TR]
            contrato = docs_by_type[DocumentType.CONTRATO]
            findings.extend(self.compare_documents(tr, contrato, process))

        # 4. Par secundário: DFD ↔ ETP
        if DocumentType.DFD in docs_by_type and DocumentType.ETP in docs_by_type:
            dfd = docs_by_type[DocumentType.DFD]
            etp = docs_by_type[DocumentType.ETP]
            findings.extend(self.compare_documents(dfd, etp, process))

        return findings
