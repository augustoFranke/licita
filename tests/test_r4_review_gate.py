from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "r4" / "manifest.json"
REVIEW_DIR = ROOT / "r4" / "review"


def test_split_ativo_nao_usa_oraculo_gerado_pelo_motor() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert len(manifest["processes"]) == 10
    assert sum(
        process["total_values_and_requirements"]
        for process in manifest["processes"]
    ) >= 300
    assert all(
        process["annotation_provenance"] in {"manual", "assistant_annotated"}
        for process in manifest["processes"]
    )


def test_eval_e_um_holdout_limpo_e_congelado() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    holdout = manifest.get("evaluation_holdout", {})

    if holdout.get("status") != "CLEAN_FROZEN":
        pytest.skip(
            "R4 aguarda substituir os cinco processos de eval expostos ao benchmark R5"
        )

    assert manifest["split_frozen_at"]


def test_candidatos_de_reposicao_sao_cinco_e_nao_foram_expostos() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    holdout = manifest["evaluation_holdout"]
    candidates = holdout["replacement_candidates"]
    active_ids = {process["processo_id"] for process in manifest["processes"]}

    assert holdout["replacement_candidates_status"] == (
        "SOURCE_REOPENED_READING_A_PENDING"
    )
    assert len(candidates) == len(set(candidates)) == 5
    assert active_ids.isdisjoint(candidates)


def test_todos_os_processos_possuem_leitura_b_cega_e_adjudicada() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected_ids = {process["processo_id"] for process in manifest["processes"]}
    records = {}

    for path in REVIEW_DIR.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["process_id"]] = record

    missing = sorted(expected_ids - records.keys())
    if missing:
        pytest.skip(
            "R4 aguarda leitura B e adjudicação de "
            f"{len(missing)}/10 processos: {', '.join(missing)}"
        )

    assert records.keys() == expected_ids
    for process_id, record in records.items():
        assert record["reviewer_a"] != record["reviewer_b"], process_id
        assert record["blind_source_review"] is True, process_id
        assert record["status"] == "ADJUDICATED", process_id
        assert record["unresolved_policy_ambiguities"] == [], process_id
