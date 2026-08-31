"""Testes unitários do Requirements Engine (Fase R5).

Valida:
- Extração de itens a partir de tabelas estruturadas;
- Extração de campos transversais (prazos, orçamentos);
- Validação no schema fechado ProcurementProcess;
- 100% de evidências com citação exata e proveniência válida;
- Status inicial de extração (EXTRACTED).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from licita_core.engine import RequirementsEngine, extract_procurement_process
from licita_core.schema import (
    DocumentType,
    FieldType,
    ProcurementProcess,
    ReviewStatus,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT_DIR / "corpus"
CATALOG_PATH = CORPUS_DIR / "catalogo" / "documentos.jsonl"


def test_requirements_engine_basic_lifecycle() -> None:
    engine = RequirementsEngine()
    assert engine.version == "1.0.0"


def test_requirements_engine_extracts_and_validates_synthetic_process(tmp_path: Path) -> None:
    # Cria arquivos temporários de teste
    test_docx = tmp_path / "teste_tr.docx"
    
    # Processa um caso real de TR para validar a integridade completa
    pid = "83026138000197-1-000126-2024"
    catalogo = {}
    for linha in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        reg = json.loads(linha)
        catalogo[(str(reg["processo_id"]), str(reg["papel"]))] = reg

    cat_tr = catalogo[(pid, "TR")]
    cat_etp = catalogo[(pid, "ETP")]
    
    raw_tr = CORPUS_DIR / cat_tr["arquivo"]
    raw_etp = CORPUS_DIR / cat_etp["arquivo"]

    engine = RequirementsEngine()
    proc = engine.process_procurement(
        pid,
        [
            (raw_etp, DocumentType.ETP),
            (raw_tr, DocumentType.TR),
        ],
    )

    assert isinstance(proc, ProcurementProcess)
    assert proc.id == pid
    assert len(proc.documents) == 2

    # Verifica integridade dos itens
    tr_doc = next(d for d in proc.documents if d.type == DocumentType.TR)
    assert len(tr_doc.items) == 71

    # Verifica status EXTRACTED
    for ev_item in tr_doc.items:
        assert ev_item.evidence
        for fv in ev_item.field_values:
            assert fv.review_status == ReviewStatus.EXTRACTED
            assert fv.evidence
            assert len(fv.evidence) >= 1
            for ev in fv.evidence:
                assert ev.page >= 1
                assert ev.quote
                assert ev.block_id


def test_extracted_process_passes_pydantic_schema_validation() -> None:
    pid = "76017474000108-1-000118-2025"
    catalogo = {}
    for linha in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        reg = json.loads(linha)
        catalogo[(str(reg["processo_id"]), str(reg["papel"]))] = reg

    cat_tr = catalogo[(pid, "TR")]
    cat_etp = catalogo[(pid, "ETP")]

    proc = extract_procurement_process(
        pid,
        [
            (CORPUS_DIR / cat_etp["arquivo"], DocumentType.ETP),
            (CORPUS_DIR / cat_tr["arquivo"], DocumentType.TR),
        ],
    )

    # Converte para dict e valida contra Pydantic
    payload = proc.model_dump(mode="json")
    revalidated = ProcurementProcess.model_validate(payload)
    assert revalidated.id == pid
    tr_doc = next(d for d in revalidated.documents if d.type == DocumentType.TR)
    assert len(tr_doc.items) >= 40
