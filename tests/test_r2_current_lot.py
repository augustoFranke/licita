import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from licita_core.r2_annotations import validate_annotations
from licita_core.schema import DocumentType, FieldType, ProcurementProcess

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "r2" / "data"
MANIFEST = ROOT / "r2" / "manifest.json"
PROCESS_SCHEMA = ROOT / "schemas" / "procurement_process.v0.1.0.json"
CATALOG_PROCESSES = ROOT / "corpus" / "catalogo" / "processos.json"
CATALOG_DOCUMENTS = ROOT / "corpus" / "catalogo" / "documentos.jsonl"
POLICY = "8-cadeia-completa-documentos-utilizaveis"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cinco_processos_reais_do_lote_fecham_r2() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    artifacts = sorted(DATA.glob("*.json"))
    catalog_processes = json.loads(CATALOG_PROCESSES.read_text(encoding="utf-8"))
    catalog_by_id = {process["processo_id"]: process for process in catalog_processes}
    catalog_documents = {
        document["documento_id"]: document
        for line in CATALOG_DOCUMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for document in [json.loads(line)]
    }
    schema_validator = Draft202012Validator(
        json.loads(PROCESS_SCHEMA.read_text(encoding="utf-8"))
    )

    assert manifest["collection_policy_version"] == POLICY
    assert len(manifest["processes"]) == 5
    assert len(artifacts) == 5

    for entry in manifest["processes"]:
        process_id = entry["processo_id"]
        artifact = ROOT / entry["artifact"]
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        process = ProcurementProcess.model_validate(payload)
        schema_validator.validate(payload)

        assert artifact in artifacts
        assert entry["annotation_provenance"] == "manual"
        assert entry["annotation_count"] > 0
        assert entry["artifact_sha256"] == _sha256(artifact)
        assert process.id == process_id
        assert {document.type for document in process.documents} == {
            DocumentType.ETP,
            DocumentType.TR,
            DocumentType.EDITAL,
            DocumentType.CONTRATO,
        }

        catalog_process = catalog_by_id[process_id]
        assert catalog_process["collection_policy_version"] == POLICY
        assert all(
            len(catalog_process["cadeia"][role]) == 1
            for role in ("ETP", "TR", "EDITAL", "CONTRATO")
        )
        assert len(entry["documents"]) == 4
        for source in entry["documents"]:
            catalog_document = catalog_documents[source["documento_id_catalogo"]]
            assert source["sha256"] == catalog_document["sha256"]

        quantities = [
            value
            for document in process.documents
            for item in document.items
            for value in item.field_values
            if value.field_type is FieldType.QUANTITY
        ]
        requirements = [
            requirement
            for document in process.documents
            for item in document.items
            for requirement in item.requirements
        ]
        assert quantities and all(value.unit for value in quantities)
        assert requirements

    coverage = validate_annotations(artifacts).to_dict()
    assert coverage["validation"]["valid"] is True
    assert coverage["validation"]["validated_files"] == 5
    assert coverage["coverage"]["totals"]["v1_fields"]["unrepresented"] == []
