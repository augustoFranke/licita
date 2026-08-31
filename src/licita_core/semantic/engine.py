"""Orquestrador Central da Camada Semântica (Fase R9)."""

from __future__ import annotations

from licita_core.schema import Finding, ProcurementProcess
from licita_core.semantic.atomic_engine import AtomicRequirementEngine
from licita_core.semantic.linter import SemanticLinter


class SemanticEngine:
    """Motor central para decomposição semântica e auditoria de requisitos."""

    def __init__(
        self,
        atomic_engine: AtomicRequirementEngine | None = None,
        linter: SemanticLinter | None = None,
    ) -> None:
        self.atomic_engine = atomic_engine or AtomicRequirementEngine()
        self.linter = linter or SemanticLinter()

    def enrich_requirements(self, process: ProcurementProcess) -> None:
        """Decompõe e adiciona requisitos atômicos estruturados a todos os itens do processo."""
        for doc in process.documents:
            for item in doc.items:
                atomic_reqs = self.atomic_engine.extract_from_item(item, document_id=doc.id)
                for req in atomic_reqs:
                    # Adiciona se o atributo ainda não existir no item
                    if not any(r.attribute.lower() == req.attribute.lower() for r in item.requirements):
                        item.requirements.append(req)

    def run_linter(self, process: ProcurementProcess) -> list[Finding]:
        """Executa o linter semântico e retorna os achados identificados."""
        return self.linter.run(process)

    def process_procurement(self, process: ProcurementProcess) -> list[Finding]:
        """Executa tanto o enriquecimento de requisitos quanto a auditoria de linter."""
        self.enrich_requirements(process)
        findings = self.run_linter(process)
        return findings
