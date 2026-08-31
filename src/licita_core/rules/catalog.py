"""Catálogo versionado das regras do TR Linter determinístico.

Registra os 8 controles (6 NORMATIVE e 2 ADVISORY) da fatia M1 para compras municipais.
"""

from licita_core.rules.annex_integrity import AnnexIntegrityRule
from licita_core.rules.attribute_contradiction import AttributeContradictionRule
from licita_core.rules.base import Rule
from licita_core.rules.delivery_deadline import DeliveryDeadlineRule
from licita_core.rules.mandatory_elements import MandatoryElementsRule
from licita_core.rules.quantity_missing import QuantityMissingRule
from licita_core.rules.receipt_rules import ReceiptRulesRule
from licita_core.rules.verifiable_requirement import VerifiableRequirementRule
from licita_core.rules.warranty_contradiction import WarrantyContradictionRule

_CATALOG: list[Rule] = [
    MandatoryElementsRule(),
    QuantityMissingRule(),
    DeliveryDeadlineRule(),
    WarrantyContradictionRule(),
    ReceiptRulesRule(),
    AnnexIntegrityRule(),
    AttributeContradictionRule(),
    VerifiableRequirementRule(),
]


def get_catalog() -> list[Rule]:
    """Retorna a lista de todas as regras registradas no catálogo."""
    return list(_CATALOG)