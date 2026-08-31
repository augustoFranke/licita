import copy
import json
from datetime import date
from decimal import Decimal
from math import inf, nan

import pytest
from pydantic import ValidationError

from licita_core.schema import (
    FieldType,
    FieldValue,
    ProcurementProcess,
    Requirement,
    RequirementOperator,
)


EVIDENCE = {
    "document_id": "doc-1",
    "page": 1,
    "block_id": "block-1",
    "quote": "trecho original",
}


def _field_value(field_type: FieldType, value: object, **extra: object) -> FieldValue:
    return FieldValue(
        field_type=field_type,
        value=value,
        evidence=[EVIDENCE],
        **extra,
    )


def _requirement(operator: RequirementOperator, value: object) -> Requirement:
    return Requirement(
        attribute="quantidade",
        operator=operator,
        value=value,
        evidence=[EVIDENCE],
    )


@pytest.mark.parametrize("field_type", list(FieldType))
@pytest.mark.parametrize("value", [True, False])
def test_field_value_rejects_bool_for_every_field_type(
    field_type: FieldType, value: object
) -> None:
    with pytest.raises(ValidationError):
        _field_value(field_type, value)


@pytest.mark.parametrize("field_type", list(FieldType))
@pytest.mark.parametrize(
    "value",
    [nan, inf, -inf, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_field_value_rejects_non_finite_numeric_values_for_every_field_type(
    field_type: FieldType, value: object
) -> None:
    with pytest.raises(ValidationError):
        _field_value(field_type, value)


@pytest.mark.parametrize("field_type", list(FieldType))
@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_field_value_rejects_blank_strings_for_every_field_type(
    field_type: FieldType, value: str
) -> None:
    with pytest.raises(ValidationError, match="string não vazia"):
        _field_value(field_type, value)


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        (FieldType.QUANTITY, 10),
        (FieldType.DELIVERY_DEADLINE, "10 dias"),
        (FieldType.CONTRACT_TERM, "12 meses"),
        (FieldType.WARRANTY_TERM, "12 meses"),
        (FieldType.UNIT_PRICE, "10.00"),
        (FieldType.TOTAL_PRICE, Decimal("0.00")),
        (FieldType.DELIVERY_LOCATION, "Almoxarifado"),
        (FieldType.RECEIPT_DEADLINE, "5 dias"),
        (FieldType.PAYMENT_DEADLINE, "30 dias"),
    ],
)
def test_field_value_accepts_non_empty_finite_values(
    field_type: FieldType, value: object
) -> None:
    field_value = _field_value(field_type, value)

    assert field_value.value is not None


@pytest.mark.parametrize("value", [True, False, "10", 0, -1])
def test_quantity_rejects_bool_string_zero_and_negative(value: object) -> None:
    with pytest.raises(ValidationError, match="número positivo"):
        _field_value(FieldType.QUANTITY, value)


def test_quantity_accepts_positive_number_without_unit() -> None:
    field_value = _field_value(FieldType.QUANTITY, 10)

    assert field_value.value == 10
    assert field_value.unit is None


@pytest.mark.parametrize("value", [True, False, "texto não numérico", -1])
def test_money_rejects_bool_non_numeric_text_and_negative(value: object) -> None:
    with pytest.raises(ValidationError):
        _field_value(FieldType.UNIT_PRICE, value)


@pytest.mark.parametrize("field_type", [FieldType.UNIT_PRICE, FieldType.TOTAL_PRICE])
def test_money_is_decimal_and_accepts_zero(field_type: FieldType) -> None:
    field_value = _field_value(field_type, "0.00")

    assert field_value.value == Decimal("0.00")
    assert isinstance(field_value.value, Decimal)
    dumped = json.loads(field_value.model_dump_json())
    assert Decimal(str(dumped["value"])) == Decimal("0.00")
    json.dumps(field_value.model_json_schema())


