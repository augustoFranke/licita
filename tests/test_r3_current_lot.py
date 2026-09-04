import hashlib
import json
from pathlib import Path

from licita_ingest.extractor import extract_document

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
ANCHORS = ROOT / "r3" / "anchors.manual.json"
POLICY = "8-cadeia-completa-documentos-utilizaveis"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_dez_processos_do_lote_reabrem_todos_os_trechos_da_r3() -> None:
    specification = json.loads(ANCHORS.read_text(encoding="utf-8"))
    required = set(specification["required_categories"])
    catalog_processes = json.loads(
        (CORPUS / "catalogo" / "processos.json").read_text(encoding="utf-8")
    )
    processes_by_id = {
        process["processo_id"]: process for process in catalog_processes
    }
    documents = [
        json.loads(line)
        for line in (CORPUS / "catalogo" / "documentos.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    documents_by_process_role = {
        (document["processo_id"], document["papel"]): document
        for document in documents
    }
    extracted = {}
    reopened = 0
    total = 0

    assert specification["collection_policy_version"] == POLICY
    assert len(specification["processes"]) == 10

    for process_specification in specification["processes"]:
        process_id = process_specification["process_id"]
        process = processes_by_id[process_id]
        assert process["collection_policy_version"] == POLICY
        assert all(
            len(process["cadeia"][role]) == 1
            for role in ("ETP", "TR", "EDITAL", "CONTRATO")
        )
        assert {
            anchor["category"] for anchor in process_specification["anchors"]
        } == required

        for anchor in process_specification["anchors"]:
            total += 1
            role = anchor["document"]
            catalog_document = documents_by_process_role[(process_id, role)]
            path = CORPUS / catalog_document["arquivo"]
            assert _sha256(path) == catalog_document["sha256"]

            key = (process_id, role)
            if key not in extracted:
                extracted[key] = extract_document(
                    path, document_id=f"{process_id}:{role.lower()}"
                )
            block = extracted[key].get_block(anchor["block_id"])
            assert block is not None
            assert block.page == anchor["page"]
            assert anchor["quote"] in block.text
            reopened += 1

    assert total == 40
    assert reopened / total >= 0.95
