"""RULE-002 — Item do TR sem quantidade estruturada.

Objetivo: emitir um finding para cada Item do TR sem ``FieldValue`` do tipo
``QUANTITY``.

Não lê Markdown nem faz regex: opera somente nos ``FieldValue`` estruturados.
"""

from licita_core.rules.base import Rule, RuleContext
from licita_core.schema import Document, DocumentType, FieldType, Finding, Item, Severity


class QuantityMissingRule(Rule):
    rule_id = "RULE-002"
    version = "1.0.0"
    description = "Item do TR sem quantidade estruturada."
    scope = "Cada Item extraído do TR. Não roda se o documento-alvo não for TR."
    legal_basis = (
        "Lei nº 14.133/2021, art. 6º, XXIII, 'a' e art. 40, III "
        "(quantitativos e quantidades a adquirir); IN SEGES/ME nº 81/2022, art. 9º, I, 'a' e 'b'."
    )
    severity = Severity.HIGH

    def applies(self, context: RuleContext) -> bool:
        doc = context.target_document
        return doc is not None and doc.type == DocumentType.TR

    def detect(self, context: RuleContext) -> list[Finding]:
        if not self.applies(context):
            return []
        doc = context.target_document
        assert doc is not None

        findings: list[Finding] = []
        for item in doc.items:
            if not self._has_quantity(item):
                findings.append(self._make_finding(item))
        return findings

    @staticmethod
    def _has_quantity(item: Item) -> bool:
        return any(fv.field_type == FieldType.QUANTITY for fv in item.field_values)

    @staticmethod
    def _make_finding(item: Item) -> Finding:
        return Finding(
            rule_id="RULE-002",
            severity=Severity.HIGH,
            message=f"Item {item.id} sem quantidade estimada estruturada no TR.",
            item_id=item.id,
            attrs={"falta": "quantidade"},
            evidence=list(item.evidence),
        )