def test_between_requires_exactly_two_values_and_valid_order() -> None:
    assert _requirement(RequirementOperator.BETWEEN, [1, 2]).value == [1, 2]
    assert _requirement(RequirementOperator.BETWEEN, (1, 2)).value == [1, 2]
    assert _requirement(RequirementOperator.BETWEEN, ["A", "Z"]).value == ["A", "Z"]
    assert _requirement(
        RequirementOperator.BETWEEN,
        [date(2025, 1, 1), date(2025, 1, 2)],
    ).value == [date(2025, 1, 1), date(2025, 1, 2)]
    for value in ([1], [1, 2, 3], 1):
        with pytest.raises(ValidationError, match="BETWEEN"):
            _requirement(RequirementOperator.BETWEEN, value)
    for value in (set((1, 2)), frozenset((1, 2))):
        with pytest.raises(ValidationError, match="coleção ordenada"):
            _requirement(RequirementOperator.BETWEEN, value)
    for value in ([True, 2], ["1", 2], [2, 1], ["   ", "Z"]):
        with pytest.raises(ValidationError, match="BETWEEN"):
            _requirement(RequirementOperator.BETWEEN, value)
    for value in ([nan, 2], [1, inf], [Decimal("NaN"), 2]):
        with pytest.raises(ValidationError, match="não finitos"):
            _requirement(RequirementOperator.BETWEEN, value)


def test_comparison_operators_require_finite_number_or_date() -> None:
    operators = (
        RequirementOperator.GREATER_THAN,
        RequirementOperator.GREATER_THAN_OR_EQUAL,
        RequirementOperator.LESS_THAN,
        RequirementOperator.LESS_THAN_OR_EQUAL,
    )
    for operator in operators:
        assert _requirement(operator, 1).value == 1
        assert _requirement(operator, date(2025, 1, 1)).value == date(2025, 1, 1)
        for value in (True, "1", nan, inf, -inf):
            with pytest.raises(ValidationError, match="numérico finito"):
                _requirement(operator, value)


def test_contains_requires_non_empty_string() -> None:
    assert _requirement(RequirementOperator.CONTAINS, "Notebook").value == "Notebook"
    for value in (1, "", "   ", ["Notebook"]):
        with pytest.raises(ValidationError, match="string não vazia"):
            _requirement(RequirementOperator.CONTAINS, value)


@pytest.mark.parametrize(
    "operator",
    [RequirementOperator.EQUAL, RequirementOperator.NOT_EQUAL],
)
def test_equality_accepts_any_valid_scalar(operator: RequirementOperator) -> None:
    for value in (True, False, "texto", 1, Decimal("1.2"), date(2025, 1, 1)):
        assert _requirement(operator, value).value == value
    with pytest.raises(ValidationError, match="escalar válido"):
        _requirement(operator, [1, 2])
    for value in ("", "   ", nan, inf, -inf, Decimal("NaN")):
        with pytest.raises(ValidationError, match="escalar válido"):
            _requirement(operator, value)


def test_in_requires_non_empty_collection_of_scalars() -> None:
    assert _requirement(RequirementOperator.IN, ["A", True, 1]).value == ["A", True, 1]
    assert _requirement(RequirementOperator.IN, ("A", "B")).value == ["A", "B"]
    assert set(_requirement(RequirementOperator.IN, {"A", "B"}).value) == {"A", "B"}
    assert set(_requirement(RequirementOperator.IN, frozenset({"A", "B"})).value) == {
        "A",
        "B",
    }
    assert _requirement(RequirementOperator.IN, [date(2025, 1, 1)]).value == [
        date(2025, 1, 1)
    ]
    for value in ([], "A"):
        with pytest.raises(ValidationError, match="IN"):
            _requirement(RequirementOperator.IN, value)
    for value in ([""], ["   "], {"   "}, frozenset({"   "})):
        with pytest.raises(ValidationError):
            _requirement(RequirementOperator.IN, value)
    with pytest.raises(ValidationError, match="escalares"):
        _requirement(RequirementOperator.IN, [[1]])
    for value in ([nan], [inf], [-inf], [Decimal("Infinity")]):
        with pytest.raises(ValidationError, match="não finitos"):
            _requirement(RequirementOperator.IN, value)


def test_exists_requires_boolean() -> None:
    assert _requirement(RequirementOperator.EXISTS, True).value is True
    for value in (1, 0, "true", [True]):
        with pytest.raises(ValidationError, match="EXISTS"):
            _requirement(RequirementOperator.EXISTS, value)


def test_duplicate_document_id_is_rejected(present_process: ProcurementProcess) -> None:
    data = present_process.model_dump(mode="json")
    data["documents"].append(copy.deepcopy(data["documents"][0]))

    with pytest.raises(ValidationError, match="ID de documento duplicado.*tr-1"):
        ProcurementProcess.model_validate(data)


