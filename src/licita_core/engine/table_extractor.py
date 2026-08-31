"""Extrator de itens, valores e requisitos a partir de tabelas estruturadas (R5)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Sequence

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
from licita_ingest.extractor import StructuredBlock, StructuredDocument


def _parse_moeda(texto: str) -> Decimal | None:
    if not texto:
        return None
    # Se contiver R$ ou valores numéricos
    match = re.search(r"R?\$?\s*([\d\.,]+)", texto)
    if not match:
        return None
    limpo = match.group(1).strip()
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


def _parse_quantidade(texto: str) -> Decimal | None:
    if not texto:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", texto)
    if not match:
        return None
    limpo = match.group(1).strip()
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


def _clean_text(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def extract_items_from_tables(doc_ext: StructuredDocument, document_id: str) -> list[Item]:
    """Extrai itens e seus FieldValues/Requirements das tabelas do documento."""
    items: list[Item] = []
    seen_item_ids: set[str] = set()

    for table in doc_ext.tables:
        row_count = table.metadata.get("row_count", 0)
        col_count = table.metadata.get("column_count", 0)
        if row_count == 0:
            continue

        all_table_text = " ".join(c.text for c in table.cells).upper()
        # Ignorar tabelas que sejam manifestamente matriz de risco ou controle administrativo
        if (
            "MATRIZ DE RISCO" in all_table_text
            or "GRAU DO RISCO" in all_table_text
            or "PROBABILIDADE" in all_table_text
            and "IMPACTO" in all_table_text
        ):
            continue

        # 1. Caso A: Tabela de Cartão de Item (ex: ITEM Nº 01 em cell [0,0])
        first_cell_text = ""
        for cell in table.cells:
            if cell.row_index == 0 and cell.column_index == 0:
                first_cell_text = _clean_text(cell.text)
                break

        # Não confundir RISCO 01 com ITEM 01
        if "RISCO" in first_cell_text.upper():
            continue

        match_card = re.match(
            r"ITEM\s*(?:Nº|N|NUMERO)?\s*(\d+)", first_cell_text, re.IGNORECASE
        )
        if match_card:
            num = int(match_card.group(1))
            base_id = f"item-{num:04d}"
            item_id = base_id
            counter = 1
            while item_id in seen_item_ids:
                counter += 1
                item_id = f"{base_id}-{counter:02d}"
            seen_item_ids.add(item_id)

            desc_text = ""
            desc_cell = None
            qtd_text = ""
            qtd_cell = None

            for r in range(row_count):
                r_cells = {c.column_index: c for c in table.cells if c.row_index == r}
                col0 = _clean_text(r_cells.get(0).text).upper() if 0 in r_cells else ""
                if "DESCRIÇÃO" in col0 and 1 in r_cells:
                    desc_text = _clean_text(r_cells[1].text)
                    desc_cell = r_cells[1]
                elif "QUANTIDADE" in col0 and 1 in r_cells:
                    qtd_text = _clean_text(r_cells[1].text)
                    qtd_cell = r_cells[1]

            if not desc_cell:
                for cell in table.cells:
                    if cell.row_index == 0 and cell.column_index == 1 and cell.text.strip():
                        desc_text = _clean_text(cell.text)
                        desc_cell = cell
                        break

            if desc_cell:
                item_ev = Evidence(
                    document_id=document_id,
                    page=desc_cell.page if desc_cell.page is not None and desc_cell.page >= 1 else 1,
                    block_id=desc_cell.id,
                    quote=desc_cell.text,
                )
                field_values: list[FieldValue] = []
                if qtd_cell:
                    match_qtd = re.search(
                        r"(\d+(?:[.,]\d+)?)\s*(unidades?|pares?|peças?|conjuntos?|rolos?|pct|cx)?",
                        qtd_text,
                        re.IGNORECASE,
                    )
                    if match_qtd:
                        val = _parse_quantidade(match_qtd.group(1))
                        un = match_qtd.group(2) or "UN"
                        if val is not None:
                            val_float = float(val) if val == int(val) else float(val)
                            qtd_ev = Evidence(
                                document_id=document_id,
                                page=qtd_cell.page if qtd_cell.page is not None and qtd_cell.page >= 1 else 1,
                                block_id=qtd_cell.id,
                                quote=qtd_cell.text,
                            )
                            field_values.append(
                                FieldValue(
                                    field_type=FieldType.QUANTITY,
                                    value=val_float,
                                    unit=un.upper(),
                                    item_id=item_id,
                                    evidence=[qtd_ev],
                                    review_status=ReviewStatus.EXTRACTED,
                                )
                            )
                items.append(
                    Item(
                        id=item_id,
                        description=desc_text,
                        field_values=field_values,
                        requirements=[],
                        evidence=[item_ev],
                    )
                )
            continue

        # 2. Caso B: Tabela Tabular Multilinha (Item | Descrição | Qtd | Valor ...)
        header_row = -1
        col_mapping: dict[str, int] = {}
        for r in range(min(5, row_count)):
            r_cells = {c.column_index: _clean_text(c.text).lower() for c in table.cells if c.row_index == r}
            # Checar se linha é rigorosamente cabeçalho
            has_item = any(
                v in ("item", "nº", "n.", "n", "numero", "lote", "#", "item nº", "item / lote", "it.")
                or v.startswith("item ")
                for v in r_cells.values()
            )
            has_desc = any(
                v.startswith("descri") or v.startswith("especifica") or v in ("objeto", "material", "produto", "discriminação")
                for v in r_cells.values()
            )
            if has_item and (has_desc or len(r_cells) >= 3):
                header_row = r
                for col_idx, col_name in r_cells.items():
                    if col_name in ("item", "nº", "n.", "n", "numero", "lote", "#", "item nº", "it.") or col_name.startswith("item"):
                        col_mapping["item"] = col_idx
                    elif col_name.startswith("descri") or col_name.startswith("especifica") or col_name in ("objeto", "material", "produto"):
                        col_mapping["desc"] = col_idx
                    elif "catmat" in col_name or "código" in col_name or col_name == "cod":
                        col_mapping["catmat"] = col_idx
                    elif "unid" in col_name or col_name in ("un", "und", "u.m.", "um"):
                        col_mapping["unit"] = col_idx
                    elif (
                        "quant" in col_name
                        or "qtd" in col_name
                        or "qnt" in col_name
                        or col_name in ("q", "qtde", "qt", "quant.")
                    ):
                        col_mapping["qtd"] = col_idx
                    elif "unit" in col_name or "v. unit" in col_name or col_name in ("r$", "valor"):
                        col_mapping["unit_price"] = col_idx
                    elif "total" in col_name or "v. total" in col_name or "r$ total" in col_name:
                        col_mapping["total_price"] = col_idx
                break

        if "desc" not in col_mapping:
            # Tentar inferir colunas posicionais padrão se houver >= 3 colunas e sem palavras de risco
            if col_count >= 3 and "RISCO" not in all_table_text:
                col_mapping["item"] = 0
                col_mapping["desc"] = 1
                if col_count == 4:
                    col_mapping["qtd"] = 2
                    col_mapping["unit_price"] = 3
                elif col_count == 5:
                    col_mapping["qtd"] = 2
                    col_mapping["unit_price"] = 3
                    col_mapping["total_price"] = 4
                elif col_count >= 7:
                    col_mapping["catmat"] = 2
                    col_mapping["unit"] = 3
                    col_mapping["qtd"] = 4
                    col_mapping["unit_price"] = 5
                    col_mapping["total_price"] = 6

        start_r = header_row + 1 if header_row >= 0 else 0
        for r in range(start_r, row_count):
            cells = {c.column_index: c for c in table.cells if c.row_index == r}
            if not cells:
                continue

            item_col = col_mapping.get("item", 0)
            desc_col = col_mapping.get("desc", 1)
            item_cell = cells.get(item_col)
            desc_cell = cells.get(desc_col)

            # Caso especial: se a descrição estiver em col 2 quando col 1 estiver vazia
            if not desc_cell or not desc_cell.text.strip():
                for alt_col in [1, 2, 3]:
                    if alt_col in cells and cells[alt_col].text.strip() and alt_col != item_col:
                        desc_cell = cells[alt_col]
                        break

            item_text = _clean_text(item_cell.text) if item_cell else ""
            desc_text = _clean_text(desc_cell.text) if desc_cell else ""

            if not desc_text or desc_text.lower() in ("descrição", "especificação", "objeto", "total"):
                continue

            if "TOTAL" in item_text.upper() or "TOTAL" in desc_text.upper() and len(desc_text) < 20:
                continue

            # Se a descrição contiver apenas indicadores de risco
            if "RISCO" in item_text.upper() or "RISCO" in desc_text.upper() and len(desc_text) < 30:
                continue

            match_num = re.match(r"^(\d+)", item_text)
            if not match_num:
                # Tentar extrair do início da descrição
                match_num = re.match(r"^(?:Item\s*)?(\d+)", desc_text, re.IGNORECASE)
                if not match_num:
                    continue
                num = int(match_num.group(1))
            else:
                num = int(match_num.group(1))

            base_id = f"item-{num:04d}"
            item_id = base_id
            counter = 1
            while item_id in seen_item_ids:
                counter += 1
                item_id = f"{base_id}-{counter:02d}"
            seen_item_ids.add(item_id)

            item_ev = Evidence(
                document_id=document_id,
                page=desc_cell.page if desc_cell and desc_cell.page is not None and desc_cell.page >= 1 else 1,
                block_id=desc_cell.id if desc_cell else (item_cell.id if item_cell else table.id),
                quote=desc_cell.text if desc_cell else (item_cell.text if item_cell else ""),
            )

            field_values: list[FieldValue] = []
            requirements: list[Requirement] = []

            # Quantidade
            if "qtd" in col_mapping and col_mapping["qtd"] in cells:
                q_cell = cells[col_mapping["qtd"]]
                q_val = _parse_quantidade(q_cell.text)
                if q_val is not None:
                    u_text = _clean_text(cells[col_mapping["unit"]].text) if "unit" in col_mapping and col_mapping["unit"] in cells else "UN"
                    if not u_text or len(u_text) > 15:
                        u_text = "UN"
                    field_values.append(
                        FieldValue(
                            field_type=FieldType.QUANTITY,
                            value=float(q_val) if q_val == int(q_val) else float(q_val),
                            unit=u_text.upper(),
                            item_id=item_id,
                            evidence=[
                                Evidence(
                                    document_id=document_id,
                                    page=q_cell.page if q_cell.page is not None and q_cell.page >= 1 else 1,
                                    block_id=q_cell.id,
                                    quote=q_cell.text,
                                )
                            ],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )
            elif col_count >= 5:
                # Procura uma célula com valor numérico plausível de quantidade
                for c_idx in [2, 3, 4]:
                    if c_idx in cells and c_idx != item_col and c_idx != desc_col:
                        q_cand = cells[c_idx]
                        q_val = _parse_quantidade(q_cand.text)
                        if q_val is not None and q_val > 0:
                            field_values.append(
                                FieldValue(
                                    field_type=FieldType.QUANTITY,
                                    value=float(q_val) if q_val == int(q_val) else float(q_val),
                                    unit="UN",
                                    item_id=item_id,
                                    evidence=[
                                        Evidence(
                                            document_id=document_id,
                                            page=q_cand.page if q_cand.page is not None and q_cand.page >= 1 else 1,
                                            block_id=q_cand.id,
                                            quote=q_cand.text,
                                        )
                                    ],
                                    review_status=ReviewStatus.EXTRACTED,
                                )
                            )
                            break

            # Preço Unitário
            if "unit_price" in col_mapping and col_mapping["unit_price"] in cells:
                up_cell = cells[col_mapping["unit_price"]]
                up_val = _parse_moeda(up_cell.text)
                if up_val is not None:
                    field_values.append(
                        FieldValue(
                            field_type=FieldType.UNIT_PRICE,
                            value=str(up_val),
                            unit="BRL",
                            item_id=item_id,
                            evidence=[
                                Evidence(
                                    document_id=document_id,
                                    page=up_cell.page if up_cell.page is not None and up_cell.page >= 1 else 1,
                                    block_id=up_cell.id,
                                    quote=up_cell.text,
                                )
                            ],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )

            # Preço Total
            if "total_price" in col_mapping and col_mapping["total_price"] in cells:
                tp_cell = cells[col_mapping["total_price"]]
                tp_val = _parse_moeda(tp_cell.text)
                if tp_val is not None:
                    field_values.append(
                        FieldValue(
                            field_type=FieldType.TOTAL_PRICE,
                            value=str(tp_val),
                            unit="BRL",
                            item_id=item_id,
                            evidence=[
                                Evidence(
                                    document_id=document_id,
                                    page=tp_cell.page if tp_cell.page is not None and tp_cell.page >= 1 else 1,
                                    block_id=tp_cell.id,
                                    quote=tp_cell.text,
                                )
                            ],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )

            # CATMAT
            if "catmat" in col_mapping and col_mapping["catmat"] in cells:
                c_cell = cells[col_mapping["catmat"]]
                c_text = _clean_text(c_cell.text)
                if c_text and re.match(r"^\d+$", c_text):
                    requirements.append(
                        Requirement(
                            attribute="catmat",
                            operator=RequirementOperator.EQUAL,
                            value=c_text,
                            unit=None,
                            item_id=item_id,
                            evidence=[
                                Evidence(
                                    document_id=document_id,
                                    page=c_cell.page if c_cell.page is not None and c_cell.page >= 1 else 1,
                                    block_id=c_cell.id,
                                    quote=c_cell.text,
                                )
                            ],
                            review_status=ReviewStatus.EXTRACTED,
                        )
                    )

            items.append(
                Item(
                    id=item_id,
                    description=desc_text,
                    field_values=field_values,
                    requirements=requirements,
                    evidence=[item_ev],
                )
            )

    return items
