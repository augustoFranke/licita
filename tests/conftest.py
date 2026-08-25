import json
from pathlib import Path

import pytest

from licita_core.schema import ProcurementProcess

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> ProcurementProcess:
    return ProcurementProcess.model_validate(
        json.loads((FIXTURES / name).read_text())
    )


@pytest.fixture
def missing_process() -> ProcurementProcess:
    return _load("quantity_missing.json")


@pytest.fixture
def present_process() -> ProcurementProcess:
    return _load("quantity_present.json")