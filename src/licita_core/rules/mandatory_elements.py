"""RULE-001 — Elemento obrigatório ausente no TR.

Verifica a presença dos 10 elementos do art. 6º, XXIII e dos conteúdos
aplicáveis do art. 40, § 1º da Lei nº 14.133/2021 no perfil de compras
municipais de bens comuns.
"""

from __future__ import annotations

import re
from typing import Sequence

from licita_core.rules.base import Rule, RuleContext
from licita_core.rules.common import (
    extract_first_evidence,
    is_placeholder,
    normalize_text,
)
from licita_core.schema import (
    BlockType,
    Document,
    DocumentType,
    FieldType,
    Finding,
    FindingCategory,
    Section,
    Severity,
)

_ELEMENT_CANONICAL_ORDER = [
    "objeto",
    "fundamentacao",
    "solucao",
    "requisitos",
    "execucao",
    "gestao",
    "medicao_pagamento",
    "selecao",
    "estimativa",
    "adequacao_orcamentaria",
    "local_entrega",
    "recebimento",
]

_TITLE_ALIASES: dict[str, list[str]] = {
    "objeto": [
        "definicao do objeto",
        "do objeto",
        "objeto",
        "descricao do objeto",
    ],
    "fundamentacao": [
        "fundamentacao da contratacao",
        "fundamentacao",
        "justificativa",
        "da justificativa",
        "da fundamentacao",
    ],
    "solucao": [
        "descricao da solucao como um todo",
        "da solucao",
        "solucao como um todo",
        "solucao",
        "descricao da solucao",
    ],
    "requisitos": [
        "requisitos da contratacao",
        "requisitos",
        "dos requisitos",
        "especificacoes da contratacao",
        "especificacao da contratacao",
        "especificacoes tecnicas",
        "especificacao tecnica",
        "especificacao do objeto",
        "especificacao",
    ],
    "execucao": [
        "modelo de execucao do objeto",
        "da execucao",
        "execucao do objeto",
        "execucao",
        "modelo de execucao",
        "execucao e fiscalizacao",
    ],
    "gestao": [
        "modelo de gestao do contrato",
        "da gestao",
        "gestao do contrato",
        "gestao",
        "fiscalizacao",
        "fiscalizacao do contrato",
        "modelo de gestao",
        "da gestao do contrato",
        "gestao e fiscalizacao",
    ],
    "medicao_pagamento": [
        "criterios de medicao e de pagamento",
        "criterios de medicao e pagamento",
        "medicao e pagamento",
        "do pagamento",
        "pagamento",
        "criterios de medicao",
        "criterios de pagamento",
    ],
    "selecao": [
        "forma e criterios de selecao do fornecedor",
        "forma e criterio de selecao do fornecedor",
        "selecao do fornecedor",
        "criterio de julgamento",
        "criterios de selecao",
        "da selecao",
        "selecao",
        "da selecao do fornecedor",
    ],
    "estimativa": [
        "estimativas do valor da contratacao",
        "estimativa do valor da contratacao",
        "estimativas do valor",
        "estimativa do valor",
        "valor da contratacao",
        "estimativa de precos",
        "estimativa de preco",
        "da estimativa de precos",
        "do valor estimado",
        "valor estimado",
        "do valor",
    ],
    "adequacao_orcamentaria": [
        "adequacao orcamentaria",
        "da dotacao",
        "dotacao orcamentaria",
        "dotacao",
        "recursos orcamentarios",
        "da adequacao orcamentaria",
        "recurso orcamentario",
        "da dotacao orcamentaria",
    ],
}


def _clean_section_title(title: str) -> str:
    norm = normalize_text(title)
    # Remove prefixos numéricos e rotulagens como '1.', '1.1.', 'capitulo i', 'secao 4', 'item 1 -'
    norm = re.sub(
        r"^(?:(?:item|secao|capitulo)\s+[\divxlcdm]+(?:\.[\divxlcdm]+)*|\d+(?:\.\d+)*)\s*[-–—:.]*\s*",
        "",
        norm,
    )
    return norm.strip()


def _section_has_valid_content(section: Section) -> bool:
    """Verifica se a seção possui blocos de corpo com conteúdo real (não placeholder)."""
    body_blocks = [b for b in section.blocks if b.type != BlockType.HEADER]
    if not body_blocks:
        # Se só tiver cabeçalho, verifica se o cabeçalho em si é a seção
        return False
    return any(not is_placeholder(block.text) for block in body_blocks)


