"""RULE-002 — Item do TR sem quantidade estruturada ou sem unidade.

Opera somente nos ``FieldValue`` estruturados, conforme ``rules_draft.md``.
"""

from licita_core.rules.base import Rule, RuleContext
from licita_core.schema import (
    DocumentType,
    FieldType,
    Finding,
    FindingCategory,
    Item,
    Severity,
)


class QuantityMissingRule(Rule):
    rule_id = "RULE-002"
    version = "1.0.0"
    rule_class = "NORMATIVE"
    category = FindingCategory.STRUCTURE
    description = (
        "Item ou lote sem quantidade numérica estimada ou sem unidade de fornecimento."
    )
    scope = "Cada Item extraído do TR. Não roda se o documento-alvo não for TR."
    legal_basis = (
        "Lei nº 14.133/2021, art. 6º, XXIII, 'a', e art. 40, III "
        "(quantitativos e quantidades a adquirir)."
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
            falta = self._falta(item)
            if falta is not None:
                findings.append(self._make_finding(item, falta))
        return findings

    @staticmethod
    def _falta(item: Item) -> str | None:
        quantities = [
            field_value
            for field_value in item.field_values
            if field_value.field_type is FieldType.QUANTITY
        ]
        if not quantities:
            return "quantidade"
        if not any(field_value.unit for field_value in quantities):
            return "unidade"
        return None

    @staticmethod
    def _make_finding(item: Item, falta: str) -> Finding:
        if falta == "unidade":
            message = (
                f"Item {item.id} sem unidade de fornecimento estruturada no TR."
            )
        elif falta == "ambas":
            message = (
                f"Item {item.id} sem quantidade estimada e sem unidade "
                "estruturadas no TR."
            )
        else:
            message = f"Item {item.id} sem quantidade estimada estruturada no TR."
        return Finding(
            id=f"FIND-RULE-002-{item.id}",
            rule_id="RULE-002",
            title="Quantidade ou unidade ausente",
            message=message,
            category=FindingCategory.STRUCTURE,
            confidence=1.0,
            severity=Severity.HIGH,
            item_id=item.id,
            attrs={"falta": falta},
            evidence=list(item.evidence),
        )
