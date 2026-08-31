import re

from licita_core.rules.catalog import get_catalog
from licita_core.schema import FindingCategory, Severity


def test_catalog_has_all_8_rules() -> None:
    catalog = get_catalog()
    assert len(catalog) == 8

    expected_ids = [
        "RULE-001",
        "RULE-002",
        "RULE-003",
        "RULE-004",
        "RULE-005",
        "RULE-006",
        "RULE-007",
        "ADVISORY-008",
    ]
    catalog_ids = [rule.rule_id for rule in catalog]
    assert catalog_ids == expected_ids


def test_rule_ids_are_unique() -> None:
    catalog = get_catalog()
    ids = [rule.rule_id for rule in catalog]
    assert len(ids) == len(set(ids))


def test_every_rule_has_required_metadata() -> None:
    for rule in get_catalog():
        assert rule.version
        assert rule.scope
        assert rule.legal_basis
        assert rule.severity
        assert rule.rule_class in ("NORMATIVE", "ADVISORY")
        assert re.search(r"\b(?:IN|AGU)\b", rule.legal_basis, re.IGNORECASE) is None

        if rule.rule_class == "NORMATIVE":
            assert "Lei nº 14.133/2021" in rule.legal_basis
            assert rule.severity == Severity.HIGH
        else:
            assert "não se aplica" in rule.legal_basis.lower()
            assert rule.severity == Severity.MEDIUM


def test_rule_classes_and_severities() -> None:
    catalog = {rule.rule_id: rule for rule in get_catalog()}

    # 6 NORMATIVE rules
    for norm_id in ["RULE-001", "RULE-002", "RULE-003", "RULE-004", "RULE-005", "RULE-007"]:
        r = catalog[norm_id]
        assert r.rule_class == "NORMATIVE"
        assert r.severity == Severity.HIGH

    # 2 ADVISORY rules
    assert catalog["RULE-006"].rule_class == "ADVISORY"
    assert catalog["RULE-006"].severity == Severity.MEDIUM

    assert catalog["ADVISORY-008"].rule_class == "ADVISORY"
    assert catalog["ADVISORY-008"].severity == Severity.MEDIUM