class MandatoryElementsRule(Rule):
    rule_id = "RULE-001"
    version = "1.0.0"
    rule_class = "NORMATIVE"
    category = FindingCategory.STRUCTURE
    description = "Elemento descritivo exigido ausente ou sem conteúdo no TR."
    scope = (
        "Todo TR classificado SUPPORTED neste perfil. Avalia presença "
        "determinística, não qualidade argumentativa nem numeração de modelo."
    )
    legal_basis = (
        "Lei nº 14.133/2021, art. 6º, XXIII, alíneas 'a' a 'j', "
        "e art. 40, § 1º, incisos I a III."
    )
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

        present_elements: set[str] = set()

        # Mapeia seções válidas pelos títulos e tipos
        for section in doc.sections:
            if not _section_has_valid_content(section):
                continue
            clean_title = _clean_section_title(section.title_original)
            sec_type = (section.section_type_normalized or "").upper()

            for elem_id, aliases in _TITLE_ALIASES.items():
                if elem_id in present_elements:
                    continue
                if any(clean_title == alias or clean_title.startswith(alias) for alias in aliases):
                    present_elements.add(elem_id)
                elif sec_type and sec_type == elem_id.upper():
                    present_elements.add(elem_id)

        # Checagens complementares
        if "objeto" not in present_elements:
            if any(item.description and not is_placeholder(item.description) for item in doc.items):
                present_elements.add("objeto")

        if "requisitos" not in present_elements:
            if doc.requirements or any(item.requirements for item in doc.items):
                present_elements.add("requisitos")

        if "estimativa" not in present_elements:
            has_prices = any(
                fv.field_type in (FieldType.UNIT_PRICE, FieldType.TOTAL_PRICE)
                for fv in doc.field_values + [fv for it in doc.items for fv in it.field_values]
            )
            if has_prices:
                present_elements.add("estimativa")

        # Checagem de local_entrega (art. 40, § 1º, II)
        if self._has_local_entrega(doc):
            present_elements.add("local_entrega")

        # Checagem de recebimento (art. 40, § 1º, II)
        if self._has_recebimento(doc):
            present_elements.add("recebimento")

        # Determina elementos faltantes na ordem canônica
        missing = [
            elem_id
            for elem_id in _ELEMENT_CANONICAL_ORDER
            if elem_id not in present_elements
        ]

        if not missing:
            return []

        attrs: dict[str, object] = {
            "missing": missing,
            "profile_id": context.profile_id,
        }
        if context.overlay_id is not None:
            attrs["overlay_id"] = context.overlay_id

        evidence = extract_first_evidence(doc)
        return [
            Finding(
                id=f"FIND-RULE-001-{doc.id}",
                rule_id=self.rule_id,
                title="Elemento obrigatório ausente no TR",
                message=(
                    f"Elemento(s) descritivo(s) obrigatório(s) ausente(s) no TR: "
                    f"{', '.join(missing)}."
                ),
                category=self.category,
                confidence=1.0,
                severity=self.severity,
                attrs=attrs,
                evidence=[evidence],
            )
        ]

    @staticmethod
    def _has_local_entrega(doc: Document) -> bool:
        # FieldValue explícito
        for fv in doc.field_values:
            if fv.field_type == FieldType.DELIVERY_LOCATION:
                if not is_placeholder(str(fv.value)):
                    return True
        for item in doc.items:
            for fv in item.field_values:
                if fv.field_type == FieldType.DELIVERY_LOCATION:
                    if not is_placeholder(str(fv.value)):
                        return True

        # Seções de execução, objeto ou local de entrega com conteúdo não-placeholder
        local_keywords = [
            "local:",
            "local de entrega",
            "locais de entrega",
            "almoxarifado",
            "sede do municipio",
            "enderecos das escolas",
            "endereco",
            "entrega no",
            "entrega em",
            "entregara os materiais no",
            "entregara no",
        ]
        for section in doc.sections:
            if not _section_has_valid_content(section):
                continue
            clean_title = _clean_section_title(section.title_original)
            is_candidate_sec = (
                clean_title in _TITLE_ALIASES["execucao"]
                or clean_title in _TITLE_ALIASES["objeto"]
                or "local" in clean_title
                or "entrega" in clean_title
            )
            if is_candidate_sec:
                for block in section.blocks:
                    if is_placeholder(block.text):
                        continue
                    norm_text = normalize_text(block.text)
                    if any(kw in norm_text for kw in local_keywords):
                        return True
        return False

    @staticmethod
    def _has_recebimento(doc: Document) -> bool:
        # FieldValue explícito
        for fv in doc.field_values:
            if fv.field_type == FieldType.RECEIPT_DEADLINE:
                return True
        for item in doc.items:
            for fv in item.field_values:
                if fv.field_type == FieldType.RECEIPT_DEADLINE:
                    return True

        recebimento_keywords = [
            "recebimento",
            "provisorio",
            "definitivo",
            "recebidos provisoriamente",
            "recebimento provisorio",
            "recebimento definitivo",
            "recebimentos provisorio e definitivo",
            "nao se aplica etapa provisoria",
        ]
        for section in doc.sections:
            if not _section_has_valid_content(section):
                continue
            clean_title = _clean_section_title(section.title_original)
            is_candidate_sec = (
                clean_title in _TITLE_ALIASES["medicao_pagamento"]
                or clean_title in _TITLE_ALIASES["gestao"]
                or clean_title in _TITLE_ALIASES["execucao"]
                or "recebimento" in clean_title
                or "pagamento" in clean_title
            )
            if is_candidate_sec:
                for block in section.blocks:
                    if is_placeholder(block.text):
                        continue
                    norm_text = normalize_text(block.text)
                    if any(kw in norm_text for kw in recebimento_keywords):
                        return True
        return False
