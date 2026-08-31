"""Testes unitários do Consistency Engine (Fase R7).

Valida:
- Regra de Evidência Bilateral Obrigatória (FR-030–036);
- Comparadores determinísticos de Quantidade (CONST-001);
- Unidade de Fornecimento (CONST-002);
- Prazo de Entrega (CONST-003);
- Garantia Técnica (CONST-004);
- Estimativa de Orçamento/Preço (CONST-005);
- Requisitos Técnicos (CONST-006);
- Silêncio quando os documentos são compatíveis.
"""

from __future__ import annotations

import pytest

from licita_core.consistency import (
    BudgetComparator,
    ConsistencyEngine,
    DeliveryDeadlineComparator,
    QuantityComparator,
    SpecificationComparator,
    UnitComparator,
    WarrantyComparator,
    build_bilateral_finding,
)
from licita_core.schema import (
    Document,
    DocumentBlock,
    DocumentFormat,
    DocumentType,
    Evidence,
    FieldType,
    FieldValue,
    FindingCategory,
    FindingStatus,
    Item,
    ProcurementProcess,
    Requirement,
    RequirementOperator,
    ReviewStatus,
    Section,
    Severity,
)


@pytest.fixture
def clean_process_pair() -> tuple[Document, Document, ProcurementProcess]:
    ev_etp = Evidence(
        document_id="p-01:etp",
        page=1,
        block_id="p-01:etp:p-0001:b-0001",
        quote="Item 1: 50 unidades, R$ 100 cada. Entrega em 30 dias. Garantia de 12 meses.",
    )
    ev_tr = Evidence(
        document_id="p-01:tr",
        page=1,
        block_id="p-01:tr:p-0001:b-0001",
        quote="Item 1: 50 unidades, R$ 100 cada. Entrega em 30 dias. Garantia de 12 meses.",
    )

    b_etp = DocumentBlock(id="p-01:etp:p-0001:b-0001", type="PARAGRAPH", text=ev_etp.quote)
    b_tr = DocumentBlock(id="p-01:tr:p-0001:b-0001", type="PARAGRAPH", text=ev_tr.quote)

    item_etp = Item(
        id="item-0001",
        description="Cadeira giratória",
        field_values=[
            FieldValue(
                field_type=FieldType.QUANTITY,
                value=50.0,
                unit="UN",
                item_id="item-0001",
                evidence=[ev_etp],
                review_status=ReviewStatus.CONFIRMED,
            ),
            FieldValue(
                field_type=FieldType.TOTAL_PRICE,
                value="5000.00",
                unit="BRL",
                item_id="item-0001",
                evidence=[ev_etp],
                review_status=ReviewStatus.CONFIRMED,
            ),
        ],
        requirements=[
            Requirement(
                attribute="catmat",
                operator=RequirementOperator.EQUAL,
                value="112233",
                unit=None,
                item_id="item-0001",
                evidence=[ev_etp],
                review_status=ReviewStatus.CONFIRMED,
            )
        ],
        evidence=[ev_etp],
    )

    item_tr = Item(
        id="item-0001",
        description="Cadeira giratória",
        field_values=[
            FieldValue(
                field_type=FieldType.QUANTITY,
                value=50.0,
                unit="UNIDADE",
                item_id="item-0001",
                evidence=[ev_tr],
                review_status=ReviewStatus.CONFIRMED,
            ),
            FieldValue(
                field_type=FieldType.TOTAL_PRICE,
                value="5000.00",
                unit="BRL",
                item_id="item-0001",
                evidence=[ev_tr],
                review_status=ReviewStatus.CONFIRMED,
            ),
        ],
        requirements=[
            Requirement(
                attribute="catmat",
                operator=RequirementOperator.EQUAL,
                value="112233",
                unit=None,
                item_id="item-0001",
                evidence=[ev_tr],
                review_status=ReviewStatus.CONFIRMED,
            )
        ],
        evidence=[ev_tr],
    )

    doc_etp = Document(
        id="p-01:etp",
        type=DocumentType.ETP,
        format=DocumentFormat.PDF,
        title="ETP",
        sections=[Section(id="s1", title_original="S1", blocks=[b_etp], evidence=ev_etp)],
        items=[item_etp],
        field_values=[
            FieldValue(
                field_type=FieldType.DELIVERY_DEADLINE,
                value=30,
                unit="DIAS",
                evidence=[ev_etp],
                review_status=ReviewStatus.CONFIRMED,
            ),
            FieldValue(
                field_type=FieldType.WARRANTY_TERM,
                value=12,
                unit="MESES",
                evidence=[ev_etp],
                review_status=ReviewStatus.CONFIRMED,
            ),
            FieldValue(
                field_type=FieldType.TOTAL_PRICE,
                value="5000.00",
                unit="BRL",
                evidence=[ev_etp],
                review_status=ReviewStatus.CONFIRMED,
            ),
        ],
        requirements=[],
    )

    doc_tr = Document(
        id="p-01:tr",
        type=DocumentType.TR,
        format=DocumentFormat.PDF,
        title="TR",
        sections=[Section(id="s2", title_original="S2", blocks=[b_tr], evidence=ev_tr)],
        items=[item_tr],
        field_values=[
            FieldValue(
                field_type=FieldType.DELIVERY_DEADLINE,
                value=30,
                unit="DIAS",
                evidence=[ev_tr],
                review_status=ReviewStatus.CONFIRMED,
            ),
            FieldValue(
                field_type=FieldType.WARRANTY_TERM,
                value=12,
                unit="MESES",
                evidence=[ev_tr],
                review_status=ReviewStatus.CONFIRMED,
            ),
            FieldValue(
                field_type=FieldType.TOTAL_PRICE,
                value="5000.00",
                unit="BRL",
                evidence=[ev_tr],
                review_status=ReviewStatus.CONFIRMED,
            ),
        ],
        requirements=[],
    )

    proc = ProcurementProcess(id="p-01", documents=[doc_etp, doc_tr], findings=[])
    return doc_etp, doc_tr, proc


