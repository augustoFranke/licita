"""RULE-004 — Mesma garantia técnica citada de forma contraditória no TR.

Verifica a consistência de prazos e condições da mesma garantia técnica para o
mesmo bem e sujeito obrigado, conforme o art. 40, § 1º, III da Lei nº 14.133/2021.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

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
    FieldType,
    Finding,
    FindingCategory,
    Severity,
)


@dataclass(frozen=True)
class _WarrantyMention:
    item_id: str
    guarantor: str
    warranty_type: str
    duration_months: int
    quote: str
    evidence: Evidence

    @property
    def key(self) -> str:
        return f"{self.item_id}/{self.guarantor}/{self.warranty_type}"


class WarrantyContradictionRule(Rule):
    rule_id = "RULE-004"
    version = "1.0.0"
    rule_class = "NORMATIVE"
    category = FindingCategory.CONSISTENCY
    description = (
        "Prazo ou condição da mesma garantia técnica, para o mesmo bem e "
        "sujeito obrigado, citado de forma contraditória no TR."
    )
    scope = (
        "Só contradição interna. Não torna garantia obrigatória quando ela não "
        "for aplicável. Menção única, ausência de garantia ou declaração "
        "justificada de não aplicabilidade não dispara."
    )
    legal_basis = "Lei nº 14.133/2021, art. 40, § 1º, III."
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

        # Verifica se garantia não é aplicável
        if self._is_warranty_not_applicable(doc):
            return []

        mentions = self._extract_warranty_mentions(doc)
        if len(mentions) < 2:
            return []

        # Agrupa menções pela chave (item/sujeito/tipo)
        by_key: dict[str, list[_WarrantyMention]] = {}
        for m in mentions:
            by_key.setdefault(m.key, []).append(m)

        findings: list[Finding] = []
        for key, group in by_key.items():
            if len(group) < 2:
                continue
            first = group[0]
            for other in group[1:]:
                if first.duration_months != other.duration_months:
                    findings.append(
                        Finding(
                            id=f"FIND-RULE-004-{doc.id}",
                            rule_id=self.rule_id,
                            title="Garantia técnica contraditória",
                            message=(
                                f"Garantia técnica ({key}) citada com prazos "
                                f"incompatíveis: {first.duration_months} meses vs "
                                f"{other.duration_months} meses."
                            ),
                            category=self.category,
                            confidence=1.0,
                            severity=self.severity,
                            attrs={
                                "guarantee_key": key,
                                "left": first.quote,
                                "right": other.quote,
                                "profile_id": context.profile_id,
                            },
                            evidence=[first.evidence, other.evidence],
                        )
                    )
                    break

        return findings

    @staticmethod
    def _is_warranty_not_applicable(doc: Document) -> bool:
        not_applicable_phrases = [
            "nao se exige garantia",
            "nao se aplica garantia",
            "garantia nao exigida",
            "nao ha exigencia de garantia",
        ]
        for section in doc.sections:
            for block in section.blocks:
                norm = normalize_text(block.text)
                if any(phrase in norm for phrase in not_applicable_phrases):
                    return True
        return False

    @staticmethod
    def _extract_warranty_mentions(doc: Document) -> list[_WarrantyMention]:
        mentions: list[_WarrantyMention] = []
        default_item_id = doc.items[0].id if doc.items else "item-1"

        # 1. FieldValues estruturados
        for fv in doc.field_values:
            if fv.field_type == FieldType.WARRANTY_TERM:
                months = WarrantyContradictionRule._to_months(fv.value, fv.unit)
                if months is not None:
                    item_id = fv.item_id or default_item_id
                    ev = fv.evidence[0] if fv.evidence else extract_first_evidence(doc)
                    mentions.append(
                        _WarrantyMention(
                            item_id=item_id,
                            guarantor="contratada",
                            warranty_type="garantia-tecnica-integral",
                            duration_months=months,
                            quote=ev.quote,
                            evidence=ev,
                        )
                    )

        # 2. Textos dos blocos
        # Regex para capturar menções de garantia no texto
        pat = re.compile(
            r"(?:garantia\s+t[eé]cnica(?:\s+integral|\s+on-site)?|garantia)"
            r"(?:(?:\s+do\s+item\s+(\d+|[a-zA-Z0-9_-]+))|(?:\s+pela\s+contratada|\s+prestada\s+pela\s+contratada))*"
            r".*?(?:m[ií]nima\s+de\s+|ser[aá]\s+de\s+|:\s*|de\s+)?(\d+)\s*(meses|m[eê]s|anos|ano)\b",
            re.IGNORECASE,
        )

        for section in doc.sections:
            for block in section.blocks:
                if is_placeholder(block.text):
                    continue
                for match in pat.finditer(block.text):
                    num = int(match.group(2))
                    unit = match.group(3).lower()
                    months = num * 12 if "ano" in unit else num

                    item_match = re.search(r"item\s+(\d+|[a-zA-Z0-9_-]+)", block.text, re.IGNORECASE)
                    item_id = f"item-{item_match.group(1)}" if item_match else default_item_id
                    if item_id.startswith("item-item-"):
                        item_id = item_id[5:]

                    guarantor = "contratada"
                    w_type = "garantia-tecnica-integral"

                    ev = Evidence(
                        document_id=doc.id,
                        page=section.evidence.page if section.evidence else 1,
                        block_id=block.id,
                        quote=block.text,
                    )
                    mentions.append(
                        _WarrantyMention(
                            item_id=item_id,
                            guarantor=guarantor,
                            warranty_type=w_type,
                            duration_months=months,
                            quote=block.text,
                            evidence=ev,
                        )
                    )

        return mentions

    @staticmethod
    def _to_months(value: object, unit: str | None) -> int | None:
        try:
            num = int(float(str(value)))
        except (ValueError, TypeError):
            return None
        unit_norm = (unit or "").lower()
        if "ano" in unit_norm:
            return num * 12
        return num
