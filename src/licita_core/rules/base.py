"""Contrato das regras do TR Linter determinístico.

Uma regra nunca emite veredito ('aprovado'/'reprovado'); ela apenas emite ou
não emite ``Finding``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from licita_core.schema import Document, Finding, FindingCategory, ProcurementProcess, Severity


@dataclass(frozen=True)
class RuleContext:
    """Contexto de avaliação: o processo e o documento-alvo."""

    process: ProcurementProcess
    target_document_id: str
    profile_id: str = "MUNICIPAL_14133_PREGAO_ELETRONICO_BENS"
    package_files: tuple[str, ...] = ()
    package_anchors: dict[str, list[str]] = field(default_factory=dict)
    overlay_id: str | None = None

    @property
    def target_document(self) -> Document | None:
        for doc in self.process.documents:
            if doc.id == self.target_document_id:
                return doc
        return None


class Rule(ABC):
    """Interface abstrata de uma regra do linter."""

    # metadados obrigatórios
    rule_id: str
    version: str
    description: str
    scope: str
    legal_basis: str
    severity: Severity
    rule_class: str = "NORMATIVE"
    category: FindingCategory | None = None

    @abstractmethod
    def applies(self, context: RuleContext) -> bool:
        """Indica se a regra deve rodar para o documento-alvo."""

    @abstractmethod
    def detect(self, context: RuleContext) -> list[Finding]:
        """Encontra findings sobre o documento-alvo. Emite zero ou mais."""