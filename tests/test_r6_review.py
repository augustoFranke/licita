"""Testes unitários e de integração para o serviço de Revisão Humana (Fase R6).

Valida:
- Importação de processos e resumos;
- Transições de estado (EXTRACTED -> CONFIRMED, REJECTED, EDIT_AND_CONFIRM);
- Aplicação estrita da regra FR-013 (bloqueio de confirmação sem evidência);
- Preservação do valor original em rejeições;
- Registro imutável de audit trail (quem, quando, anterior, posterior);
- Exportação downstream contendo exclusivamente dados CONFIRMED;
- Endpoints REST da API FastAPI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    Requirement,
    RequirementOperator,
    ReviewStatus,
    Section,
)
from licita_review.app import app, service
from licita_review.models import (
    ReviewActionRequest,
    ReviewActionType,
    ReviewTargetType,
)
from licita_review.service import ReviewService


@pytest.fixture
def sample_process() -> ProcurementProcess:
    doc_id = "proc-001:tr"
    ev = Evidence(
        document_id=doc_id,
        page=2,
        block_id="proc-001:tr:p-0002:b-0001",
        quote="Entrega em até 30 dias.",
    )
    item_ev = Evidence(
        document_id=doc_id,
        page=1,
        block_id="proc-001:tr:p-0001:b-0005",
        quote="Item 1: Caderno Universitário, 500 unidades",
    )

    fv_deadline = FieldValue(
        field_type=FieldType.DELIVERY_DEADLINE,
        value=30,
        unit="DIAS",
        item_id=None,
        evidence=[ev],
        review_status=ReviewStatus.EXTRACTED,
    )
    fv_qtd = FieldValue(
        field_type=FieldType.QUANTITY,
        value=500.0,
        unit="UN",
        item_id="item-0001",
        evidence=[item_ev],
        review_status=ReviewStatus.EXTRACTED,
    )
    req_catmat = Requirement(
        attribute="catmat",
        operator=RequirementOperator.EQUAL,
        value="123456",
        unit=None,
        item_id="item-0001",
        evidence=[item_ev],
        review_status=ReviewStatus.EXTRACTED,
    )

    item1 = Item(
        id="item-0001",
        description="Caderno Universitário 200 folhas",
        field_values=[fv_qtd],
        requirements=[req_catmat],
        evidence=[item_ev],
    )

    b1 = DocumentBlock(
        id="proc-001:tr:p-0002:b-0001",
        type="PARAGRAPH",
        text="Entrega em até 30 dias.",
    )
    b2 = DocumentBlock(
        id="proc-001:tr:p-0001:b-0005",
        type="PARAGRAPH",
        text="Item 1: Caderno Universitário, 500 unidades",
    )

    doc = Document(
        id=doc_id,
        type=DocumentType.TR,
        format=DocumentFormat.PDF,
        title="TR Teste",
        sections=[
            Section(
                id="sec-001",
                title_original="Corpo",
                blocks=[b1, b2],
                evidence=ev,
            )
        ],
        items=[item1],
        field_values=[fv_deadline],
        requirements=[],
    )

    return ProcurementProcess(
        id="proc-001",
        documents=[doc],
        findings=[],
    )


def test_review_service_confirm_and_audit(sample_process: ProcurementProcess) -> None:
    srv = ReviewService()
    srv.import_process(sample_process)

    # 1. Confirma prazo de entrega
    target_id = "proc-001:tr:DELIVERY_DEADLINE"
    audit = srv.review_field_value(
        "proc-001",
        target_id,
        ReviewActionRequest(
            user_id="revisor_joao",
            action=ReviewActionType.CONFIRM,
            notes="Conferido com o item 5 do TR",
        ),
    )

    assert audit.action == ReviewActionType.CONFIRM
    assert audit.previous_status == ReviewStatus.EXTRACTED
    assert audit.new_status == ReviewStatus.CONFIRMED
    assert audit.user_id == "revisor_joao"
    assert audit.previous_value == 30
    assert audit.new_value == 30

    # 2. Confirma quantidade de item
    target_item_qtd = "proc-001:tr:item-0001:QUANTITY"
    audit_item = srv.review_field_value(
        "proc-001",
        target_item_qtd,
        ReviewActionRequest(
            user_id="revisor_joao",
            action=ReviewActionType.CONFIRM,
        ),
    )
    assert audit_item.new_status == ReviewStatus.CONFIRMED

    # 3. Verifica audit trail
    trail = srv.get_audit_trail("proc-001")
    assert len(trail) == 2


def test_review_service_edit_and_confirm(sample_process: ProcurementProcess) -> None:
    srv = ReviewService()
    srv.import_process(sample_process)

    target_item_qtd = "proc-001:tr:item-0001:QUANTITY"
    fv_evidencia_anterior = sample_process.documents[0].items[0].field_values[0].evidence[0]
    audit = srv.review_field_value(
        "proc-001",
        target_item_qtd,
        ReviewActionRequest(
            user_id="revisor_maria",
            action=ReviewActionType.EDIT_AND_CONFIRM,
            new_value=600.0,
            new_unit="PACOTES",
            new_evidence_quote="Item 1: Caderno Universitário, 500 unidades",
            notes="Corrigido conforme errata do edital",
        ),
    )

    assert audit.action == ReviewActionType.EDIT_AND_CONFIRM
    assert audit.previous_value == 500.0
    assert audit.new_value == 600.0
    assert audit.new_status == ReviewStatus.CONFIRMED

    proc = srv.get_process("proc-001")
    doc = proc.documents[0]
    fv = doc.items[0].field_values[0]
    assert fv.value == 600.0
    assert fv.unit == "PACOTES"
    assert fv.review_status == ReviewStatus.CONFIRMED

    # A âncora passa a ser a do trecho informado, resolvida no bloco real.
    assert [ev.block_id for ev in fv.evidence] == ["proc-001:tr:p-0001:b-0005"]
    assert fv.evidence[0].page == 1
    assert audit.new_evidence == fv.evidence
    assert audit.previous_evidence == [fv_evidencia_anterior]


def test_edit_and_confirm_troca_a_ancora(sample_process: ProcurementProcess) -> None:
    """A âncora registrada passa a ser a do trecho informado na edição."""
    srv = ReviewService()
    srv.import_process(sample_process)

    audit = srv.review_field_value(
        "proc-001",
        "proc-001:tr:DELIVERY_DEADLINE",
        ReviewActionRequest(
            action=ReviewActionType.EDIT_AND_CONFIRM,
            new_value=15,
            new_evidence_quote="Item 1: Caderno Universitário, 500 unidades",
        ),
    )

    fv = srv.get_process("proc-001").documents[0].field_values[0]
    assert [ev.block_id for ev in fv.evidence] == ["proc-001:tr:p-0001:b-0005"]
    assert fv.evidence[0].page == 1
    assert audit.previous_evidence[0].block_id == "proc-001:tr:p-0002:b-0001"
    assert audit.previous_evidence[0].page == 2


def test_edit_and_confirm_exige_trecho_do_documento(sample_process: ProcurementProcess) -> None:
    """Editar sem reancorar deixaria um CONFIRMED apontando para o valor antigo."""
    srv = ReviewService()
    srv.import_process(sample_process)

    with pytest.raises(ValueError, match="FR-013"):
        srv.review_field_value(
            "proc-001",
            "proc-001:tr:item-0001:QUANTITY",
            ReviewActionRequest(
                action=ReviewActionType.EDIT_AND_CONFIRM,
                new_value=600.0,
            ),
        )

    fv = srv.get_process("proc-001").documents[0].items[0].field_values[0]
    assert fv.value == 500.0
    assert fv.review_status == ReviewStatus.EXTRACTED


def test_edit_and_confirm_recusa_trecho_inexistente(sample_process: ProcurementProcess) -> None:
    """A evidência tem de ser texto literal de um bloco ingerido."""
    srv = ReviewService()
    srv.import_process(sample_process)

    with pytest.raises(ValueError, match="Trecho não encontrado"):
        srv.review_field_value(
            "proc-001",
            "proc-001:tr:item-0001:QUANTITY",
            ReviewActionRequest(
                action=ReviewActionType.EDIT_AND_CONFIRM,
                new_value=600.0,
                new_evidence_quote="600 unidades conforme combinado por telefone",
            ),
        )

    fv = srv.get_process("proc-001").documents[0].items[0].field_values[0]
    assert fv.review_status == ReviewStatus.EXTRACTED


def test_edit_and_confirm_recusa_evidencia_do_outro_documento(
    sample_process: ProcurementProcess,
) -> None:
    """Valor do TR não pode ser sustentado por texto do ETP.

    A evidência emprestada faria a R7 comparar ETP e TR sobre o mesmo trecho.
    """
    etp = Document(
        id="proc-001:etp",
        type=DocumentType.ETP,
        format=DocumentFormat.PDF,
        title="ETP Teste",
        sections=[
            Section(
                id="sec-etp-001",
                title_original="Corpo",
                blocks=[
                    DocumentBlock(
                        id="proc-001:etp:p-0001:b-0001",
                        type="PARAGRAPH",
                        text="Estimativa preliminar de 900 unidades.",
                    )
                ],
                evidence=Evidence(
                    document_id="proc-001:etp",
                    page=1,
                    block_id="proc-001:etp:p-0001:b-0001",
                    quote="Estimativa preliminar de 900 unidades.",
                ),
            )
        ],
    )
    processo = sample_process.model_copy(
        update={"documents": [*sample_process.documents, etp]}
    )

    srv = ReviewService()
    srv.import_process(processo)

    with pytest.raises(ValueError, match="Trecho não encontrado"):
        srv.review_field_value(
            "proc-001",
            "proc-001:tr:item-0001:QUANTITY",
            ReviewActionRequest(
                action=ReviewActionType.EDIT_AND_CONFIRM,
                new_value=900.0,
                new_evidence_quote="Estimativa preliminar de 900 unidades.",
            ),
        )


def test_review_service_reject_preserves_original(sample_process: ProcurementProcess) -> None:
    srv = ReviewService()
    srv.import_process(sample_process)

    target_id = "proc-001:tr:DELIVERY_DEADLINE"
    audit = srv.review_field_value(
        "proc-001",
        target_id,
        ReviewActionRequest(
            user_id="revisor_carlos",
            action=ReviewActionType.REJECT,
            notes="Dado espúrio",
        ),
    )

    assert audit.action == ReviewActionType.REJECT
    assert audit.new_status == ReviewStatus.REJECTED
    assert audit.new_value == 30  # Valor original preservado

    # Exportação downstream não inclui REJECTED
    confirmed_proc = srv.get_confirmed_process("proc-001")
    doc = confirmed_proc.documents[0]
    assert len(doc.field_values) == 0  # Campo rejeitado excluído da visão confirmada


def test_review_service_blocks_confirmation_without_evidence(sample_process: ProcurementProcess) -> None:
    # Remove evidência do campo
    sample_process.documents[0].field_values[0].evidence = []

    srv = ReviewService()
    srv.import_process(sample_process)

    target_id = "proc-001:tr:DELIVERY_DEADLINE"
    with pytest.raises(ValueError, match="FR-013"):
        srv.review_field_value(
            "proc-001",
            target_id,
            ReviewActionRequest(
                user_id="revisor_test",
                action=ReviewActionType.CONFIRM,
            ),
        )


def test_review_service_requirement_review(sample_process: ProcurementProcess) -> None:
    srv = ReviewService()
    srv.import_process(sample_process)

    target_req = "proc-001:tr:item-0001:req:catmat"
    audit = srv.review_requirement(
        "proc-001",
        target_req,
        ReviewActionRequest(
            user_id="revisor_ana",
            action=ReviewActionType.CONFIRM,
        ),
    )

    assert audit.target_type == ReviewTargetType.REQUIREMENT
    assert audit.new_status == ReviewStatus.CONFIRMED


def test_fastapi_review_api_lifecycle(sample_process: ProcurementProcess) -> None:
    client = TestClient(app)

    # 1. Importa processo via API
    payload = sample_process.model_dump(mode="json")
    res_import = client.post("/api/processes/import", json=payload)
    assert res_import.status_code == 200
    assert res_import.json()["status"] == "ok"

    # 2. Lista processos
    res_list = client.get("/api/processes")
    assert res_list.status_code == 200
    pids = [p["id"] for p in res_list.json()]
    assert "proc-001" in pids

    # 3. Detalhes do processo
    res_get = client.get("/api/processes/proc-001")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == "proc-001"

    # 4. Confirma campo via API
    target_id = "proc-001:tr:DELIVERY_DEADLINE"
    res_review = client.post(
        f"/api/processes/proc-001/fields/{target_id}/review",
        json={"user_id": "api_user", "action": "CONFIRM"},
    )
    assert res_review.status_code == 200
    assert res_review.json()["new_status"] == "CONFIRMED"

    # 5. Consulta audit trail via API
    res_audit = client.get("/api/processes/proc-001/audit")
    assert res_audit.status_code == 200
    assert len(res_audit.json()) >= 1

    # 6. Exporta processo confirmado via API
    res_conf = client.get("/api/processes/proc-001/confirmed")
    assert res_conf.status_code == 200
    assert res_conf.json()["id"] == "proc-001"

    # 7. Endpoint raiz da UI
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "text/html" in res_root.headers["content-type"]
