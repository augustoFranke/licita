"""RULE-005 — Regras aplicáveis de recebimento dos bens ausentes ou insuficientemente definidas.

Verifica a definição suficiente das regras de recebimento provisório e definitivo
(ou simultâneo fundamentado / não aplicabilidade justificada), conforme o
art. 140, II, 'a' e 'b', e art. 40, § 1º, II da Lei nº 14.133/2021.
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


class ReceiptRulesRule(Rule):
    rule_id = "RULE-005"
    version = "1.0.0"
    rule_class = "NORMATIVE"
    category = FindingCategory.EXECUTION
    description = (
        "Regras aplicáveis de recebimento dos bens ausentes ou "
        "insuficientemente definidas."
    )
    scope = (
        "Todo TR do perfil. Aceita rito provisório/definitivo, recebimento "
        "simultâneo explicitamente definido ou declaração fundamentada de não "
        "aplicabilidade de uma etapa. Mera citação da Lei não basta."
    )
    legal_basis = "Lei nº 14.133/2021, art. 140, II, 'a' e 'b', e art. 40, § 1º, II."
    severity = Severity.HIGH

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

        all_text = " ".join(
            block.text for section in doc.sections for block in section.blocks
        )
        norm_text = normalize_text(all_text)

        # 1. Verifica se atende a algum dos 3 modos válidos
        if self._check_simultaneo_ok(all_text, norm_text):
            return []
        if self._check_nao_aplicavel_ok(all_text, norm_text):
            return []
        if self._check_normal_ok(all_text, norm_text):
            return []

        # 2. Diagnostica a falha
        mode, falta = self._diagnose_failure(all_text, norm_text)

        evidence = extract_first_evidence(doc)
        return [
            Finding(
                id=f"FIND-RULE-005-{doc.id}",
                rule_id=self.rule_id,
                title="Recebimento insuficientemente definido",
                message=(
                    "Regras aplicáveis de recebimento dos bens ausentes ou "
                    f"insuficientemente definidas no TR (modo: {mode}, falta: {', '.join(falta)})."
                ),
                category=self.category,
                confidence=1.0,
                severity=self.severity,
                attrs={
                    "mode": mode,
                    "falta": falta,
                    "profile_id": context.profile_id,
                },
                evidence=[evidence],
            )
        ]

    @staticmethod
    def _check_simultaneo_ok(raw_text: str, norm_text: str) -> bool:
        if not any(kw in norm_text for kw in ["simultaneamente", "no mesmo ato", "ocorrerao simultaneamente"]):
            return False
        has_responsible = any(kw in norm_text for kw in ["servidor", "fiscal", "comissao"])
        has_verification = any(kw in norm_text for kw in ["conferencia", "verificacao", "especificac", "conformidade"])
        has_term = any(kw in norm_text for kw in ["termo detalhado", "termo", "registro", "aceite"])
        has_no_placeholder = not re.search(r"<\s*respons[aá]vel\s*>|\[.*?indicar.*?\]|XXXX", raw_text, re.IGNORECASE)
        return has_responsible and has_verification and has_term and has_no_placeholder

    @staticmethod
    def _check_nao_aplicavel_ok(raw_text: str, norm_text: str) -> bool:
        if not any(kw in norm_text for kw in ["nao se aplica etapa provisoria", "nao se aplica recebimento provisorio"]):
            return False
        has_justification = any(kw in norm_text for kw in ["em razao", "considerad", "balcao de retirada", "caracteristicas"])
        has_definitivo = any(kw in norm_text for kw in ["definitivo", "mesmo ato", "aceite aplicavel"])
        has_responsible = any(kw in norm_text for kw in ["servidor", "fiscal", "comissao"])
        has_verification = any(kw in norm_text for kw in ["conferencia", "verificacao", "especificac"])
        has_term = any(kw in norm_text for kw in ["termo detalhado", "termo", "registro"])
        has_no_placeholder = not re.search(r"<\s*respons[aá]vel\s*>|\[.*?indicar.*?\]|XXXX", raw_text, re.IGNORECASE)
        return has_justification and has_definitivo and has_responsible and has_verification and has_term and has_no_placeholder

    @staticmethod
    def _check_normal_ok(raw_text: str, norm_text: str) -> bool:
        # Provisório
        has_provisorio = "provisorio" in norm_text or "provisoriamente" in norm_text
        provisorio_ok = has_provisorio and any(
            kw in norm_text for kw in ["sumaria", "no ato da entrega", "entrega", "fiscal", "servidor"]
        ) and not re.search(r"provisoriamente\s+por\s+<\s*respons[aá]vel\s*>", raw_text, re.IGNORECASE)

        # Definitivo
        has_definitivo = "definitivo" in norm_text or "definitivamente" in norm_text
        definitivo_ok = has_definitivo and any(
            kw in norm_text for kw in ["servidor", "comissao", "equipe", "designad"]
        ) and any(
            kw in norm_text for kw in ["termo detalhado", "ateste", "verificacao de conformidade", "conferencia", "dias uteis", "dias corridos"]
        ) and not re.search(r"XXXX\s+dias|\[\s*servidor/comiss[aã]o\s+a\s+indicar\s*\]", raw_text, re.IGNORECASE)

        return provisorio_ok and definitivo_ok

    @staticmethod
    def _diagnose_failure(raw_text: str, norm_text: str) -> tuple[str, list[str]]:
        # Checa se há placeholders em template
        has_ph_resp_prov = bool(re.search(r"provisoriamente\s+por\s+<\s*respons[aá]vel\s*>", raw_text, re.IGNORECASE))
        has_ph_prazo_def = bool(re.search(r"XXXX\s+dias", raw_text, re.IGNORECASE))
        has_ph_resp_def = bool(re.search(r"\[\s*servidor/comiss[aã]o\s+a\s+indicar\s*\]", raw_text, re.IGNORECASE))

        if has_ph_resp_prov or has_ph_prazo_def or has_ph_resp_def:
            falta = []
            if has_ph_resp_prov:
                falta.append("responsavel_provisorio")
            if has_ph_prazo_def:
                falta.append("prazo_definitivo")
            if has_ph_resp_def:
                falta.append("responsavel_definitivo")
            return "normal", falta

        # Checa citação pura do art. 140
        if re.search(r"art(?:igo|\.)?\s*140", raw_text, re.IGNORECASE) and not ("provisorio" in norm_text or "definitivo" in norm_text):
            return "indefinido", ["provisorio", "definitivo"]

        # Checa presença parcial
        has_provisorio = "provisorio" in norm_text or "provisoriamente" in norm_text
        has_definitivo = "definitivo" in norm_text or "definitivamente" in norm_text

        if has_provisorio and not has_definitivo:
            return "normal", ["definitivo"]
        if has_definitivo and not has_provisorio:
            return "normal", ["provisorio"]

        return "indefinido", ["provisorio", "definitivo"]
