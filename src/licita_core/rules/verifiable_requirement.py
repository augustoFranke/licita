"""ADVISORY-008 — Requisito técnico objetivamente aferível sem método de comprovação.

Controle de qualidade editorial (ADVISORY / QUALITY).
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
    Evidence,
    Finding,
    FindingCategory,
    Severity,
)

_VERIFIABLE_METRIC_PATTERNS = [
    # Joules (impacto)
    r"\b\d+\s*(?:Joules?|J)\b",
    # Resistência a escorregamento
    r"\b(?:SRC|SRA|SRB)\b",
    # Proteção solar UV / UPF
    r"\b(?:UV|UPF)\s*(?:fator\s*)?(?:50\+|\d+\+?)\b",
    r"\bprote[cç][aã]o\s+solar\s+UV\b",
    # Inflamabilidade / Retardante a chamas
    r"\bretardante\s+a\s+chamas\s+classe\s+[A-E]\b",
    r"\binflamabilidade\s+classe\s+[A-E]\b",
    # Grau de proteção IP
    r"\bIP\d{2}\b",
]

_VERIFICATION_METHOD_KEYWORDS = [
    "laudo",
    "laudo de ensaio",
    "certificado",
    "certificado valido",
    "laboratorio acreditado",
    "ensaio",
    "amostra",
    "prova de conceito",
    "comprovacao",
    "comprovado mediante",
    "apresentacao de certificado",
    "acreditado",
]


class VerifiableRequirementRule(Rule):
    rule_id = "ADVISORY-008"
    version = "1.0.0"
    rule_class = "ADVISORY"
    category = FindingCategory.COMPLIANCE
    description = (
        "Requisito técnico objetivamente aferível sem critério, documento ou "
        "método de comprovação explicitado."
    )
    scope = (
        "Controle opcional de qualidade editorial, fora da R8 normativa. Só "
        "requisito objetivamente verificável usado como filtro de proposta, "
        "habilitação ou recebimento. Especificação ordinária do bem não entra; "
        "expressão vaga pertence à R9."
    )
    legal_basis = (
        "não se aplica — não é teste automático de compliance municipal."
    )
    severity = Severity.MEDIUM

    def applies(self, context: RuleContext) -> bool:
        doc = context.target_document
        return (
            doc is not None
            and doc.type == DocumentType.TR
            and context.profile_id == "MUNICIPAL_14133_PREGAO_ELETRONICO_BENS"
        )

    def detect(self, context: RuleContext) -> list[Finding]:
        if not self.applies(context):
            return []
        doc = context.target_document
        assert doc is not None

        findings: list[Finding] = []

        for section in doc.sections:
            for block in section.blocks:
                if is_placeholder(block.text):
                    continue

                text = block.text
                has_verifiable = any(
                    re.search(pat, text, re.IGNORECASE)
                    for pat in _VERIFIABLE_METRIC_PATTERNS
                )

                if has_verifiable:
                    norm_text = normalize_text(text)
                    has_method = any(
                        kw in norm_text for kw in _VERIFICATION_METHOD_KEYWORDS
                    )
                    if not has_method:
                        ev = Evidence(
                            document_id=doc.id,
                            page=section.evidence.page if section.evidence else 1,
                            block_id=block.id,
                            quote=text,
                        )
                        findings.append(
                            Finding(
                                id=f"FIND-ADVISORY-008-{doc.id}",
                                rule_id=self.rule_id,
                                title="Requisito aferível sem método de comprovação",
                                message=(
                                    "Requisito técnico objetivamente aferível sem "
                                    "critério, documento ou método de comprovação explicitado."
                                ),
                                category=self.category,
                                confidence=1.0,
                                severity=self.severity,
                                attrs={
                                    "rule_class": "ADVISORY",
                                    "category": "QUALITY",
                                    "profile_id": context.profile_id,
                                },
                                evidence=[ev],
                            )
                        )
                        break

        return findings
