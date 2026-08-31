"""Pacote de regras do TR Linter determinístico."""

from licita_core.rules.annex_integrity import AnnexIntegrityRule
from licita_core.rules.attribute_contradiction import AttributeContradictionRule
from licita_core.rules.base import Rule, RuleContext
from licita_core.rules.catalog import get_catalog
from licita_core.rules.delivery_deadline import DeliveryDeadlineRule
from licita_core.rules.mandatory_elements import MandatoryElementsRule
from licita_core.rules.quantity_missing import QuantityMissingRule
from licita_core.rules.receipt_rules import ReceiptRulesRule
from licita_core.rules.verifiable_requirement import VerifiableRequirementRule
from licita_core.rules.warranty_contradiction import WarrantyContradictionRule

__all__ = [
    "AnnexIntegrityRule",
    "AttributeContradictionRule",
    "DeliveryDeadlineRule",
    "MandatoryElementsRule",
    "QuantityMissingRule",
    "ReceiptRulesRule",
    "Rule",
    "RuleContext",
    "VerifiableRequirementRule",
    "WarrantyContradictionRule",
    "get_catalog",
]