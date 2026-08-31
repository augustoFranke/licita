"""Contrato externo de escopo do catálogo municipal."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

RAIZ = Path(__file__).parent.parent
SCHEMA_PATH = RAIZ / "schemas" / "corpus_process.v0.1.0.json"
EXEMPLOS = RAIZ / "schemas" / "examples"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize(
    "nome",
    ["corpus_process.supported.json", "corpus_process.out_of_scope.json"],
)
def test_exemplos_municipais_validam(
    validator: Draft202012Validator, nome: str
) -> None:
    payload = json.loads((EXEMPLOS / nome).read_text(encoding="utf-8"))
    validator.validate(payload)


def test_catalogo_real_valida_quando_disponivel(
    validator: Draft202012Validator,
) -> None:
    caminho = RAIZ / "corpus" / "catalogo" / "processos.json"
    if not caminho.exists():
        pytest.skip("catálogo real não está presente")
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    assert len(processos) >= 15
    for processo in processos:
        validator.validate(processo)


def test_esfera_nao_municipal_e_rejeitada(
    validator: Draft202012Validator,
) -> None:
    payload = json.loads(
        (EXEMPLOS / "corpus_process.supported.json").read_text(encoding="utf-8")
    )
    payload["orgao"]["esfera"] = "F"
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_scope_status_precisa_concordar_com_perfil(
    validator: Draft202012Validator,
) -> None:
    payload = json.loads(
        (EXEMPLOS / "corpus_process.supported.json").read_text(encoding="utf-8")
    )
    inconsistente = copy.deepcopy(payload)
    inconsistente["scope_status"] = "OUT_OF_SCOPE"
    with pytest.raises(ValidationError):
        validator.validate(inconsistente)
