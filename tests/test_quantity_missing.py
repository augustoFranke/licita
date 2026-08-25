import pytest

from licita_core.rules.base import RuleContext
from licita_core.rules.quantity_missing import QuantityMissingRule
from licita_core.schema import DocumentType, ProcurementProcess, Severity

TR_DOC_ID = "tr-1"


def _rule() -> QuantityMissingRule:
    return QuantityMissingRule()


def _context(proc: ProcurementProcess) -> RuleContext:
    return RuleContext(process=proc, target_document_id=TR_DOC_ID)


def test_missing_quantity_generates_exactly_one_finding(
    missing_process: ProcurementProcess,
) -> None:
    findings = _rule().detect(_context(missing_process))
    assert len(findings) == 1


def test_present_quantity_generates_no_finding(
    present_process: ProcurementProcess,
) -> None:
    findings = _rule().detect(_context(present_process))
    assert findings == []


def test_finding_shape(
    missing_process: ProcurementProcess,
) -> None:
    (finding,) = _rule().detect(_context(missing_process))
    assert finding.rule_id == "RULE-002"
    assert finding.severity == Severity.HIGH
    assert finding.item_id == "item-1"
    assert "item-1" in finding.message
    assert "unidade" not in finding.message.lower()
    assert finding.attrs == {"falta": "quantidade"}
    assert len(finding.evidence) >= 1


def test_rule_002_description_is_only_about_missing_quantity() -> None:
    rule = _rule()
    assert "quantidade" in rule.description.lower()
    assert "unidade" not in rule.description.lower()


def test_finding_evidence_resolves_to_real_block(
    missing_process: ProcurementProcess,
) -> None:
    (finding,) = _rule().detect(_context(missing_process))
    documents = {document.id: document for document in missing_process.documents}

    for evidence in finding.evidence:
        document = documents[evidence.document_id]
        blocks = {
            block.id: block
            for section in document.sections
            for block in section.blocks
        }
        block = blocks[evidence.block_id]
        assert block.id == evidence.block_id
        assert block.text == evidence.quote
        assert evidence.page >= 1


def test_rule_does_not_apply_for_non_tr(
    present_process: ProcurementProcess,
) -> None:
    edital = present_process.model_copy(
        update={"documents": [present_process.documents[0].model_copy(
            update={"id": "edital-1", "type": DocumentType.EDITAL}
        )]}
    )
    context = RuleContext(process=edital, target_document_id="edital-1")
    assert _rule().applies(context) is False
    assert _rule().detect(context) == []


def test_rule_does_not_apply_when_target_absent(
    present_process: ProcurementProcess,
) -> None:
    context = RuleContext(process=present_process, target_document_id="inexistente")
    assert _rule().applies(context) is False
    assert _rule().detect(context) == []


def test_two_items_without_quantity_generate_two_findings(
    missing_process: ProcurementProcess,
) -> None:
    data = missing_process.model_dump(mode="json")
    second_item = data["documents"][0]["items"][0].copy()
    second_item["id"] = "item-2"
    data["documents"][0]["items"].append(second_item)
    process = ProcurementProcess.model_validate(data)

    findings = _rule().detect(_context(process))

    assert len(findings) == 2
    assert {finding.item_id for finding in findings} == {"item-1", "item-2"}


def test_one_item_with_quantity_only_flags_the_other(
    missing_process: ProcurementProcess,
) -> None:
    data = missing_process.model_dump(mode="json")
    data["documents"][0]["sections"][0]["blocks"].extend(
        [
            {
                "id": "b-obj-mouse",
                "type": "TABLE_CELL",
                "text": "Mouse",
            },
            {
                "id": "b-obj-mouse-qtd",
                "type": "TABLE_CELL",
                "text": "Quantidade: 10",
            },
        ]
    )
    data["documents"][0]["items"].append(
        {
            "id": "item-2",
            "description": "Mouse",
            "field_values": [
                {
                    "field_type": "QUANTITY",
                    "value": 10,
                    "item_id": "item-2",
                    "evidence": [
                        {
                            "document_id": TR_DOC_ID,
                            "page": 1,
                            "block_id": "b-obj-mouse-qtd",
                            "quote": "Quantidade: 10",
                        }
                    ],
                }
            ],
            "requirements": [],
            "evidence": [
                {
                    "document_id": TR_DOC_ID,
                    "page": 1,
                    "block_id": "b-obj-mouse",
                    "quote": "Mouse",
                }
            ],
        }
    )
    process = ProcurementProcess.model_validate(data)

    findings = _rule().detect(_context(process))

    assert len(findings) == 1
    assert findings[0].item_id == "item-1"