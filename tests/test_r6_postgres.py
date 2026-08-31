"""Integração da revisão humana (R6) com PostgreSQL.

Prova o que o estado em memória não sustenta: a revisão e a trilha de
auditoria sobrevivem ao restart do serviço, e o audit log não pode ser
alterado nem apagado.

Roda apenas com ``LICITA_REVIEW_DB_URL`` apontando para um PostgreSQL
acessível; a senha fica com o libpq (``~/.pgpass`` ou equivalente).
"""

from __future__ import annotations

import os

import psycopg
import pytest

from licita_core.schema import (
    Document,
    DocumentBlock,
    DocumentFormat,
    DocumentType,
    Evidence,
    FieldType,
    FieldValue,
    Item,
    ProcurementProcess,
    ReviewStatus,
    Section,
)
from licita_review.models import ReviewActionRequest, ReviewActionType
from licita_review.service import ReviewService
from licita_review.storage import PostgresStorage

DB_URL = os.environ.get("LICITA_REVIEW_DB_URL", "").strip()
SCHEMA = "teste_r6"

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason="LICITA_REVIEW_DB_URL não definida: integração com PostgreSQL não roda",
)


@pytest.fixture
def storage() -> PostgresStorage:
    store = PostgresStorage(DB_URL, schema=SCHEMA)
    store.drop()
    store.migrate()
    yield store
    store.drop()


@pytest.fixture
def processo() -> ProcurementProcess:
    doc_id = "proc-pg:tr"
    evidencia = Evidence(
        document_id=doc_id,
        page=1,
        block_id="proc-pg:tr:p-0001:b-0001",
        quote="Item 1: 40 unidades de cadeira empilhável",
    )
    bloco = DocumentBlock(
        id="proc-pg:tr:p-0001:b-0001",
        type="PARAGRAPH",
        text="Item 1: 40 unidades de cadeira empilhável",
    )
    outro_bloco = DocumentBlock(
        id="proc-pg:tr:p-0002:b-0007",
        type="PARAGRAPH",
        text="Retificação: 45 unidades de cadeira empilhável",
    )
    return ProcurementProcess(
        id="proc-pg",
        documents=[
            Document(
                id=doc_id,
                type=DocumentType.TR,
                format=DocumentFormat.PDF,
                title="TR persistência",
                sections=[
                    Section(
                        id="sec-001",
                        title_original="Corpo",
                        blocks=[bloco, outro_bloco],
                        evidence=evidencia,
                    )
                ],
                items=[
                    Item(
                        id="item-0001",
                        description="Cadeira empilhável",
                        field_values=[
                            FieldValue(
                                field_type=FieldType.QUANTITY,
                                value=40.0,
                                unit="UN",
                                item_id="item-0001",
                                evidence=[evidencia],
                                review_status=ReviewStatus.EXTRACTED,
                            )
                        ],
                        evidence=[evidencia],
                    )
                ],
            )
        ],
        findings=[],
    )


def test_revisao_e_audit_sobrevivem_ao_restart(storage, processo) -> None:
    """Um serviço novo, como depois de um restart, encontra tudo no banco."""
    servico = ReviewService(storage)
    servico.import_process(processo)

    servico.review_field_value(
        "proc-pg",
        "proc-pg:tr:item-0001:QUANTITY",
        ReviewActionRequest(
            user_id="revisor_ana",
            action=ReviewActionType.EDIT_AND_CONFIRM,
            new_value=45.0,
            new_evidence_quote="Retificação: 45 unidades de cadeira empilhável",
            notes="Retificação publicada",
        ),
    )

    # Instância nova, sem nenhum estado em memória herdado.
    reiniciado = ReviewService(PostgresStorage(DB_URL, schema=SCHEMA))

    fv = reiniciado.get_process("proc-pg").documents[0].items[0].field_values[0]
    assert fv.value == 45.0
    assert fv.review_status == ReviewStatus.CONFIRMED
    assert [ev.block_id for ev in fv.evidence] == ["proc-pg:tr:p-0002:b-0007"]
    assert fv.evidence[0].page == 2

    trilha = reiniciado.get_audit_trail("proc-pg")
    assert len(trilha) == 1
    assert trilha[0].user_id == "revisor_ana"
    assert trilha[0].previous_value == 40.0
    assert trilha[0].new_value == 45.0
    assert trilha[0].previous_status == ReviewStatus.EXTRACTED
    assert trilha[0].new_status == ReviewStatus.CONFIRMED
    assert trilha[0].previous_evidence[0].block_id == "proc-pg:tr:p-0001:b-0001"
    assert trilha[0].new_evidence[0].block_id == "proc-pg:tr:p-0002:b-0007"

    # Downstream continua expondo só o CONFIRMED, agora vindo do banco.
    confirmado = reiniciado.get_confirmed_process("proc-pg")
    assert [f.value for f in confirmado.documents[0].items[0].field_values] == [45.0]


def test_audit_log_nao_pode_ser_alterado_nem_apagado(storage, processo) -> None:
    """A imutabilidade da trilha é garantida pelo banco, não só pelo código."""
    servico = ReviewService(storage)
    servico.import_process(processo)
    servico.review_field_value(
        "proc-pg",
        "proc-pg:tr:item-0001:QUANTITY",
        ReviewActionRequest(action=ReviewActionType.CONFIRM),
    )

    with psycopg.connect(DB_URL, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="imutável"):
            conn.execute(f"UPDATE {SCHEMA}.review_audit SET process_id = 'outro'")
        with pytest.raises(psycopg.errors.RaiseException, match="imutável"):
            conn.execute(f"DELETE FROM {SCHEMA}.review_audit")

        restantes = conn.execute(
            f"SELECT count(*) FROM {SCHEMA}.review_audit"
        ).fetchone()[0]
    assert restantes == 1


def test_reimportar_processo_preserva_a_trilha(storage, processo) -> None:
    """Reimportar atualiza o payload sem apagar auditoria (FR-084 / R10)."""
    servico = ReviewService(storage)
    servico.import_process(processo)
    servico.review_field_value(
        "proc-pg",
        "proc-pg:tr:item-0001:QUANTITY",
        ReviewActionRequest(action=ReviewActionType.CONFIRM),
    )

    servico.import_process(processo)

    assert len(servico.get_audit_trail("proc-pg")) == 1
    fv = servico.get_process("proc-pg").documents[0].items[0].field_values[0]
    assert fv.review_status == ReviewStatus.EXTRACTED
