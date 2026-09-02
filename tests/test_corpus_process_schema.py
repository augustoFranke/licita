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


def test_esferas_da_uniao_aos_municipios_sao_aceitas(
    validator: Draft202012Validator,
) -> None:
    """A esfera deixou de restringir o perfil: F/E/D/M validam."""
    payload = json.loads(
        (EXEMPLOS / "corpus_process.supported.json").read_text(encoding="utf-8")
    )
    for esfera in ("F", "E", "D", "M"):
        payload["orgao"]["esfera"] = esfera
        validator.validate(payload)


def test_esfera_desconhecida_ou_ausente_e_rejeitada(
    validator: Draft202012Validator,
) -> None:
    """A esfera continua fechada e obrigatória."""
    payload = json.loads(
        (EXEMPLOS / "corpus_process.supported.json").read_text(encoding="utf-8")
    )
    for esfera in ("X", "", "municipal"):
        payload["orgao"]["esfera"] = esfera
        with pytest.raises(ValidationError):
            validator.validate(payload)

    del payload["orgao"]["esfera"]
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


def test_policy_nova_exige_quatro_papeis_e_contrato_vinculado(
    validator: Draft202012Validator,
) -> None:
    payload = json.loads(
        (EXEMPLOS / "corpus_process.supported.json").read_text(encoding="utf-8")
    )
    payload["collection_policy_version"] = "6-cadeia-completa-todas-esferas"
    payload["cadeia"]["EDITAL"] = ["12345678000199-1-000001-2025#edital-03"]
    payload["cadeia"]["CONTRATO"] = ["12345678000199-1-000001-2025#contrato-01"]
    payload["documentos"] += [
        "12345678000199-1-000001-2025#edital-03",
        "12345678000199-1-000001-2025#contrato-01",
    ]
    payload["contratos"] = [
        {
            "numero_controle_pncp": "12345678000199-2-000001/2025",
            "numero_controle_pncp_compra": payload["numero_controle_pncp"],
            "criterio_vinculo": "numeroControlePncpCompra",
        }
    ]
    validator.validate(payload)

    sem_contrato = copy.deepcopy(payload)
    del sem_contrato["contratos"]
    with pytest.raises(ValidationError):
        validator.validate(sem_contrato)

    edital_vazio = copy.deepcopy(payload)
    edital_vazio["cadeia"]["EDITAL"] = []
    with pytest.raises(ValidationError):
        validator.validate(edital_vazio)
