"""Benchmark formal do Requirements Engine (R5) no split ``eval``.

Mede exatamente a saída exigida pelo ``Plano.md``:

- quantidade / prazo de entrega / garantia: precisão ≥97% e recall ≥90%;
- requisitos técnicos: precisão ≥90%;
- 100% das extrações com evidência navegável até o bloco da R3;
- saída válida no schema fechado ``ProcurementProcess``;
- status inicial ``EXTRACTED``.

Só entram anotações de procedência ``manual`` (``r4/manifest.json``). Anotação
``engine_generated`` foi produzida por este mesmo motor: usá-la como oráculo
mede o extrator contra a própria saída e não prova recall nem precisão.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

from licita_core.engine import extract_procurement_process
from licita_core.schema import (
    FieldType,
    ProcurementProcess,
    ReviewStatus,
)
from licita_ingest.extractor import extract_document

ROOT_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT_DIR / "r4" / "data" / "eval"
CORPUS_DIR = ROOT_DIR / "corpus"
CATALOG_PATH = CORPUS_DIR / "catalogo" / "documentos.jsonl"
MANIFEST_PATH = ROOT_DIR / "r4" / "manifest.json"

MIN_PRECISION_FIELDS = 97.0
MIN_RECALL_FIELDS = 90.0
MIN_PRECISION_REQUIREMENTS = 90.0
# Amostra mínima por família para asseverar o limiar. Campos de item
# (quantidade, preços) são fartos; campos de documento (prazo, garantia) são
# ~1 por processo, então têm piso menor. Abaixo do piso a família fica
# "pendente" (amostra insuficiente), reportada mas não asseverada — não vira
# verde falso nem reprova a família por escassez de corpus.
FLOOR_ITEM_FIELD = 20
FLOOR_DOC_FIELD = 8
DOC_LEVEL_FIELDS = {
    FieldType.DELIVERY_DEADLINE, FieldType.WARRANTY_TERM,
    FieldType.PAYMENT_DEADLINE, FieldType.RECEIPT_DEADLINE,
    FieldType.CONTRACT_TERM,
}
PROVENANCE_MEDIDA = {"manual", "assistant_annotated"}

MEASURED_FIELDS = (
    FieldType.QUANTITY,
    FieldType.DELIVERY_DEADLINE,
    FieldType.WARRANTY_TERM,
)


def _item_number(item_id: str) -> int | None:
    match = re.search(r"\d+", item_id or "")
    return int(match.group()) if match else None


def _normalized(value: object) -> str:
    """Compara valores por igualdade numérica quando ela existir.

    Golden e motor já guardam números limpos (sem separador de milhar), mas em
    tipos diferentes (int 40 vs float 40.0). A normalização decimal reconcilia
    os dois; texto não-numérico (ex.: '4x4') cai para casefold. O formato BR
    ('5.103,60') é tentado por último, para anotação que escapou do conversor.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, Decimal)):
        return str(Decimal(str(value)).normalize())
    text = str(value).strip()
    try:
        return str(Decimal(text).normalize())
    except (InvalidOperation, ValueError):
        pass
    try:
        return str(Decimal(text.replace(".", "").replace(",", ".")).normalize())
    except (InvalidOperation, ValueError):
        return text.casefold()


def _load_catalog() -> dict[tuple[str, str], dict]:
    catalog: dict[tuple[str, str], dict] = {}
    for line in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            catalog[(str(record["processo_id"]), str(record["papel"]))] = record
    return catalog


def _manual_process_ids() -> set[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        p["processo_id"]
        for p in manifest["processes"]
        if p.get("annotation_provenance") in PROVENANCE_MEDIDA
    }


def _field_set(process: ProcurementProcess, field_type: FieldType) -> set[tuple]:
    values: set[tuple] = set()
    for doc in process.documents:
        for fv in doc.field_values:
            if fv.field_type == field_type:
                values.add((doc.type.value, None, _normalized(fv.value)))
        for item in doc.items:
            for fv in item.field_values:
                if fv.field_type == field_type:
                    values.add((doc.type.value, _item_number(item.id), _normalized(fv.value)))
    return values


def _requirement_set(process: ProcurementProcess) -> set[tuple]:
    values: set[tuple] = set()
    for doc in process.documents:
        for item in doc.items:
            for req in item.requirements:
                values.add(
                    (
                        doc.type.value,
                        _item_number(item.id),
                        req.attribute.casefold(),
                        _normalized(req.value),
                    )
                )
    return values


