"""Testes unitários e de integração para a Camada Semântica (Fase R9).

Valida:
- Decomposição em atributos atômicos de especificações complexas (AtomicRequirementEngine);
- Linter semântico de termos vagos e subjetivos (SEM-001);
- Linter semântico de direcionamento de marcas (SEM-002);
- Conformidade estrita com o schema Requirement e Finding;
- Ancoragem obrigatória de evidências textuais.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from licita_core.schema import (
    Document,
    DocumentBlock,
    DocumentFormat,
    DocumentType,
    Evidence,
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
from licita_core.semantic import (
    AtomicRequirementEngine,
    SemanticEngine,
    SemanticLinter,
)


@pytest.fixture
def vehicle_item() -> Item:
    quote = (
        "VEÍCULO TIPO PASSEIO, MINI SUV, ZERO KM, MOTOR 1.8, Tipo De Combustível: Flex, "
        "Ano/Modelo: 2024/2024 ou superior, Cor Branca, Câmbio Manual, Com 07 (Sete) Lugares, "
        "Com Airbags, Ar Condicionado, Trava Elétrica. Veículos de Referência: Chevrolet/Spin ou similar."
    )
    ev = Evidence(
        document_id="p-01:tr",
        page=1,
        block_id="p-01:tr:p-0001:b-0001",
        quote=quote,
    )
    return Item(
        id="item-1",
        description=quote,
        field_values=[],
        requirements=[],
        evidence=[ev],
    )


@pytest.fixture
def tractor_item() -> Item:
    quote = (
        "Trator agrícola de pneus, motor 6 cilindros, com 171 cv de potência, tração 4x4, "
        "Colhedora de forragens com 2 rotores, 12 facas cada rotor, largura de 2.30 m."
    )
    ev = Evidence(
        document_id="p-02:tr",
        page=1,
        block_id="p-02:tr:p-0001:b-0001",
        quote=quote,
    )
    return Item(
        id="item-1",
        description=quote,
        field_values=[],
        requirements=[],
        evidence=[ev],
    )


def test_atomic_engine_vehicle_decomposition(vehicle_item: Item) -> None:
    engine = AtomicRequirementEngine()
    reqs = engine.extract_from_item(vehicle_item, document_id="p-01:tr")

    attrs_map = {r.attribute.lower(): r for r in reqs}

    assert "lugares" in attrs_map
    assert attrs_map["lugares"].value == 7
    assert attrs_map["lugares"].operator == RequirementOperator.GREATER_THAN_OR_EQUAL

    assert "combustivel" in attrs_map
    assert attrs_map["combustivel"].value.lower() == "flex"

    assert "cambio" in attrs_map
    assert attrs_map["cambio"].value.lower() == "manual"

    assert "cor" in attrs_map
    assert attrs_map["cor"].value.lower() == "branca"

    assert "ano_modelo" in attrs_map
    assert "2024" in str(attrs_map["ano_modelo"].value)

    assert attrs_map["opcional_airbags"].value is True
    assert attrs_map["opcional_ar_condicionado"].value is True

    # Valida que todos os requisitos gerados possuem evidência válida
    for r in reqs:
        assert len(r.evidence) >= 1
        assert r.evidence[0].quote != ""
        assert r.evidence[0].page == 1


def test_atomic_engine_tractor_decomposition(tractor_item: Item) -> None:
    engine = AtomicRequirementEngine()
    reqs = engine.extract_from_item(tractor_item, document_id="p-02:tr")

    attrs_map = {r.attribute.lower(): r for r in reqs}

    assert "potencia_cv" in attrs_map
    assert attrs_map["potencia_cv"].value == 171

    assert "tracao" in attrs_map
    assert attrs_map["tracao"].value == "4x4"

    assert "quantidade_rotores" in attrs_map
    assert attrs_map["quantidade_rotores"].value == 2

    assert "quantidade_facas" in attrs_map
    assert attrs_map["quantidade_facas"].value == 12


def test_semantic_linter_vague_terms_detection() -> None:
    text = "Papel sulfite A4 de primeira qualidade e marca de renome no mercado."
    ev = Evidence(document_id="p-03:tr", page=1, block_id="b1", quote=text)
    b1 = DocumentBlock(id="b1", type="PARAGRAPH", text=text)

    item = Item(
        id="item-1",
        description=text,
        field_values=[],
        requirements=[],
        evidence=[ev],
    )
    doc = Document(
        id="p-03:tr",
        type=DocumentType.TR,
        format=DocumentFormat.PDF,
        title="TR",
        sections=[Section(id="s1", title_original="S1", blocks=[b1], evidence=ev)],
        items=[item],
        field_values=[],
        requirements=[],
    )
    proc = ProcurementProcess(id="p-03", documents=[doc], findings=[])

    linter = SemanticLinter()
    findings = linter.run(proc)

    vague_findings = [f for f in findings if f.rule_id == "SEM-001"]
    assert len(vague_findings) >= 1
    assert any("primeira qualidade" in f.message for f in vague_findings)
    assert vague_findings[0].severity == Severity.HIGH
    assert vague_findings[0].category == FindingCategory.COMPLIANCE


def test_semantic_linter_brand_direction_without_equivalent() -> None:
    text = "Computador portátil marca Dell com processador Intel Core i7."
    ev = Evidence(document_id="p-04:tr", page=1, block_id="b1", quote=text)
    b1 = DocumentBlock(id="b1", type="PARAGRAPH", text=text)

    item_dir = Item(
        id="item-1",
        description=text,
        field_values=[],
        requirements=[],
        evidence=[ev],
    )
    doc = Document(
        id="p-04:tr",
        type=DocumentType.TR,
        format=DocumentFormat.PDF,
        title="TR",
        sections=[Section(id="s1", title_original="S1", blocks=[b1], evidence=ev)],
        items=[item_dir],
        field_values=[],
        requirements=[],
    )
    proc = ProcurementProcess(id="p-04", documents=[doc], findings=[])

    linter = SemanticLinter()
    findings = linter.run(proc)

    brand_findings = [f for f in findings if f.rule_id == "SEM-002"]
    assert len(brand_findings) == 1
    assert "Dell" in brand_findings[0].message
    assert brand_findings[0].severity == Severity.HIGH


def test_semantic_linter_brand_with_equivalent_allowed() -> None:
    text = "Computador portátil padrão Dell Inspiron ou similar/equivalente."
    ev = Evidence(document_id="p-05:tr", page=1, block_id="b1", quote=text)
    b1 = DocumentBlock(id="b1", type="PARAGRAPH", text=text)

    item_ok = Item(
        id="item-1",
        description=text,
        field_values=[],
        requirements=[],
        evidence=[ev],
    )
    doc = Document(
        id="p-05:tr",
        type=DocumentType.TR,
        format=DocumentFormat.PDF,
        title="TR",
        sections=[Section(id="s1", title_original="S1", blocks=[b1], evidence=ev)],
        items=[item_ok],
        field_values=[],
        requirements=[],
    )
    proc = ProcurementProcess(id="p-05", documents=[doc], findings=[])

    linter = SemanticLinter()
    findings = linter.run(proc)

    # Marca permitida pois possui "ou similar/equivalente"
    brand_findings = [f for f in findings if f.rule_id == "SEM-002"]
    assert len(brand_findings) == 0


def test_semantic_engine_full_lifecycle(vehicle_item: Item) -> None:
    ev = vehicle_item.evidence[0]
    b1 = DocumentBlock(id=ev.block_id, type="PARAGRAPH", text=vehicle_item.description)
    doc = Document(
        id="p-01:tr",
        type=DocumentType.TR,
        format=DocumentFormat.PDF,
        title="TR",
        sections=[Section(id="s1", title_original="S1", blocks=[b1], evidence=ev)],
        items=[vehicle_item],
        field_values=[],
        requirements=[],
    )
    proc = ProcurementProcess(id="p-01", documents=[doc], findings=[])

    engine = SemanticEngine()
    findings = engine.process_procurement(proc)

    # Verifica que os requisitos foram enriquecidos
    assert len(proc.documents[0].items[0].requirements) >= 5

    # Valida integridade do modelo Pydantic
    assert proc.model_dump() is not None