def test_duplicate_block_id_is_rejected(present_process: ProcurementProcess) -> None:
    data = present_process.model_dump(mode="json")
    block = copy.deepcopy(data["documents"][0]["sections"][0]["blocks"][0])
    data["documents"][0]["sections"][0]["blocks"].append(block)

    with pytest.raises(ValidationError, match="ID de bloco duplicado.*b-obj-tbl-1"):
        ProcurementProcess.model_validate(data)


def test_duplicate_item_id_is_rejected_within_document(
    present_process: ProcurementProcess,
) -> None:
    data = present_process.model_dump(mode="json")
    data["documents"][0]["items"].append(copy.deepcopy(data["documents"][0]["items"][0]))

    with pytest.raises(ValidationError, match="ID de item duplicado.*item-1"):
        ProcurementProcess.model_validate(data)


def test_item_id_references_are_valid_for_all_entities(
    present_process: ProcurementProcess,
) -> None:
    data = present_process.model_dump(mode="json")
    document = data["documents"][0]
    evidence = {
        "document_id": "tr-1",
        "page": 1,
        "block_id": "b-obj-tbl-1",
        "quote": "Notebook",
    }
    document["items"][0]["requirements"] = [
        {
            "attribute": "marca",
            "operator": "EQUAL",
            "value": True,
            "item_id": "item-1",
            "evidence": [evidence],
        }
    ]
    document["field_values"] = [
        {
            "field_type": "DELIVERY_DEADLINE",
            "value": "10 dias",
            "item_id": "item-1",
            "evidence": [evidence],
        }
    ]
    document["requirements"] = [
        {
            "attribute": "cor",
            "operator": "EQUAL",
            "value": "preto",
            "item_id": "item-1",
            "evidence": [evidence],
        }
    ]
    data["findings"] = [
        {
            "rule_id": "RULE-X",
            "severity": "INFO",
            "message": "revisar item",
            "item_id": "item-1",
            "evidence": [evidence],
        }
    ]

    process = ProcurementProcess.model_validate(data)

    assert process.documents[0].items[0].requirements[0].item_id == "item-1"
    assert process.documents[0].field_values[0].item_id == "item-1"
    assert process.documents[0].requirements[0].item_id == "item-1"
    assert process.findings[0].item_id == "item-1"


@pytest.mark.parametrize("entity", ["field_values", "requirements"])
def test_nested_item_id_must_match_parent(
    present_process: ProcurementProcess, entity: str
) -> None:
    data = present_process.model_dump(mode="json")
    item = data["documents"][0]["items"][0]
    if entity == "field_values":
        item[entity][0]["item_id"] = "item-2"
    else:
        item[entity] = [
            {
                "attribute": "cor",
                "operator": "EQUAL",
                "value": "preto",
                "item_id": "item-2",
                "evidence": [EVIDENCE | {"document_id": "tr-1", "block_id": "b-obj-tbl-1", "quote": "Notebook"}],
            }
        ]

    with pytest.raises(ValidationError, match=r"item-1.*item-2|item-2.*item-1"):
        ProcurementProcess.model_validate(data)


@pytest.mark.parametrize("entity", ["field_values", "requirements"])
def test_document_level_item_id_must_reference_document_item(
    present_process: ProcurementProcess, entity: str
) -> None:
    data = present_process.model_dump(mode="json")
    value = {
        "item_id": "item-inexistente",
        "evidence": [
            {
                "document_id": "tr-1",
                "page": 1,
                "block_id": "b-obj-tbl-1",
                "quote": "Notebook",
            }
        ],
    }
    if entity == "field_values":
        data["documents"][0][entity] = [
            {"field_type": "DELIVERY_DEADLINE", "value": "10 dias", **value}
        ]
    else:
        data["documents"][0][entity] = [
            {
                "attribute": "cor",
                "operator": "EQUAL",
                "value": "preto",
                **value,
            }
        ]

    with pytest.raises(ValidationError, match="item-inexistente"):
        ProcurementProcess.model_validate(data)


def test_finding_item_id_must_reference_item_in_evidence_documents(
    present_process: ProcurementProcess,
) -> None:
    data = present_process.model_dump(mode="json")
    data["findings"] = [
        {
            "rule_id": "RULE-X",
            "severity": "INFO",
            "message": "revisar item",
            "item_id": "item-inexistente",
            "evidence": [
                {
                    "document_id": "tr-1",
                    "page": 1,
                    "block_id": "b-obj-tbl-1",
                    "quote": "Notebook",
                }
            ],
        }
    ]

    with pytest.raises(ValidationError, match="item-inexistente.*tr-1"):
        ProcurementProcess.model_validate(data)
