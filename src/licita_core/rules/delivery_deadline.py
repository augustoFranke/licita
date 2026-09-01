"""RULE-003 — Prazo determinado de entrega ou de cada fornecimento ausente.

Verifica a existência de prazo determinado de entrega ou fornecimento no TR,
conforme exigido pelo art. 6º, XXIII, 'a' e 'e', e art. 40, § 1º, II da Lei nº 14.133/2021.
"""

from __future__ import annotations

import re

from licita_core.rules.base import Rule, RuleContext
from licita_core.rules.common import (
    extract_first_evidence,
    is_placeholder,
    normalize_text,
)
from licita_core.schema import (
    Document,
    DocumentType,
    FieldType,
    Finding,
    FindingCategory,
    Severity,
)

_DELIVERY_DEADLINE_PATTERNS = [
    # Prazo numérico explícito com unidade
    r"\b(?:prazo\s+de\s+entrega|entrega(?:\s+no\s+almoxarifado|\s+dos?\s+materiais|\s+dos?\s+bens)?|entregue|fornecimento|cada\s+parcela)\b.*?\b(?:em\s+at[eé]\s+|no\s+prazo\s+de\s+|de\s+)?(\d+|um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|quinze|vinte|trinta)(?:\s*\([^\)]+\))?\s*(dias?\s+(?:[uú]teis|corridos)|horas?)\b",
    r"\b(?:em\s+at[eé]\s+|no\s+prazo\s+de\s+)(\d+|um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|quinze|vinte|trinta)(?:\s*\([^\)]+\))?\s*(dias?\s+(?:[uú]teis|corridos)|horas?)\b.*?(?:da\s+nota\s+de\s+empenho|da\s+ordem|do\s+recebimento)",
    r"\b(\d+|um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|quinze|vinte|trinta)(?:\s*\([^\)]+\))?\s*(dias?\s+(?:[uú]teis|corridos))\b.*?(?:contados\s+d|da\s+confirmação|da\s+ordem|do\s+recebimento)",
    # Cláusula explícita de entrega imediata / pronta entrega
    r"\b(?:entrega\s+imediata|pronta\s+entrega|no\s+ato\s+da\s+retirada)\b",
]


class DeliveryDeadlineRule(Rule):
    rule_id = "RULE-003"
    version = "1.0.0"
    rule_class = "NORMATIVE"
    category = FindingCategory.EXECUTION
    description = "Prazo determinado de entrega ou de cada fornecimento ausente."
    scope = (
        "Todo TR do perfil. Só prazo de entrega/fornecimento. Prazo de "
        "vigência contratual é outro campo e não substitui o prazo operacional."
    )
    legal_basis = "Lei nº 14.133/2021, art. 6º, XXIII, 'a' e 'e', e art. 40, § 1º, II."
    severity = Severity.HIGH

    def applies(self, context: RuleContext) -> bool:
        doc = context.target_document
        return (
            doc is not None
            and doc.type == DocumentType.TR
            and context.profile_id == "PUBLICO_14133_PREGAO_ELETRONICO_BENS"
        )

    def detect(self, context: RuleContext) -> list[Finding]:
        if not self.applies(context):
            return []
        doc = context.target_document
        assert doc is not None

        if self._has_delivery_deadline(doc):
            return []

        evidence = extract_first_evidence(doc)
        return [
            Finding(
                id=f"FIND-RULE-003-{doc.id}",
                rule_id=self.rule_id,
                title="Prazo de entrega ausente",
                message="Prazo determinado de entrega ou de cada fornecimento ausente no TR.",
                category=self.category,
                confidence=1.0,
                severity=self.severity,
                attrs={"profile_id": context.profile_id},
                evidence=[evidence],
            )
        ]

    @classmethod
    def _has_delivery_deadline(cls, doc: Document) -> bool:
        # 1. FieldValue estruturado
        for fv in doc.field_values:
            if fv.field_type == FieldType.DELIVERY_DEADLINE:
                if not is_placeholder(str(fv.value)):
                    return True
        for item in doc.items:
            for fv in item.field_values:
                if fv.field_type == FieldType.DELIVERY_DEADLINE:
                    if not is_placeholder(str(fv.value)):
                        return True

        # 2. Busca nos blocos de texto
        for section in doc.sections:
            for block in section.blocks:
                if is_placeholder(block.text):
                    continue
                text = block.text.lower()
                for pat in _DELIVERY_DEADLINE_PATTERNS:
                    if re.search(pat, text, re.IGNORECASE):
                        return True

        return False
