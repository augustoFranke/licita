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


_NUM_POR_EXTENSO = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "quinze": 15, "vinte": 20, "trinta": 30, "quarenta": 40, "sessenta": 60,
    "noventa": 90, "cento e vinte": 120,
}

# Prazo de ENTREGA/fornecimento (não pagamento, não vigência). O número pode vir
# como dígito seguido de forma por extenso entre parênteses ("20(vinte) dias").
# Dois padrões: (A) uma âncora de entrega ANTES do número; (B) "no prazo de N
# dias" seguido, na mesma cláusula, de um gatilho de entrega ("após a
# autorização de fornecimento", "da ordem", "do recebimento") — é o que
# distingue entrega de pagamento sem depender da ordem das palavras.
_GATILHO_ENTREGA = (
    r"autoriza[çc][ãa]o\s+de\s+fornecimento|ordem\s+de\s+fornecimento|nota\s+de\s+empenho"
    r"|recebimento\s+da\s+(?:ordem|af|autoriza)|solicita[çc][ãa]o|assinatura\s+d[oa]\s+contrato"
)
_PRAZO_ENTREGA_RE = re.compile(
    r"(?:prazo\s+de\s+entrega|prazo\s+de\s+fornecimento|prazo\s+de\s+execu[çc][ãa]o\s+d[oa]\s+entrega"
    r"|entreg\w+\s+(?:no\s+prazo\s+de|em\s+at[ée]|em)|ser[áa]\s+entregue\s+(?:no\s+prazo\s+de|em))"
    r"\s*(\d{1,3})\s*(?:\([^)]*\))?\s*(dias?|horas?)",
    re.IGNORECASE,
)
_PRAZO_ENTREGA_GATILHO_RE = re.compile(
    r"no\s+prazo\s+de\s+(\d{1,3})\s*(?:\([^)]*\))?\s*(dias?|horas?)"
    rf"(?:(?!pagamento).){{0,80}}?(?:{_GATILHO_ENTREGA})",
    re.IGNORECASE,
)
# Garantia técnica / do produto: exige a palavra-âncora ANTES do número, para
# não capturar "validade da proposta" nem "garantia de execução" (caução).
_GARANTIA_RE = re.compile(
    r"garantia(?:\s+t[ée]cnica|\s+do\s+produto|\s+m[íi]nima|\s+contra\s+defeitos)?"
    r"(?:\s+de|\s+ser[áa]\s+de|\s+m[íi]nima\s+de|\s*:)?\s*(\d{1,3})\s*(?:\([^)]*\))?\s*(meses|m[êe]s|anos?)",
    re.IGNORECASE,
)


def _num_prazo(texto_num: str) -> int | None:
    texto_num = texto_num.strip().lower()
    if texto_num.isdigit():
        return int(texto_num)
    return _NUM_POR_EXTENSO.get(texto_num)


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

    # Prazo e garantia são campos documentais: um valor por documento. Emitir o
    # primeiro achado com contexto seguro evita multiplicar valores (uma cláusula
    # de substituição "em 5 dias" não é o prazo de entrega) e mantém a precisão.
    prazo_emitido = False
    garantia_emitida = False

    def _evid(block: StructuredBlock) -> Evidence:
        return Evidence(
            document_id=document_id,
            page=block.page if block.page is not None and block.page >= 1 else 1,
            block_id=block.id,
            quote=block.text,
        )

    for block in doc_ext.iter_blocks(include_children=True):
        if block.type.value in ("TABLE", "IMAGE") or not (block.text or "").strip():
            continue
        text = _clean_text(block.text)
        low = text.lower()

        # 1. Prazo de Entrega. Ignora cláusulas de pagamento e de vigência, que
        # têm seus próprios campos e não são o prazo operacional de entrega.
        if not prazo_emitido and "pagamento" not in low and "vig" not in low[:60]:
            m = _PRAZO_ENTREGA_RE.search(text) or _PRAZO_ENTREGA_GATILHO_RE.search(text)
            if m:
                dias = _num_prazo(m.group(1))
                if dias is not None:
                    fields.append(
                        FieldValue(
                            field_type=FieldType.DELIVERY_DEADLINE,
                            value=dias,
                            unit="DIAS",
                            item_id=None,
                            evidence=[_evid(block)],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )
                    prazo_emitido = True

        # 2. Garantia técnica / do produto (art. 40, §1º, III). Ausência é
        # legítima e não gera campo — só se extrai quando o TR a declara.
        if not garantia_emitida:
            mg = _GARANTIA_RE.search(text)
            if mg:
                num = _num_prazo(mg.group(1))
                unidade = mg.group(2).lower()
                if num is not None:
                    meses = num * 12 if unidade.startswith("ano") else num
                    fields.append(
                        FieldValue(
                            field_type=FieldType.WARRANTY_TERM,
                            value=meses,
                            unit="MESES",
                            item_id=None,
                            evidence=[_evid(block)],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )
                    garantia_emitida = True

        # 3. Estimativa de Orçamento / Valor Total
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
