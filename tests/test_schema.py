import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from licita_core.schema import (
    Document,
    Evidence,
    ProcurementProcess,
    SCHEMA_VERSION,
    Section,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA_FILE = (
    Path(__file__).parent.parent / "schemas" / "procurement_process.v0.1.0.json"
)


def _all_evidence(proc: ProcurementProcess) -> list[Evidence]:
    evidence: list[Evidence] = [e for f in proc.findings for e in f.evidence]
    for doc in proc.documents:
        for fv in doc.field_values:
            evidence.extend(fv.evidence)
        for req in doc.requirements:
            evidence.extend(req.evidence)
        for section in doc.sections:
            evidence.append(section.evidence)
        for item in doc.items:
            evidence.extend(item.evidence)
            for fv in item.field_values:
                evidence.extend(fv.evidence)
            for req in item.requirements:
                evidence.extend(req.evidence)
    return evidence


@pytest.mark.parametrize("name", ["quantity_missing.json", "quantity_present.json"])
def test_fixture_validates_with_pydantic(name: str) -> None:
    proc = ProcurementProcess.model_validate(
        json.loads((FIXTURES / name).read_text())
    )
    assert proc is not None


@pytest.mark.parametrize("name", ["quantity_missing.json", "quantity_present.json"])
def test_schema_version_is_010(name: str) -> None:
    proc = ProcurementProcess.model_validate(
        json.loads((FIXTURES / name).read_text())
    )
    assert proc.schema_version == SCHEMA_VERSION == "0.1.0"


@pytest.mark.parametrize("name", ["quantity_missing.json", "quantity_present.json"])
def test_all_evidence_has_valid_page(name: str) -> None:
    proc = ProcurementProcess.model_validate(
        json.loads((FIXTURES / name).read_text())
    )
    for evidence in _all_evidence(proc):
        assert evidence.page >= 1


@pytest.mark.parametrize("page", [True, False, 1.0, "1"])
def test_evidence_page_requires_strict_int(page: object) -> None:
    with pytest.raises(ValidationError):
        Evidence(
            document_id="doc-1",
            page=page,
            block_id="block-1",
            quote="trecho original",
        )


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_non_empty_string_rejects_empty_and_whitespace(value: str) -> None:
    with pytest.raises(ValidationError):
        Evidence(
            document_id=value,
            page=1,
            block_id="block-1",
            quote="trecho original",
        )


def test_non_empty_string_preserves_surrounding_whitespace() -> None:
    evidence = Evidence(
        document_id=" texto ",
        page=1,
        block_id="block-1",
        quote=" texto ",
    )

    assert evidence.document_id == " texto "
    assert evidence.quote == " texto "


def test_non_empty_string_constraints_are_in_json_schema() -> None:
    schema = ProcurementProcess.model_json_schema()

    for model_name, field_name in (
        ("Evidence", "document_id"),
        ("Evidence", "quote"),
        ("DocumentBlock", "text"),
    ):
        field_schema = schema["$defs"][model_name]["properties"][field_name]
        assert field_schema["minLength"] == 1
        assert field_schema["pattern"] == r"\S"


def test_json_schema_generated() -> None:
    assert SCHEMA_FILE.exists(), "JSON Schema não foi gerado"
    on_disk = json.loads(SCHEMA_FILE.read_text())
    assert on_disk == ProcurementProcess.model_json_schema()


def test_document_entities_present() -> None:
    schema = ProcurementProcess.model_json_schema()
    definitions = schema.get("$defs", {})
    # ProcurementProcess é o modelo raiz (top-level), não fica em \\$defs.
    assert schema.get("title") == "ProcurementProcess"
    for entity in (
        "Document",
        "Section",
        "DocumentBlock",
        "Item",
        "FieldValue",
        "Requirement",
        "Evidence",
        "Finding",
    ):
        assert entity in definitions, f"entidade ausente no JSON Schema: {entity}"


def test_evidence_document_and_block_are_navigable(
    present_process: ProcurementProcess,
) -> None:
    evidence = present_process.documents[0].items[0].field_values[0].evidence[0]
    document = next(
        document
        for document in present_process.documents
        if document.id == evidence.document_id
    )
    block = next(
        block
        for section in document.sections
        for block in section.blocks
        if block.id == evidence.block_id
    )

    assert block.text == evidence.quote


@pytest.mark.parametrize(
    ("field", "invalid_id"),
    [("document_id", "document-inexistente"), ("block_id", "block-inexistente")],
)
def test_broken_evidence_reference_is_rejected(field: str, invalid_id: str) -> None:
    data = json.loads((FIXTURES / "quantity_missing.json").read_text())
    data["documents"][0]["sections"][0]["evidence"][field] = invalid_id

    with pytest.raises(ValidationError, match=invalid_id):
        ProcurementProcess.model_validate(data)


def test_unknown_model_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Document.model_validate(
            {
                "id": "doc-1",
                "type": "TR",
                "format": "DOCX",
                "unknown": "não permitido",
            }
        )


def test_evidence_quote_can_be_an_excerpt(
    present_process: ProcurementProcess,
) -> None:
    data = present_process.model_dump(mode="json")
    data["documents"][0]["sections"][0]["evidence"]["quote"] = "Notebook"

    process = ProcurementProcess.model_validate(data)

    assert process.documents[0].sections[0].evidence.quote == "Notebook"


def test_evidence_quote_must_be_contained_in_referenced_block() -> None:
    data = json.loads((FIXTURES / "quantity_missing.json").read_text())
    data["documents"][0]["sections"][0]["evidence"]["quote"] = "não está no bloco"

    with pytest.raises(ValidationError, match="b-obj-tbl-1"):
        ProcurementProcess.model_validate(data)


def test_empty_quote_is_rejected() -> None:
    data = json.loads((FIXTURES / "quantity_missing.json").read_text())
    data["documents"][0]["sections"][0]["evidence"]["quote"] = "   "

    with pytest.raises(ValidationError):
        ProcurementProcess.model_validate(data)


def test_empty_ids_are_rejected_even_when_references_are_consistent() -> None:
    data = json.loads((FIXTURES / "quantity_missing.json").read_text())
    data["id"] = ""
    data["documents"][0]["id"] = ""
    data["documents"][0]["sections"][0]["id"] = ""
    data["documents"][0]["sections"][0]["blocks"][0]["id"] = ""
    data["documents"][0]["sections"][0]["evidence"]["document_id"] = ""
    data["documents"][0]["sections"][0]["evidence"]["block_id"] = ""
    data["documents"][0]["items"][0]["id"] = ""

    with pytest.raises(ValidationError):
        ProcurementProcess.model_validate(data)


@pytest.mark.parametrize("field", ["title", "section_type_normalized"])
def test_optional_strings_reject_whitespace(
    present_process: ProcurementProcess, field: str
) -> None:
    data = present_process.model_dump(mode="json")
    if field == "title":
        data["documents"][0][field] = "   "
    else:
        data["documents"][0]["sections"][0][field] = "   "

    with pytest.raises(ValidationError):
        ProcurementProcess.model_validate(data)


def test_requirement_attribute_and_finding_message_must_not_be_empty() -> None:
    data = json.loads((FIXTURES / "quantity_missing.json").read_text())
    evidence = {
        "document_id": "tr-1",
        "page": 1,
        "block_id": "b-obj-tbl-1",
        "quote": "Notebook",
    }
    data["documents"][0]["requirements"] = [
        {
            "attribute": "   ",
            "operator": "EQUAL",
            "value": True,
            "evidence": [evidence],
        }
    ]
    with pytest.raises(ValidationError):
        ProcurementProcess.model_validate(data)

    data["documents"][0]["requirements"][0]["attribute"] = "quantidade"
    data["findings"] = [
        {
            "rule_id": "RULE-X",
            "severity": "LOW",
            "message": "   ",
            "evidence": [evidence],
        }
    ]
    with pytest.raises(ValidationError):
        ProcurementProcess.model_validate(data)


def test_section_keeps_original_title_and_optional_normalized_type(
    present_process: ProcurementProcess,
) -> None:
    section = present_process.documents[0].sections[0]

    assert section.title_original == "DEFINIÇÃO DO OBJETO"
    assert section.section_type_normalized == "OBJECT"
    assert "title" not in Section.model_fields