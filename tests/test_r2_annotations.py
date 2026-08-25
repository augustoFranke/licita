import json
from pathlib import Path

from licita_core.r2_annotations import (
    REQUIREMENT_COVERAGE_FIELD,
    V1_COVERAGE_FIELDS,
    build_coverage,
    load_annotation,
    main,
    validate_annotation,
    validate_annotations,
)
from licita_core.schema import FieldType, ProcurementProcess

FIXTURES = Path(__file__).parent / "fixtures" / "r2_annotations"
COMPLETE = FIXTURES / "complete.synthetic.json"
PARTIAL = FIXTURES / "partial.synthetic.json"


def test_complete_synthetic_annotation_validates_against_procurement_process() -> None:
    process = load_annotation(COMPLETE)

    assert isinstance(process, ProcurementProcess)
    assert process.id == "synthetic-r2-complete"
    assert process.schema_version == "0.1.0"


def test_complete_annotation_reports_every_v1_field() -> None:
    coverage = validate_annotation(COMPLETE)
    payload = coverage.to_dict()

    assert coverage.process_id == "synthetic-r2-complete"
    assert coverage.field_value_counts == {
        field_type.value: 1 for field_type in FieldType
    }
    assert coverage.requirement_count == 1
    assert payload["totals"]["field_values"]["total"] == len(FieldType)
    assert payload["totals"]["v1_fields"]["represented"] == list(
        V1_COVERAGE_FIELDS
    )
    assert payload["totals"]["v1_fields"]["unrepresented"] == []
    assert payload["totals"]["quantity_units"] == {
        "with_unit": 1,
        "without_unit": 0,
    }
    assert payload["totals"]["evidence_anchors"] == 12


def test_partial_coverage_is_diagnostic_not_a_schema_failure() -> None:
    report = validate_annotations([PARTIAL])
    payload = report.to_dict()
    v1 = payload["coverage"]["totals"]["v1_fields"]

    assert report.is_valid
    assert payload["validation"] == {
        "valid": True,
        "scope": "ProcurementProcess schema only",
        "requested_files": 1,
        "validated_files": 1,
        "invalid_files": 0,
    }
    assert v1["represented"] == [FieldType.QUANTITY.value]
    assert REQUIREMENT_COVERAGE_FIELD in v1["unrepresented"]
    assert set(v1["unrepresented"]) == set(V1_COVERAGE_FIELDS) - {
        FieldType.QUANTITY.value
    }


def test_aggregate_report_counts_nested_and_document_level_annotations() -> None:
    payload = validate_annotations([COMPLETE, PARTIAL]).to_dict()
    totals = payload["coverage"]["totals"]

    assert totals["processes"] == 2
    assert totals["documents"] == {
        "total": 2,
        "by_type": {"ETP": 1, "TR": 1, "EDITAL": 0, "CONTRATO": 0},
    }
    assert totals["items"] == 2
    assert totals["field_values"]["total"] == len(FieldType) + 1
    assert totals["field_values"]["by_type"][FieldType.QUANTITY.value] == 2
    assert totals["requirements"] == 1
    assert totals["evidence_anchors"] == 15
    assert totals["v1_fields"]["unrepresented"] == []
    json.dumps(payload)


def test_quantity_without_unit_is_visible_in_coverage() -> None:
    data = json.loads(PARTIAL.read_text(encoding="utf-8"))
    del data["documents"][0]["items"][0]["field_values"][0]["unit"]
    process = ProcurementProcess.model_validate(data)

    coverage = build_coverage(process)

    assert coverage.to_dict()["totals"]["quantity_units"] == {
        "with_unit": 0,
        "without_unit": 1,
    }


def test_schema_error_is_reported_without_partial_coverage(tmp_path: Path) -> None:
    data = json.loads(COMPLETE.read_text(encoding="utf-8"))
    evidence = data["documents"][0]["field_values"][0]["evidence"][0]
    evidence["block_id"] = "block-that-does-not-exist"
    invalid = tmp_path / "invalid-schema.synthetic.json"
    invalid.write_text(json.dumps(data), encoding="utf-8")

    report = validate_annotations([invalid])
    payload = report.to_dict()

    assert not report.is_valid
    assert payload["validation"]["validated_files"] == 0
    assert payload["coverage"]["totals"]["processes"] == 0
    assert payload["errors"][0]["kind"] == "schema"
    assert "block-that-does-not-exist" in payload["errors"][0]["details"][0][
        "message"
    ]


def test_batch_keeps_valid_coverage_and_reports_malformed_json(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.synthetic.json"
    malformed.write_text("{", encoding="utf-8")

    report = validate_annotations([PARTIAL, malformed])
    payload = report.to_dict()

    assert not report.is_valid
    assert payload["validation"]["requested_files"] == 2
    assert payload["validation"]["validated_files"] == 1
    assert payload["validation"]["invalid_files"] == 1
    assert payload["coverage"]["totals"]["processes"] == 1
    assert payload["errors"][0]["kind"] == "json"
    assert payload["errors"][0]["details"][0]["type"] == "json_invalid"


def test_missing_file_is_reported_as_io_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.synthetic.json"

    payload = validate_annotations([missing]).to_dict()

    assert payload["validation"]["valid"] is False
    assert payload["errors"][0]["kind"] == "io"
    assert payload["errors"][0]["details"][0]["type"] == "FileNotFoundError"


def test_cli_prints_json_and_uses_validation_exit_status(capsys) -> None:
    exit_status = main([str(PARTIAL)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_status == 0
    assert payload["validation"]["valid"] is True
    assert payload["coverage"]["totals"]["v1_fields"]["unrepresented"]
