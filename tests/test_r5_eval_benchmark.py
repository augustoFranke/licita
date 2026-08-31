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
# Amostra mínima por família para a medida significar alguma coisa: abaixo
# disso um único acerto move a métrica dezenas de pontos.
MIN_SAMPLE_PER_FAMILY = 20

MEASURED_FIELDS = (
    FieldType.QUANTITY,
    FieldType.DELIVERY_DEADLINE,
    FieldType.WARRANTY_TERM,
)


def _item_number(item_id: str) -> int | None:
    match = re.search(r"\d+", item_id or "")
    return int(match.group()) if match else None


def _normalized(value: object) -> str:
    """Compara valores por igualdade numérica quando ela existir."""
    text = str(value).strip()
    try:
        return str(Decimal(text.replace(".", "").replace(",", ".")).normalize())
    except (InvalidOperation, ValueError):
        try:
            return str(Decimal(text).normalize())
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
        if p.get("annotation_provenance") == "manual"
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
        for ground_truth, extracted in measured:
            truth |= {(ground_truth.id, *k) for k in _field_set(ground_truth, field_type)}
            found |= {(extracted.id, *k) for k in _field_set(extracted, field_type)}
        hits = len(truth & found)
        precision = (hits / len(found) * 100) if found else 0.0
        recall = (hits / len(truth) * 100) if truth else 0.0
        metrics[field_type.value] = (precision, recall, len(truth), len(found))
        report.append(
            f"  {field_type.value:<18} precisão={precision:6.2f}% recall={recall:6.2f}% "
            f"(anotados={len(truth)}, extraídos={len(found)})"
        )

    req_truth: set[tuple] = set()
    req_found: set[tuple] = set()
    for ground_truth, extracted in measured:
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

    undersized = {
        name: truth_size
        for name, (_, _, truth_size, _) in metrics.items()
        if truth_size < MIN_SAMPLE_PER_FAMILY
    }
    assert not undersized, (
        f"Amostra insuficiente para medir a R5: {undersized} "
        f"(mínimo {MIN_SAMPLE_PER_FAMILY} valores anotados por família). "
        f"Só {len(measured)} processos do eval têm anotação manual; "
        f"{len(excluded)} foram excluídos por serem saída do próprio motor. "
        f"A R5 não pode ser medida antes de a R4 anotar manualmente o eval."
    )

    for name, (precision, recall, _, _) in metrics.items():
        assert precision >= MIN_PRECISION_FIELDS, f"{name}: precisão {precision:.2f}% < {MIN_PRECISION_FIELDS}%"
        assert recall >= MIN_RECALL_FIELDS, f"{name}: recall {recall:.2f}% < {MIN_RECALL_FIELDS}%"

    assert req_precision >= MIN_PRECISION_REQUIREMENTS, (
        f"Requisitos técnicos: precisão {req_precision:.2f}% < {MIN_PRECISION_REQUIREMENTS}%"
    )
