"""Aplicação FastAPI para a Interface de Revisão Humana (Fase R6)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from licita_core.schema import ProcurementProcess
from licita_review.models import (
    ProcessSummary,
    ReviewActionRequest,
    ReviewAuditEntry,
)
from licita_review.service import ReviewService
from licita_review.storage import InMemoryStorage, PostgresStorage, ReviewStorage

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Licita — Human Review Service",
    version="1.0.0",
    description="Serviço e interface web para validação, edição e auditoria de extrações licitatórias.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # A API não usa cookie nem credencial: origem "*" com credenciais é
    # combinação inválida no CORS e o navegador a rejeita.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

DB_URL_ENV = "LICITA_REVIEW_DB_URL"


def _build_storage() -> ReviewStorage:
    """Escolhe a persistência e diz em voz alta quando ela é volátil.

    Sem ``LICITA_REVIEW_DB_URL`` o serviço continua utilizável, mas revisão e
    audit log morrem no restart — a R6 não fecha nesse modo, e o operador
    precisa saber disso ao subir o app, não ao perder o trabalho.
    """
    conninfo = os.environ.get(DB_URL_ENV, "").strip()
    if not conninfo:
        logger.warning(
            "%s não definida: revisão e audit log ficam em memória e somem no "
            "restart. Defina a URL do PostgreSQL para persistir.",
            DB_URL_ENV,
        )
        return InMemoryStorage()
    storage = PostgresStorage(conninfo)
    storage.migrate()
    logger.info("Persistência em PostgreSQL ativa")
    return storage


service = ReviewService(_build_storage())


def _preload_golden_data() -> None:
    """Carrega o golden na área de revisão; arquivo ilegível é erro, não silêncio.

    NFR-002: falha de parsing nunca desaparece. Um processo que some da UI sem
    aviso vira ausência invisível de documento, exatamente o que o produto não
    pode fazer.
    """
    root = Path(__file__).resolve().parent.parent.parent
    ja_importados = set(service.list_process_ids())
    for split in ["dev", "eval"]:
        split_dir = root / "r4" / "data" / split
        if not split_dir.exists():
            continue
        for f in sorted(split_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                proc = ProcurementProcess.model_validate(data)
            except (OSError, json.JSONDecodeError, ValidationError) as erro:
                raise RuntimeError(
                    f"Processo do golden ilegível em {f}: {erro}"
                ) from erro
            # Reimportar sobrescreveria a revisão já persistida com a extração
            # original: quem já está no banco fica como está.
            if proc.id not in ja_importados:
                service.import_process(proc)


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
