"""Catálogo versionado das regras do TR Linter determinístico.

Vertical slice mínimo: apenas RULE-002 está registrada neste momento.
"""

from licita_core.rules.base import Rule
from licita_core.rules.quantity_missing import QuantityMissingRule

_CATALOG: list[Rule] = [
    QuantityMissingRule(),
]


def get_catalog() -> list[Rule]:
    """Retorna a lista atual de regras registradas."""
    return list(_CATALOG)