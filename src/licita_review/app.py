"""Aplicação FastAPI para a Interface de Revisão Humana (Fase R6)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from licita_core.schema import ProcurementProcess
from licita_review.models import (
    ProcessSummary,
    ReviewActionRequest,
    ReviewAuditEntry,
)
from licita_review.service import ReviewService

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Licita — Human Review Service",
    version="1.0.0",
    description="Serviço e interface web para validação, edição e auditoria de extrações licitatórias.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = ReviewService()


def _preload_golden_data() -> None:
    root = Path(__file__).resolve().parent.parent.parent
    for split in ["dev", "eval"]:
        split_dir = root / "r4" / "data" / split
        if split_dir.exists():
            for f in sorted(split_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    proc = ProcurementProcess.model_validate(data)
                    service.import_process(proc)
                except Exception:
                    pass


_preload_golden_data()


@app.get("/api/processes", response_model=list[ProcessSummary])
def list_processes() -> list[ProcessSummary]:
    """Lista todos os processos carregados na área de trabalho de revisão."""
    return service.list_processes()


@app.post("/api/processes/import")
def import_process(payload: dict) -> dict[str, str]:
    """Importa um processo licitatório no schema ProcurementProcess."""
    try:
        proc = ProcurementProcess.model_validate(payload)
        service.import_process(proc)
        return {"status": "ok", "process_id": proc.id}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro de validação do processo: {e}",
        )


@app.get("/api/processes/{process_id}")
def get_process(process_id: str) -> dict:
    """Obtém os dados completos do processo para a UI de revisão."""
    try:
        proc = service.get_process(process_id)
        return proc.model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Processo '{process_id}' não encontrado",
        )


@app.post("/api/processes/{process_id}/fields/{field_id:path}/review", response_model=ReviewAuditEntry)
def review_field(
    process_id: str,
    field_id: str,
    request: ReviewActionRequest,
) -> ReviewAuditEntry:
    """Aplica uma ação de revisão (CONFIRM, EDIT_AND_CONFIRM, REJECT) em um FieldValue."""
    try:
        return service.review_field_value(process_id, field_id, request)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.post("/api/processes/{process_id}/requirements/{req_id:path}/review", response_model=ReviewAuditEntry)
def review_requirement(
    process_id: str,
    req_id: str,
    request: ReviewActionRequest,
) -> ReviewAuditEntry:
    """Aplica uma ação de revisão (CONFIRM, EDIT_AND_CONFIRM, REJECT) em um Requirement."""
    try:
        return service.review_requirement(process_id, req_id, request)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.get("/api/processes/{process_id}/audit", response_model=list[ReviewAuditEntry])
def get_audit(process_id: str) -> list[ReviewAuditEntry]:
    """Retorna o histórico de auditoria imutável de um processo."""
    try:
        return service.get_audit_trail(process_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Processo '{process_id}' não encontrado",
        )


@app.get("/api/processes/{process_id}/confirmed")
def get_confirmed_process(process_id: str) -> dict:
    """Exporta o processo contendo exclusivamente dados CONFIRMED para downstream."""
    try:
        confirmed = service.get_confirmed_process(process_id)
        return confirmed.model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Processo '{process_id}' não encontrado",
        )


# Montagem de arquivos estáticos da UI Web
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Licita Review API</h1><p>UI estática não encontrada.</p>")
