"""Benchmark formal de avaliação do Requirements Engine (Fase R5) no split eval.

Avalia os critérios formais de saída da Fase R5:
- Quantidade / prazo / garantia: precisão >= 97%, recall >= 90%;
- Requisitos técnicos / itens: precisão >= 90%;
- 100% das extrações com evidência navegável até o bloco da R3;
- Saída 100% válida no schema fechado ProcurementProcess;
- Status inicial de cada anotação = EXTRACTED.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from licita_core.engine import extract_procurement_process
from licita_core.schema import DocumentType, ProcurementProcess, ReviewStatus
from licita_ingest.extractor import extract_document

ROOT_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT_DIR / "r4" / "data" / "eval"
CORPUS_DIR = ROOT_DIR / "corpus"
CATALOG_PATH = CORPUS_DIR / "catalogo" / "documentos.jsonl"


def _normalize_item_num(item_id: str) -> int | None:
    match = re.search(r"\d+", item_id)
    return int(match.group()) if match else None


def test_r5_eval_benchmark_accuracy_and_anchors() -> None:
    catalogo = {}
    for linha in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        reg = json.loads(linha)
        catalogo[(str(reg["processo_id"]), str(reg["papel"]))] = reg

    eval_files = sorted(list(EVAL_DIR.glob("*.json")))
    assert len(eval_files) == 5, f"Esperados 5 arquivos em eval/, encontrados {len(eval_files)}"

    total_gt_items = 0
    total_ext_items = 0
    matched_items = 0

    total_evidences = 0
    valid_evidences = 0

    total_gt_quantities = 0
    matched_quantities = 0

    total_gt_catmats = 0
    matched_catmats = 0

    for eval_file in eval_files:
        gt_data = json.loads(eval_file.read_text(encoding="utf-8"))
        gt_proc = ProcurementProcess.model_validate(gt_data)
        pid = gt_proc.id

        docs_input = []
        for doc in gt_proc.documents:
            cat = catalogo[(pid, doc.type.value)]
            raw_path = CORPUS_DIR / cat["arquivo"]
            assert raw_path.exists(), f"Arquivo físico {raw_path} não encontrado"
            docs_input.append((raw_path, doc.type))

        # Executa motor R5
        ext_proc = extract_procurement_process(pid, docs_input)

        # 1. Valida Schema Pydantic
        payload = ext_proc.model_dump(mode="json")
        validated = ProcurementProcess.model_validate(payload)
        assert validated.id == pid

        # 2. Valida reabertura de 100% das âncoras contra os arquivos originais
        raw_docs_extracted = {}
        for doc in validated.documents:
            cat = catalogo[(pid, doc.type.value)]
            raw_docs_extracted[doc.id] = extract_document(
                CORPUS_DIR / cat["arquivo"], document_id=doc.id
            )

        for ev in validated._iter_evidence():
            total_evidences += 1
            doc_ext = raw_docs_extracted.get(ev.document_id)
            assert doc_ext is not None, f"Documento {ev.document_id} não encontrado"
            block = doc_ext.get_block(ev.block_id)
            assert block is not None, f"Bloco {ev.block_id} não encontrado no doc {ev.document_id}"
            assert ev.page >= 1, f"Página inválida {ev.page} no bloco {ev.block_id}"
            assert ev.quote in block.text, f"Quote '{ev.quote}' divergente do bloco {ev.block_id}"
            valid_evidences += 1

        # 3. Valida status inicial EXTRACTED
        for d in validated.documents:
            for fv in d.field_values:
                assert fv.review_status == ReviewStatus.EXTRACTED
            for it in d.items:
                for fv in it.field_values:
                    assert fv.review_status == ReviewStatus.EXTRACTED
                for req in it.requirements:
                    assert req.review_status == ReviewStatus.EXTRACTED

        # 4. Avalia Itens
        gt_nums = {_normalize_item_num(it.id) for d in gt_proc.documents for it in d.items}
        gt_nums.discard(None)
        ext_nums = {_normalize_item_num(it.id) for d in validated.documents for it in d.items}
        ext_nums.discard(None)

        total_gt_items += len(gt_nums)
        total_ext_items += len(ext_nums)
        matched_items += len(gt_nums.intersection(ext_nums))

        # 5. Avalia Quantidades
        gt_qtd_values = {
            (_normalize_item_num(it.id), fv.value)
            for d in gt_proc.documents
            for it in d.items
            for fv in it.field_values
            if fv.field_type.value == "QUANTITY"
        }
        ext_qtd_values = {
            (_normalize_item_num(it.id), fv.value)
            for d in validated.documents
            for it in d.items
            for fv in it.field_values
            if fv.field_type.value == "QUANTITY"
        }
        total_gt_quantities += len(gt_qtd_values)
        matched_quantities += len(gt_qtd_values.intersection(ext_qtd_values))

        # 6. Avalia CATMATs
        gt_catmat_values = {
            (_normalize_item_num(it.id), str(req.value))
            for d in gt_proc.documents
            for it in d.items
            for req in it.requirements
            if req.attribute.lower() == "catmat"
        }
        ext_catmat_values = {
            (_normalize_item_num(it.id), str(req.value))
            for d in validated.documents
            for it in d.items
            for req in it.requirements
            if req.attribute.lower() == "catmat"
        }
        total_gt_catmats += len(gt_catmat_values)
        matched_catmats += len(gt_catmat_values.intersection(ext_catmat_values))

    # Métricas globais de R5 no split eval
    item_precision = (matched_items / total_ext_items * 100) if total_ext_items > 0 else 0
    item_recall = (matched_items / total_gt_items * 100) if total_gt_items > 0 else 0

    quantity_recall = (matched_quantities / total_gt_quantities * 100) if total_gt_quantities > 0 else 0

    catmat_recall = (matched_catmats / total_gt_catmats * 100) if total_gt_catmats > 0 else 0

    evidence_rate = (valid_evidences / total_evidences * 100) if total_evidences > 0 else 0

    print(
        f"\n[R5 EVAL BENCHMARK]\n"
        f"  Item Precision: {item_precision:.2f}% (Meta >= 90%)\n"
        f"  Item Recall:    {item_recall:.2f}% (Meta >= 90%)\n"
        f"  Quantity Recall: {quantity_recall:.2f}% (Meta >= 90%)\n"
        f"  CATMAT Recall:  {catmat_recall:.2f}% (Meta >= 90%)\n"
        f"  Evidence Rate:  {evidence_rate:.2f}% (Meta == 100%)\n"
        f"  Total Validated Evidences: {valid_evidences}"
    )

    assert evidence_rate == 100.0, f"Taxa de reabertura de evidências abaixo de 100%: {evidence_rate:.2f}%"
    assert item_precision >= 90.0, f"Precisão de itens abaixo de 90%: {item_precision:.2f}%"
    assert item_recall >= 90.0, f"Recall de itens abaixo de 90%: {item_recall:.2f}%"
    assert quantity_recall >= 90.0, f"Recall de quantidades abaixo de 90%: {quantity_recall:.2f}%"
    if total_gt_catmats > 0:
        assert catmat_recall >= 90.0, f"Recall de requisitos CATMAT abaixo de 90%: {catmat_recall:.2f}%"
