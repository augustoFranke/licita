"""Helper para construir ProcurementProcess sintéticos a partir de markdown."""

from __future__ import annotations

import re
from typing import Any

from licita_core.schema import (
    BlockType,
    Document,
    DocumentBlock,
    DocumentFormat,
    DocumentType,
    Evidence,
    FieldType,
    FieldValue,
    Item,
    ProcurementProcess,
    Requirement,
    Section,
)


def _find_block_for_quote(
    sections: list[Section], quote: str
) -> tuple[str, int, str]:
    """Encontra block_id e página para uma citação, ou retorna o primeiro bloco."""
    for section in sections:
        for block in section.blocks:
            if quote in block.text:
                return block.id, section.evidence.page, quote
            if block.text in quote:
                return block.id, section.evidence.page, block.text

    # Se não encontrou exato, busca por palavra-chave ou primeiro bloco
    first_sec = sections[0]
    first_block = first_sec.blocks[0]
    return first_block.id, first_sec.evidence.page, first_block.text


def build_tr_process(
    markdown_text: str,
    *,
    process_id: str = "proc-synthetic-1",
    document_id: str = "tr-synthetic-1",
    extra_items: list[dict[str, Any]] | None = None,
    extra_field_values: list[dict[str, Any]] | None = None,
    extra_requirements: list[dict[str, Any]] | None = None,
) -> ProcurementProcess:
    """Converte markdown sintético de TR em um ProcurementProcess válido."""
    lines = markdown_text.strip().split("\n")
    sections: list[Section] = []
    doc_title = "TERMO DE REFERÊNCIA"

    curr_sec_title: str | None = None
    curr_blocks: list[DocumentBlock] = []
    block_counter = 1
    sec_counter = 1

    def flush_section() -> None:
        nonlocal sec_counter, curr_sec_title, curr_blocks
        if curr_sec_title is not None and curr_blocks:
            first_block = curr_blocks[0]
            sec_id = f"sec-{sec_counter:02d}"
            ev = Evidence(
                document_id=document_id,
                page=1,
                block_id=first_block.id,
                quote=first_block.text,
            )
            sections.append(
                Section(
                    id=sec_id,
                    title_original=curr_sec_title,
                    blocks=list(curr_blocks),
                    evidence=ev,
                )
            )
            sec_counter += 1
            curr_blocks = []

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("# ") and curr_sec_title is None and not sections:
            doc_title = line_str[2:].strip()
            continue
        if line_str.startswith("## ") or line_str.startswith("# "):
            flush_section()
            curr_sec_title = line_str.lstrip("#").strip()
            b_id = f"b-{block_counter:03d}"
            curr_blocks.append(
                DocumentBlock(
                    id=b_id,
                    type=BlockType.HEADER,
                    text=curr_sec_title,
                )
            )
            block_counter += 1
            continue

        if curr_sec_title is None:
            curr_sec_title = "CORPO"
            b_id = f"b-{block_counter:03d}"
            curr_blocks.append(
                DocumentBlock(
                    id=b_id,
                    type=BlockType.HEADER,
                    text=curr_sec_title,
                )
            )
            block_counter += 1

        b_id = f"b-{block_counter:03d}"
        b_type = BlockType.TABLE_CELL if line_str.startswith("|") else BlockType.PARAGRAPH
        curr_blocks.append(
            DocumentBlock(
                id=b_id,
                type=b_type,
                text=line_str,
            )
        )
        block_counter += 1

    flush_section()

    if not sections:
        b_id = "b-001"
        block = DocumentBlock(id=b_id, type=BlockType.PARAGRAPH, text=doc_title)
        ev = Evidence(document_id=document_id, page=1, block_id=b_id, quote=doc_title)
        sections.append(
            Section(
                id="sec-01",
                title_original=doc_title,
                blocks=[block],
                evidence=ev,
            )
        )

    # Identifica itens padrão se não fornecidos
    items: list[Item] = []
    if extra_items is not None:
        for it_data in extra_items:
            # Valida e ajusta evidências dos itens e field_values
            data = dict(it_data)
            it_evs = []
            for ev_data in data.get("evidence", []):
                quote = ev_data.get("quote", "")
                block_id, page, matched_quote = _find_block_for_quote(sections, quote)
                it_evs.append(
                    Evidence(
                        document_id=document_id,
                        page=page,
                        block_id=block_id,
                        quote=matched_quote,
                    )
                )
            if not it_evs:
                first_block = sections[0].blocks[0]
                it_evs.append(
                    Evidence(
                        document_id=document_id,
                        page=1,
                        block_id=first_block.id,
                        quote=first_block.text,
                    )
                )
            data["evidence"] = it_evs

            fvs = []
            for fv_data in data.get("field_values", []):
                fv_d = dict(fv_data)
                fv_evs = []
                for ev_data in fv_d.get("evidence", []):
                    quote = ev_data.get("quote", "")
                    block_id, page, matched_quote = _find_block_for_quote(sections, quote)
                    fv_evs.append(
                        Evidence(
                            document_id=document_id,
                            page=page,
                            block_id=block_id,
                            quote=matched_quote,
                        )
                    )
                if not fv_evs:
                    first_block = sections[0].blocks[0]
                    fv_evs.append(
                        Evidence(
                            document_id=document_id,
                            page=1,
                            block_id=first_block.id,
                            quote=first_block.text,
                        )
                    )
                fv_d["evidence"] = fv_evs
                fvs.append(FieldValue.model_validate(fv_d))
            data["field_values"] = fvs

            items.append(Item.model_validate(data))
    else:
        # Cria Item 1 a partir do primeiro bloco da seção de objeto ou primeiro bloco
        first_sec = sections[0]
        first_block = first_sec.blocks[0]
        it_ev = Evidence(
            document_id=document_id,
            page=1,
            block_id=first_block.id,
            quote=first_block.text,
        )
        # Extrai quantidade se presente no texto
        item_fvs = []
        full_text = " ".join(b.text for s in sections for b in s.blocks)
        qtd_match = re.search(r"Quantidade\s*(?:estimada)?:\s*(\d+)", full_text, re.IGNORECASE)
        un_match = re.search(r"Unidade\s*(?:de\s+fornecimento)?:\s*([a-zA-Z]+)", full_text, re.IGNORECASE)
        if qtd_match:
            b_id, p_num, q_text = _find_block_for_quote(sections, qtd_match.group(0))
            item_fvs.append(
                FieldValue(
                    field_type=FieldType.QUANTITY,
                    value=int(qtd_match.group(1)),
                    unit=un_match.group(1).lower() if un_match else "unidade",
                    item_id="item-1",
                    evidence=[
                        Evidence(
                            document_id=document_id,
                            page=p_num,
                            block_id=b_id,
                            quote=q_text,
                        )
                    ],
                )
            )

        items.append(
            Item(
                id="item-1",
                description="Item 1 sintético",
                field_values=item_fvs,
                evidence=[it_ev],
            )
        )

    field_values: list[FieldValue] = []
    if extra_field_values:
        for fv_data in extra_field_values:
            fv_d = dict(fv_data)
            fv_evs = []
            for ev_data in fv_d.get("evidence", []):
                quote = ev_data.get("quote", "")
                block_id, page, matched_quote = _find_block_for_quote(sections, quote)
                fv_evs.append(
                    Evidence(
                        document_id=document_id,
                        page=page,
                        block_id=block_id,
                        quote=matched_quote,
                    )
                )
            if not fv_evs:
                first_block = sections[0].blocks[0]
                fv_evs.append(
                    Evidence(
                        document_id=document_id,
                        page=1,
                        block_id=first_block.id,
                        quote=first_block.text,
                    )
                )
            fv_d["evidence"] = fv_evs
            field_values.append(FieldValue.model_validate(fv_d))

    requirements: list[Requirement] = []
    if extra_requirements:
        for req_data in extra_requirements:
            req_d = dict(req_data)
            req_evs = []
            for ev_data in req_d.get("evidence", []):
                quote = ev_data.get("quote", "")
                block_id, page, matched_quote = _find_block_for_quote(sections, quote)
                req_evs.append(
                    Evidence(
                        document_id=document_id,
                        page=page,
                        block_id=block_id,
                        quote=matched_quote,
                    )
                )
            if not req_evs:
                first_block = sections[0].blocks[0]
                req_evs.append(
                    Evidence(
                        document_id=document_id,
                        page=1,
                        block_id=first_block.id,
                        quote=first_block.text,
                    )
                )
            req_d["evidence"] = req_evs
            requirements.append(Requirement.model_validate(req_d))

    doc = Document(
        id=document_id,
        type=DocumentType.TR,
        format=DocumentFormat.DOCX,
        title=doc_title,
        sections=sections,
        items=items,
        field_values=field_values,
        requirements=requirements,
    )

    return ProcurementProcess(
        id=process_id,
        schema_version="0.1.0",
        documents=[doc],
    )
