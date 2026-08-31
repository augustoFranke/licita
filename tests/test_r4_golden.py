"""Testes formais de validação do Golden Dataset (Fase R4).

Verifica os critérios de saída da R4:
- 10 a 15 processos reais elegíveis no perfil MUNICIPAL_14133_PREGAO_ELETRONICO_BENS;
- >= 300 valores e requisitos com evidência navegável;
- Split dev / eval formalmente congelado e estritamente disjunto;
- 100% de validação no schema fechado ProcurementProcess;
- 100% de reabertura de evidências sobre os documentos físicos em disco;
- Conformidade com o manifesto da R4 e política 4-municipal-historical-ocr.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from licita_core.schema import ProcurementProcess
from licita_ingest.extractor import extract_document, sha256_file

ROOT_DIR = Path(__file__).resolve().parent.parent
R4_DIR = ROOT_DIR / "r4"
DEV_DIR = R4_DIR / "data" / "dev"
EVAL_DIR = R4_DIR / "data" / "eval"
MANIFEST_PATH = R4_DIR / "manifest.json"
CORPUS_DIR = ROOT_DIR / "corpus"
CATALOG_PATH = CORPUS_DIR / "catalogo" / "documentos.jsonl"


def test_r4_manifest_integrity_and_disjoint_split() -> None:
    assert MANIFEST_PATH.exists(), f"Manifesto {MANIFEST_PATH} não encontrado"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["profile"] == "MUNICIPAL_14133_PREGAO_ELETRONICO_BENS"
    assert manifest["esfera"] == "M"
    assert manifest["policy"] == "4-municipal-historical-ocr"

    dev_ids = set(manifest["split"]["dev"])
    eval_ids = set(manifest["split"]["eval"])

    assert len(dev_ids) == 5, f"Esperados 5 processos em dev, obtidos {len(dev_ids)}"
    assert len(eval_ids) == 5, f"Esperados 5 processos em eval, obtidos {len(eval_ids)}"
    assert dev_ids.isdisjoint(eval_ids), "Split contaminado: interseção entre dev e eval não é vazia!"

    dev_files = {f.stem for f in DEV_DIR.glob("*.json")}
    eval_files = {f.stem for f in EVAL_DIR.glob("*.json")}

    assert dev_files == dev_ids, f"Arquivos em dev/ divergem do manifesto: {dev_files} != {dev_ids}"
    assert eval_files == eval_ids, f"Arquivos em eval/ divergem do manifesto: {eval_files} != {eval_ids}"


def test_r4_volume_and_schema_validation() -> None:
    all_files = list(DEV_DIR.glob("*.json")) + list(EVAL_DIR.glob("*.json"))
    assert len(all_files) == 10

    total_items = 0
    total_fields = 0
    total_reqs = 0

    for file_path in all_files:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        process = ProcurementProcess.model_validate(data)

        n_items = sum(len(d.items) for d in process.documents)
        n_fields = sum(len(d.field_values) for d in process.documents) + sum(
            len(it.field_values) for d in process.documents for it in d.items
        )
        n_reqs = sum(len(d.requirements) for d in process.documents) + sum(
            len(it.requirements) for d in process.documents for it in d.items
        )

        total_items += n_items
        total_fields += n_fields
        total_reqs += n_reqs

    total_values_and_reqs = total_fields + total_reqs
    assert total_values_and_reqs >= 300, (
        f"Meta de anotação da R4 não atingida: {total_values_and_reqs} < 300"
    )
    assert total_items >= 50, f"Total de itens estruturados insuficiente: {total_items}"


def test_r4_evidence_anchors_reopen_against_corpus() -> None:
    all_files = sorted(list(DEV_DIR.glob("*.json")) + list(EVAL_DIR.glob("*.json")))

    catalogo = {}
    for linha in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        reg = json.loads(linha)
        catalogo[(str(reg["processo_id"]), str(reg["papel"]))] = reg

    total_evidencias = 0
    reabertas_ok = 0
    falhas = []

    for file_path in all_files:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        process = ProcurementProcess.model_validate(data)
        pid = process.id

        docs_extraidos = {}
        for doc in process.documents:
            cat = catalogo[(pid, doc.type.value)]
            raw_path = CORPUS_DIR / cat["arquivo"]
            assert raw_path.exists()
            assert sha256_file(raw_path) == cat["sha256"]

            extracted = extract_document(raw_path, document_id=doc.id)
            docs_extraidos[doc.id] = extracted

        for ev in process._iter_evidence():
            total_evidencias += 1
            doc_ext = docs_extraidos.get(ev.document_id)
            if not doc_ext:
                falhas.append((pid, ev.document_id, "doc_nao_extraido"))
                continue

            block = doc_ext.get_block(ev.block_id)
            if not block:
                falhas.append((pid, ev.document_id, "block_id_nao_encontrado", ev.block_id))
                continue

            if ev.page < 1:
                falhas.append((pid, ev.document_id, "pagina_invalida", ev.page))
                continue

            if ev.quote not in block.text:
                falhas.append((pid, ev.document_id, "quote_divergente", ev.quote))
                continue

            reabertas_ok += 1

    taxa = (reabertas_ok / total_evidencias * 100.0) if total_evidencias > 0 else 0.0
    assert len(falhas) == 0, f"Falhas de evidência na R4: {falhas[:5]}"
    assert taxa == 100.0, f"Taxa de reabertura da R4 abaixo de 100%: {taxa:.2f}%"
    assert total_evidencias >= 300, f"Total de evidências avaliadas insuficiente: {total_evidencias}"
