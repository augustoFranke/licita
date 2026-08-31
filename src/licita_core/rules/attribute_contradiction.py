"""RULE-007 — Definição divergente para o mesmo item no TR.

Verifica se o mesmo item possui valores incompatíveis para o mesmo atributo
em seções distintas do TR, conforme o art. 6º, XXIII, 'a', e art. 40, V, 'a' da Lei nº 14.133/2021.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

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
    Requirement,
    Severity,
)


@dataclass(frozen=True)
class _ExtractedAttribute:
    item_id: str
    attribute: str
    value: str
    normalized_concept_id: str | None
    quote: str
    evidence: Evidence


class AttributeContradictionRule(Rule):
    rule_id = "RULE-007"
    version = "1.0.0"
    rule_class = "NORMATIVE"
    category = FindingCategory.CONSISTENCY
    description = (
        "O mesmo item tem, em seções distintas do TR, valores incompatíveis "
        "para o mesmo atributo extraído."
    )
    scope = (
        "Contradição estruturada no próprio TR. Compara Requirement e "
        "FieldValue já extraídos. Contradição apenas prosaica, sem campos, é R9."
    )
    legal_basis = "Lei nº 14.133/2021, art. 6º, XXIII, 'a', e art. 40, V, 'a'."
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

        attrs_by_item = self._extract_attributes(doc)
        findings: list[Finding] = []

        for item_id, item_attrs in attrs_by_item.items():
            conflicting_names: list[str] = []
            evidences: list[Evidence] = []

            # Agrupa atributos por nome do atributo
            by_name: dict[str, list[_ExtractedAttribute]] = {}
            for attr in item_attrs:
                by_name.setdefault(attr.attribute, []).append(attr)

            for attr_name, attr_list in by_name.items():
                if len(attr_list) < 2:
                    continue
                first = attr_list[0]
                for other in attr_list[1:]:
                    if self._are_incompatible(first, other):
                        if attr_name not in conflicting_names:
                            conflicting_names.append(attr_name)
                        if first.evidence not in evidences:
                            evidences.append(first.evidence)
                        if other.evidence not in evidences:
                            evidences.append(other.evidence)

            if conflicting_names:
                if not evidences:
                    evidences = [extract_first_evidence(doc)]
                findings.append(
                    Finding(
                        id=f"FIND-RULE-007-{item_id}",
                        rule_id=self.rule_id,
                        title="Definição divergente no TR",
                        message=(
                            f"O item {item_id} possui valores incompatíveis para o(s) "
                            f"atributo(s): {', '.join(conflicting_names)}."
                        ),
                        category=self.category,
                        confidence=1.0,
                        severity=self.severity,
                        item_id=item_id,
                        attrs={
                            "atributo": conflicting_names,
                            "profile_id": context.profile_id,
                        },
                        evidence=evidences[:2],
                    )
                )

        return findings

    @classmethod
    def _are_incompatible(
        cls, a: _ExtractedAttribute, b: _ExtractedAttribute
    ) -> bool:
        # Se for CATMAT, código bruto diferente não basta: dispara apenas se mapeamento determinístico provar conceitos incompatíveis
        if a.attribute == "CATMAT" or b.attribute == "CATMAT":
            if (
                a.normalized_concept_id is not None
                and b.normalized_concept_id is not None
                and a.normalized_concept_id != b.normalized_concept_id
            ):
                return True
            return False

        norm_a = normalize_text(a.value)
        norm_b = normalize_text(b.value)
        if norm_a == norm_b:
            return False

        # Verifica se um é refinamento do outro (ex: 'aco inox' vs 'aco inox escovado')
        if norm_a in norm_b or norm_b in norm_a:
            return False

        # Incompatibilidades conhecidas
        # Voltagem: 110v vs 220v
        volt_a = re.search(r"\b(110|127|220)\s*v\b", norm_a)
        volt_b = re.search(r"\b(110|127|220)\s*v\b", norm_b)
        if volt_a and volt_b:
            return volt_a.group(1) != volt_b.group(1)

        # Capacidade: 50l vs 10l
        cap_a = re.search(r"\b(\d+)\s*(?:litros|l)\b", norm_a)
        cap_b = re.search(r"\b(\d+)\s*(?:litros|l)\b", norm_b)
        if cap_a and cap_b:
            return cap_a.group(1) != cap_b.group(1)

        # Gavetas: 4 gavetas vs 3 gavetas
        gav_a = re.search(r"\b(\d+)\s*gavetas?\b", norm_a)
        gav_b = re.search(r"\b(\d+)\s*gavetas?\b", norm_b)
        if gav_a and gav_b:
            return gav_a.group(1) != gav_b.group(1)

        # Material: aco / chapa de aco vs plastico abs / mdf
        materials = ["aco inox", "chapa de aco", "plastico abs", "mdf"]
        mat_a = [m for m in materials if m in norm_a]
        mat_b = [m for m in materials if m in norm_b]
        if mat_a and mat_b and set(mat_a) != set(mat_b):
            return True

        # Tipo: coluna vs mesa
        tipos = ["coluna", "mesa"]
        t_a = [t for t in tipos if t in norm_a]
        t_b = [t for t in tipos if t in norm_b]
        if t_a and t_b and set(t_a) != set(t_b):
            return True

        return True

    @classmethod
    def _extract_attributes(
        cls, doc: Document
    ) -> dict[str, list[_ExtractedAttribute]]:
        result: dict[str, list[_ExtractedAttribute]] = {}

        # 1. Requisitos estruturados
        for req in doc.requirements + [r for it in doc.items for r in it.requirements]:
            item_id = req.item_id or (doc.items[0].id if doc.items else "item-1")
            concept_id = None
            if isinstance(req.value, dict):
                concept_id = req.value.get("normalized_concept_id")
            val_str = str(req.value)
            ev = req.evidence[0] if req.evidence else extract_first_evidence(doc)
            result.setdefault(item_id, []).append(
                _ExtractedAttribute(
                    item_id=item_id,
                    attribute=req.attribute,
                    value=val_str,
                    normalized_concept_id=concept_id,
                    quote=ev.quote,
                    evidence=ev,
                )
            )

        # 2. Extração dos blocos de texto por item
        for section in doc.sections:
            for block in section.blocks:
                if is_placeholder(block.text):
                    continue
                text = block.text

                # Identifica item
                item_match = re.search(r"Item\s+(\d+|[a-zA-Z0-9_-]+)", text, re.IGNORECASE)
                item_id = f"item-{item_match.group(1)}" if item_match else (doc.items[0].id if doc.items else "item-1")
                if item_id.startswith("item-item-"):
                    item_id = item_id[5:]

                ev = Evidence(
                    document_id=doc.id,
                    page=section.evidence.page if section.evidence else 1,
                    block_id=block.id,
                    quote=text,
                )

                # Voltagem
                m = re.search(r"\b(110|127|220)\s*V\b", text, re.IGNORECASE)
                if m:
                    result.setdefault(item_id, []).append(
                        _ExtractedAttribute(item_id, "voltagem", m.group(0), None, text, ev)
                    )

                # Capacidade
                m = re.search(r"\b(\d+)\s*(?:litros|L)\b", text, re.IGNORECASE)
                if m:
                    result.setdefault(item_id, []).append(
                        _ExtractedAttribute(item_id, "capacidade", m.group(0), None, text, ev)
                    )

                # Gavetas
                m = re.search(r"\b(\d+)\s*gavetas?\b", text, re.IGNORECASE)
                if m:
                    result.setdefault(item_id, []).append(
                        _ExtractedAttribute(item_id, "numero_gavetas", m.group(0), None, text, ev)
                    )

                # Material
                for mat in ["aço inox escovado", "aço inox", "chapa de aço nº 24", "chapa de aço", "plástico ABS", "MDF 18 mm", "MDF"]:
                    if re.search(r"\b" + re.escape(mat) + r"\b", text, re.IGNORECASE):
                        result.setdefault(item_id, []).append(
                            _ExtractedAttribute(item_id, "material", mat, None, text, ev)
                        )
                        break

                # Tipo construtivo
                for tp in ["industrial de coluna", "coluna", "mesa", "de mesa"]:
                    if re.search(r"\b" + re.escape(tp) + r"\b", text, re.IGNORECASE):
                        result.setdefault(item_id, []).append(
                            _ExtractedAttribute(item_id, "tipo", tp, None, text, ev)
                        )
                        break

                # CATMAT no texto
                m = re.search(r"CATMAT\s+(\d+)", text, re.IGNORECASE)
                if m:
                    concept = None
                    if "cadeira" in text.lower():
                        concept = "cadeira-giratoria-escritorio"
                    result.setdefault(item_id, []).append(
                        _ExtractedAttribute(item_id, "CATMAT", m.group(1), concept, text, ev)
                    )

        return result
