"""Extrator de campos transversais (prazos, garantias, orçamento) e itens em prosa (R5)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Sequence

from licita_core.schema import (
    BlockType,
    Evidence,
    FieldType,
    FieldValue,
    Item,
    Requirement,
    RequirementOperator,
    ReviewStatus,
)
from licita_ingest.extractor import StructuredDocument, StructuredBlock


def _clean_text(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _parse_quantidade(texto: str) -> Decimal | None:
    if not texto:
        return None
    limpo = re.sub(r"[^\d,\.]", "", texto).strip()
    if not limpo:
        return None
    if re.match(r"^\d{1,3}(?:\.\d{3})+$", limpo):
        limpo = limpo.replace(".", "")
    elif "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        val = Decimal(limpo)
        if val > 0:
            return val
    except Exception:
        return None
    return None


def _parse_moeda(texto: str) -> Decimal | None:
    if not texto:
        return None
    limpo = re.sub(r"[^\d,\.]", "", texto).strip()
    if not limpo:
        return None
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        val = Decimal(limpo)
        if val >= 0:
            return val
    except Exception:
        return None
    return None


def extract_document_fields(doc_ext: ExtractedDocument, document_id: str) -> list[FieldValue]:
    """Extrai campos transversais de nível documental (prazo de entrega, garantia, orçamento)."""
    fields: list[FieldValue] = []

    for block in doc_ext.iter_blocks(include_children=True):
        if block.type.value in ("TABLE", "IMAGE") or not (block.text or "").strip():
            continue
        text = _clean_text(block.text)

        # 1. Prazo de Entrega
        match_deadline = re.search(
            r"\b(?:prazo\s+de\s+entrega|entrega\s+em|prazo\s+de\s+fornecimento|em\s+at[eé]|no\s+prazo\s+de)\s*(\d+)\s*(?:dias?\s*(?:[uú]teis|corridos)?|horas?)\b",
            text,
            re.IGNORECASE,
        )
        if match_deadline and "vigência" not in text.lower():
            qtd_dias = int(match_deadline.group(1))
            ev = Evidence(
                document_id=document_id,
                page=block.page if block.page is not None and block.page >= 1 else 1,
                block_id=block.id,
                quote=block.text,
            )
            fields.append(
                FieldValue(
                    field_type=FieldType.DELIVERY_DEADLINE,
                    value=qtd_dias,
                    unit="DIAS",
                    item_id=None,
                    evidence=[ev],
                    review_status=ReviewStatus.EXTRACTED,
                )
            )

        # 2. Estimativa de Orçamento / Valor Total
        match_budget = re.search(
            r"\b(?:valor\s+total\s+(?:estimado|da\s+contrata[cç][aã]o)|estimativa\s+de\s+pre[cç]os?|or[cç]amento\s+estimado|valor\s+global)\s*(?:[:=]|\s+de|\s+em)?\s*R\$\s*([\d\.,]+)",
            text,
            re.IGNORECASE,
        )
        if match_budget:
            val_moeda = _parse_moeda(match_budget.group(1))
            if val_moeda is not None:
                ev = Evidence(
                    document_id=document_id,
                    page=block.page if block.page is not None and block.page >= 1 else 1,
                    block_id=block.id,
                    quote=block.text,
                )
                fields.append(
                    FieldValue(
                        field_type=FieldType.BUDGET_ESTIMATE,
                        value=str(val_moeda),
                        unit="BRL",
                        item_id=None,
                        evidence=[ev],
                        review_status=ReviewStatus.EXTRACTED,
                    )
                )

    return fields


def extract_prose_items(doc_ext: ExtractedDocument, document_id: str) -> list[Item]:
    """Extrai itens listados em parágrafos de texto (quando não há tabelas)."""
    items: list[Item] = []
    seen_ids: set[str] = set()

    for block in doc_ext.iter_blocks(include_children=True):
        if block.type.value in ("TABLE", "IMAGE") or not (block.text or "").strip():
            continue
        text = _clean_text(block.text)

        match_item = re.match(
            r"^(?:Item|Lote)\s*(\d+)\s*[-–—:]\s*(.+)$",
            text,
            re.IGNORECASE,
        )
        if match_item:
            num = int(match_item.group(1))
            item_id = f"item-{num:04d}"
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            desc = match_item.group(2).strip()
            item_ev = Evidence(
                document_id=document_id,
                page=block.page if block.page is not None and block.page >= 1 else 1,
                block_id=block.id,
                quote=block.text,
            )

            field_values: list[FieldValue] = []
            # Procurar quantidade na descrição
            match_qtd = re.search(
                r"\b(?:quantidade|qtd|quant\.?)\s*(?:estimada)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(unidades?|un|peças?|cx|kg|l)?\b",
                desc,
                re.IGNORECASE,
            )
            if match_qtd:
                val = _parse_quantidade(match_qtd.group(1))
                un = match_qtd.group(2) or "UN"
                if val is not None:
                    field_values.append(
                        FieldValue(
                            field_type=FieldType.QUANTITY,
                            value=float(val) if val == int(val) else float(val),
                            unit=un.upper(),
                            item_id=item_id,
                            evidence=[item_ev],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )

            items.append(
                Item(
                    id=item_id,
                    description=desc,
                    field_values=field_values,
                    requirements=[],
                    evidence=[item_ev],
                )
            )

    return items