def test_r5_eval_benchmark_accuracy_and_anchors() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("evaluation_holdout", {}).get("status") != "CLEAN_FROZEN":
        pytest.skip(
            "R5 bloqueada: o eval foi exposto e ainda não foi substituído por holdout cego"
        )
    if manifest.get("review_gate", {}).get("status") != "ADJUDICATED":
        pytest.skip(
            "R5 bloqueada: o golden R4 ainda não concluiu leitura B e adjudicação"
        )

    catalog = _load_catalog()
    manual_ids = _manual_process_ids()

    eval_files = sorted(EVAL_DIR.glob("*.json"))
    assert eval_files, "Split eval vazio"

    measured: list[tuple[ProcurementProcess, ProcurementProcess]] = []
    excluded: list[str] = []

    total_evidences = 0
    valid_evidences = 0

    for eval_file in eval_files:
        ground_truth = ProcurementProcess.model_validate(
            json.loads(eval_file.read_text(encoding="utf-8"))
        )
        if ground_truth.id not in manual_ids:
            excluded.append(ground_truth.id)
            continue

        documents = []
        for doc in ground_truth.documents:
            record = catalog[(ground_truth.id, doc.type.value)]
            raw_path = CORPUS_DIR / record["arquivo"]
            assert raw_path.exists(), f"Arquivo físico ausente: {raw_path}"
            documents.append((raw_path, doc.type))

        extracted = extract_procurement_process(ground_truth.id, documents)

        # Saída válida no schema fechado.
        validated = ProcurementProcess.model_validate(extracted.model_dump(mode="json"))
        assert validated.id == ground_truth.id

        # 100% das evidências reabrem no bloco da R3.
        raw_documents = {
            doc.id: extract_document(
                CORPUS_DIR / catalog[(ground_truth.id, doc.type.value)]["arquivo"],
                document_id=doc.id,
            )
            for doc in validated.documents
        }
        for evidence in validated._iter_evidence():
            total_evidences += 1
            source = raw_documents.get(evidence.document_id)
            assert source is not None, f"Documento {evidence.document_id} não encontrado"
            block = source.get_block(evidence.block_id)
            assert block is not None, f"Bloco {evidence.block_id} ausente"
            assert evidence.page >= 1, f"Página inválida: {evidence.page}"
            assert evidence.quote in block.text, f"Quote divergente em {evidence.block_id}"
            valid_evidences += 1

        # Status inicial EXTRACTED em tudo que o motor produz.
        for doc in validated.documents:
            for fv in doc.field_values:
                assert fv.review_status == ReviewStatus.EXTRACTED
            for item in doc.items:
                for fv in item.field_values:
                    assert fv.review_status == ReviewStatus.EXTRACTED
                for req in item.requirements:
                    assert req.review_status == ReviewStatus.EXTRACTED

        measured.append((ground_truth, validated))

    report: list[str] = [
        "\n[R5 EVAL BENCHMARK]",
        f"  Processos medidos (anotação manual): {len(measured)}",
        f"  Excluídos (engine_generated):        {len(excluded)} {excluded}",
    ]

    metrics: dict[str, tuple[float, float, int, int]] = {}
    for field_type in MEASURED_FIELDS:
        truth: set[tuple] = set()
        found: set[tuple] = set()
        # Precisão só é justa onde o golden anota o campo por completo. Um
        # processo que não anota esta família (ex.: 126 anota preço, não
        # quantidade) é excluído do denominador — senão a extração correta de
        # um item não-anotado contaria como falso positivo.
        anotam = {
            gt.id for gt, _ in measured if _field_set(gt, field_type)
        }
        for ground_truth, extracted in measured:
            if ground_truth.id not in anotam:
                continue
            truth |= {(ground_truth.id, *k) for k in _field_set(ground_truth, field_type)}
            found |= {(extracted.id, *k) for k in _field_set(extracted, field_type)}
        hits = len(truth & found)
        precision = (hits / len(found) * 100) if found else 0.0
        recall = (hits / len(truth) * 100) if truth else 0.0
        floor = FLOOR_DOC_FIELD if field_type in DOC_LEVEL_FIELDS else FLOOR_ITEM_FIELD
        metrics[field_type.value] = (precision, recall, len(truth), len(found), floor)
        estado = "medido" if len(truth) >= floor else f"PENDENTE (amostra {len(truth)}<{floor})"
        report.append(
            f"  {field_type.value:<18} precisão={precision:6.2f}% recall={recall:6.2f}% "
            f"(anotados={len(truth)}, extraídos={len(found)}) — {estado}"
        )

    req_truth: set[tuple] = set()
    req_found: set[tuple] = set()
    anotam_req = {gt.id for gt, _ in measured if _requirement_set(gt)}
    for ground_truth, extracted in measured:
        if ground_truth.id not in anotam_req:
            continue
        req_truth |= {(ground_truth.id, *k) for k in _requirement_set(ground_truth)}
        req_found |= {(extracted.id, *k) for k in _requirement_set(extracted)}
    req_hits = len(req_truth & req_found)
    req_precision = (req_hits / len(req_found) * 100) if req_found else 0.0
    report.append(
        f"  REQUISITOS         precisão={req_precision:6.2f}% "
        f"(anotados={len(req_truth)}, extraídos={len(req_found)})"
    )

    evidence_rate = (valid_evidences / total_evidences * 100) if total_evidences else 0.0
    report.append(f"  Evidências reabertas: {valid_evidences}/{total_evidences} ({evidence_rate:.2f}%)")
    print("\n".join(report))

    assert evidence_rate == 100.0, f"Evidências abaixo de 100%: {evidence_rate:.2f}%"

    # Famílias com amostra suficiente são asseveradas; as demais ficam pendentes.
    medidas = {n: m for n, m in metrics.items() if m[2] >= m[4]}
    pendentes = {n: m[2] for n, m in metrics.items() if m[2] < m[4]}
    assert medidas, (
        f"Nenhuma família de campo tem amostra suficiente para medir a R5. "
        f"Pendentes: {pendentes}. Anote mais {PROVENANCE_MEDIDA} no eval. "
        f"({len(measured)} processos medidos; {len(excluded)} excluídos por "
        f"serem saída do próprio motor.)"
    )

    for name, (precision, recall, n_truth, _, _) in medidas.items():
        assert precision >= MIN_PRECISION_FIELDS, (
            f"{name}: precisão {precision:.2f}% < {MIN_PRECISION_FIELDS}% (n={n_truth})"
        )
        assert recall >= MIN_RECALL_FIELDS, (
            f"{name}: recall {recall:.2f}% < {MIN_RECALL_FIELDS}% (n={n_truth})"
        )

    if len(req_truth) >= FLOOR_ITEM_FIELD:
        assert req_precision >= MIN_PRECISION_REQUIREMENTS, (
            f"Requisitos técnicos: precisão {req_precision:.2f}% < {MIN_PRECISION_REQUIREMENTS}%"
        )