def test_consistency_engine_silence_on_consistent_process(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    engine = ConsistencyEngine()
    findings = engine.run(proc)
    assert len(findings) == 0, f"Processo consistente não deveria gerar findings: {findings}"


def test_quantity_comparator_detects_discrepancy(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    # Modifica quantidade no TR para 40
    doc_tr.items[0].field_values[0].value = 40.0

    comparator = QuantityComparator()
    findings = comparator.compare(doc_etp, doc_tr, proc)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CONST-001"
    assert f.category == FindingCategory.CONSISTENCY
    assert f.severity == Severity.HIGH
    assert len(f.evidence) >= 2
    # Valida evidência bilateral
    doc_ids = {ev.document_id for ev in f.evidence}
    assert "p-01:etp" in doc_ids
    assert "p-01:tr" in doc_ids


def test_unit_comparator_detects_discrepancy(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    # Modifica unidade no TR de UN para CAIXA
    doc_tr.items[0].field_values[0].unit = "CAIXA"

    comparator = UnitComparator()
    findings = comparator.compare(doc_etp, doc_tr, proc)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CONST-002"
    assert "CAIXA" in f.message


def test_deadline_comparator_detects_discrepancy(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    # Modifica prazo no TR de 30 para 15 dias
    doc_tr.field_values[0].value = 15

    comparator = DeliveryDeadlineComparator()
    findings = comparator.compare(doc_etp, doc_tr, proc)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CONST-003"
    assert "15 dias" in f.message


def test_warranty_comparator_detects_discrepancy(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    # Modifica garantia no TR de 12 para 24 meses
    doc_tr.field_values[1].value = 24

    comparator = WarrantyComparator()
    findings = comparator.compare(doc_etp, doc_tr, proc)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CONST-004"
    assert "24 meses" in f.message


def test_budget_comparator_detects_discrepancy(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    # Modifica orçamento global no TR de 5000 para 7500
    doc_tr.field_values[2].value = "7500.00"

    comparator = BudgetComparator()
    findings = comparator.compare(doc_etp, doc_tr, proc)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CONST-005"
    assert "7500" in f.message


def test_specification_comparator_detects_catmat_discrepancy(clean_process_pair) -> None:
    doc_etp, doc_tr, proc = clean_process_pair
    # Modifica código CATMAT no TR
    doc_tr.items[0].requirements[0].value = "998877"

    comparator = SpecificationComparator()
    findings = comparator.compare(doc_etp, doc_tr, proc)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CONST-006"
    assert "998877" in f.message


def test_bilateral_evidence_rule_enforcement() -> None:
    ev_a = Evidence(document_id="doc:etp", page=1, block_id="b1", quote="Texto ETP")
    ev_same_doc = Evidence(document_id="doc:etp", page=2, block_id="b2", quote="Outro texto ETP")

    # Tentativa de criar finding com evidências apenas de um documento DEVE falhar
    with pytest.raises(ValueError, match="distintos"):
        build_bilateral_finding(
            rule_id="CONST-001",
            title="Teste",
            description="Teste",
            severity=Severity.HIGH,
            evidence_a=ev_a,
            evidence_b=ev_same_doc,
        )
