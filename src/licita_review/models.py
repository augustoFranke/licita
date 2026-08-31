"""Modelos de dados para o módulo de Revisão Humana (Fase R6)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from licita_core.schema import Evidence, ReviewStatus


class ReviewActionType(str, Enum):
    CONFIRM = "CONFIRM"
    EDIT_AND_CONFIRM = "EDIT_AND_CONFIRM"
    REJECT = "REJECT"


class ReviewTargetType(str, Enum):
    FIELD_VALUE = "FIELD_VALUE"
    REQUIREMENT = "REQUIREMENT"
    ITEM = "ITEM"


class ReviewActionRequest(BaseModel):
    user_id: str = Field(default="revisor_humano_1", min_length=1)
    action: ReviewActionType
    new_value: Any | None = None
    new_unit: str | None = None
    new_evidence_quote: str | None = Field(
        default=None,
        description=(
            "Trecho literal do documento que sustenta o valor editado. "
            "Obrigatório em EDIT_AND_CONFIRM: a evidência anterior sustentava "
            "o valor anterior (FR-013)."
        ),
    )
    notes: str | None = None


class ReviewAuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    process_id: str
    target_id: str
    target_type: ReviewTargetType
    action: ReviewActionType
    user_id: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    previous_value: Any | None = None
    new_value: Any | None = None
    previous_status: ReviewStatus
    new_status: ReviewStatus
    previous_evidence: list[Evidence] | None = None
    new_evidence: list[Evidence] | None = None
    notes: str | None = None


class ProcessSummary(BaseModel):
    id: str
    documents_count: int
    items_count: int
    extracted_fields_count: int
    confirmed_fields_count: int
    rejected_fields_count: int
