"""Esboco R2: ``arquivo → ProcurementProcess`` com blocos da R3, sem inventar fatos.

A saída é o ponto de partida da conversão manual. Não conta para o gate da R2
enquanto ``items`` / ``field_values`` / ``requirements`` estiverem vazios.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from licita_core.schema import (
    Document,
    DocumentBlock,
    DocumentFormat,
    DocumentType,
    Evidence,
    ProcurementProcess,
    Section,
)
from licita_ingest import BlockType, extract_document

_TIPOS_NAO_CITAVEIS = {BlockType.TABLE, BlockType.IMAGE}


def _citaveis(extracted) -> list:
    blocos = []
    for block in extracted.iter_blocks(include_children=True):
        if block.type in _TIPOS_NAO_CITAVEIS:
            continue
        if not (block.text or "").strip():
            continue
        blocos.append(block)
    return blocos


def _document_block(block) -> DocumentBlock:
    return DocumentBlock(id=block.id, type=block.type.value, text=block.text)


def _evidence(document_id: str, block) -> Evidence:
    page = block.page if block.page is not None and block.page >= 1 else 1
    return Evidence(
        document_id=document_id,
        page=page,
        block_id=block.id,
        quote=block.text,
    )


def _sections(document_id: str, blocos: Sequence) -> list[Section]:
    if not blocos:
        raise ValueError(f"{document_id}: ingestão sem bloco citável")

    sections: list[Section] = []
    titulo = "CORPO"
    atual: list = []

    def fechar() -> None:
        if not atual:
            return
        primeiro = atual[0]
        sections.append(
            Section(
                id=f"{document_id}:sec-{len(sections) + 1:04d}",
                title_original=titulo,
                blocks=[_document_block(block) for block in atual],
                evidence=_evidence(document_id, primeiro),
            )
        )

    for block in blocos:
        if block.type is BlockType.HEADER:
            fechar()
            titulo = block.text.strip()
            atual = [block]
            continue
        atual.append(block)
    fechar()
    return sections


def esboco_documento(
    caminho: str | Path,
    *,
    document_id: str,
    document_type: DocumentType,
) -> Document:
    """Extrai blocos e monta um ``Document`` sem itens nem requisitos."""

    extracted = extract_document(caminho, document_id=document_id)
    blocos = _citaveis(extracted)
    return Document(
        id=document_id,
        type=document_type,
        format=DocumentFormat(extracted.format.value),
        title=Path(caminho).name,
        sections=_sections(document_id, blocos),
    )


def esboco_processo(
    process_id: str,
    documentos: Sequence[tuple[str | Path, DocumentType]],
) -> ProcurementProcess:
    """Monta o processo com um documento por arquivo informado."""

    if not documentos:
        raise ValueError("informe ao menos um documento")
    docs = [
        esboco_documento(caminho, document_id=f"{process_id}:{tipo.value.lower()}", document_type=tipo)
        for caminho, tipo in documentos
    ]
    return ProcurementProcess(id=process_id, documents=docs)


def _tipo(valor: str) -> DocumentType:
    return DocumentType(valor.upper())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera esboço ProcurementProcess a partir de PDF/DOCX (R3→R2)."
    )
    parser.add_argument("--id", required=True, help="id estável do processo")
    parser.add_argument("--etp", type=Path, help="arquivo do ETP")
    parser.add_argument("--tr", type=Path, help="arquivo do TR")
    parser.add_argument("--saida", type=Path, required=True)
    args = parser.parse_args(argv)

    pares: list[tuple[Path, DocumentType]] = []
    if args.etp is not None:
        pares.append((args.etp, DocumentType.ETP))
    if args.tr is not None:
        pares.append((args.tr, DocumentType.TR))
    if not pares:
        parser.error("informe --etp e/ou --tr")

    processo = esboco_processo(args.id, pares)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(processo.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
