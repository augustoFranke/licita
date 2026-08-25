from licita_core.rules.catalog import get_catalog
from licita_core.rules.quantity_missing import QuantityMissingRule


def test_single_rule_registered() -> None:
    catalog = get_catalog()
    assert len(catalog) == 1
    assert catalog[0].rule_id == "RULE-002"


def test_rule_ids_are_unique() -> None:
    catalog = get_catalog()
    ids = [rule.rule_id for rule in catalog]
    assert len(ids) == len(set(ids))


def test_every_rule_has_required_metadata() -> None:
    for rule in get_catalog():
        assert rule.version
        assert rule.scope
        assert rule.legal_basis
        assert any(source in rule.legal_basis for source in ("Lei", "IN", "AGU"))
        assert rule.severity


def test_rule_metadata_values() -> None:
    rule = QuantityMissingRule()
    assert rule.rule_id == "RULE-002"
    assert rule.severity.value == "HIGH"