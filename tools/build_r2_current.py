"""Constrói os cinco payloads manuais da R2 a partir do corpus policy 8.

Os fatos normalizados ficam em ``r2/annotations.manual.json``. Este gerador
apenas reabre os documentos, resolve cada ``block_id`` e materializa o schema;
ele não descobre nem infere campos automaticamente.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from licita_core.r2_skeleton import esboco_documento
from licita_core.schema import (
    Document,
    DocumentType,
    Evidence,
    FieldType,
    FieldValue,
    Item,
    ProcurementProcess,
    Requirement,
    RequirementOperator,
)

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CATALOGO_DOCUMENTOS = CORPUS / "catalogo" / "documentos.jsonl"
ANOTACOES = ROOT / "r2" / "annotations.manual.json"
DESTINO = ROOT / "r2" / "data"
MANIFESTO = ROOT / "r2" / "manifest.json"


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _catalogo() -> dict[tuple[str, str], dict[str, Any]]:
    registros = {}
    for linha in CATALOGO_DOCUMENTOS.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        registro = json.loads(linha)
        registros[(registro["processo_id"], registro["papel"])] = registro
    return registros


def _evidencia(documento: Document, anotacao: dict[str, Any]) -> Evidence:
    blocos = {
        bloco.id: bloco
        for secao in documento.sections
        for bloco in secao.blocks
    }
    bloco_id = anotacao["block_id"]
    if bloco_id not in blocos:
        raise ValueError(f"{documento.id}: bloco manual inexistente: {bloco_id}")
    bloco = blocos[bloco_id]
    return Evidence(
        document_id=documento.id,
        page=anotacao["page"],
        block_id=bloco.id,
        quote=bloco.text,
        attr=anotacao.get("field_type") or anotacao.get("attribute"),
    )


def _materializar_documento(
    esboco: Document, anotacoes: list[dict[str, Any]]
) -> Document:
    campos_documento: list[FieldValue] = []
    requisitos_documento: list[Requirement] = []
    itens: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"description": None, "evidence": [], "fields": [], "requirements": []}
    )

    for anotacao in anotacoes:
        evidencia = _evidencia(esboco, anotacao)
        item_id = anotacao.get("item_id")
        if "field_type" in anotacao:
            valor = FieldValue(
                field_type=FieldType(anotacao["field_type"]),
                value=anotacao["value"],
                unit=anotacao.get("unit"),
                item_id=item_id,
                evidence=[evidencia],
            )
            destino = campos_documento if item_id is None else itens[item_id]["fields"]
        else:
            valor = Requirement(
                attribute=anotacao["attribute"],
                operator=RequirementOperator(anotacao["operator"]),
                value=anotacao["value"],
                unit=anotacao.get("unit"),
                item_id=item_id,
                evidence=[evidencia],
            )
            destino = (
                requisitos_documento
                if item_id is None
                else itens[item_id]["requirements"]
            )
        destino.append(valor)

        if item_id is not None:
            item = itens[item_id]
            item["description"] = anotacao.get("description") or item["description"]
            if not item["evidence"]:
                item["evidence"].append(evidencia)

    itens_materializados = [
        Item(
            id=item_id,
            description=conteudo["description"],
            field_values=conteudo["fields"],
            requirements=conteudo["requirements"],
            evidence=conteudo["evidence"],
        )
        for item_id, conteudo in sorted(itens.items())
    ]
    return esboco.model_copy(
        update={
            "items": itens_materializados,
            "field_values": campos_documento,
            "requirements": requisitos_documento,
        }
    )


def construir() -> dict[str, Any]:
    especificacao = json.loads(ANOTACOES.read_text(encoding="utf-8"))
    catalogo = _catalogo()
    DESTINO.mkdir(parents=True, exist_ok=True)
    manifestos: list[dict[str, Any]] = []

    ids_esperados = {processo["process_id"] for processo in especificacao["processes"]}
    for antigo in DESTINO.glob("*.json"):
        if antigo.stem not in ids_esperados:
            antigo.unlink()

    for processo in especificacao["processes"]:
        processo_id = processo["process_id"]
        por_documento: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for anotacao in processo["annotations"]:
            por_documento[anotacao["document"]].append(anotacao)

        documentos: list[Document] = []
        fontes: list[dict[str, Any]] = []
        for papel in processo["documents"]:
            registro = catalogo[(processo_id, papel)]
            caminho = CORPUS / registro["arquivo"]
            hash_original = _sha256(caminho)
            if hash_original != registro["sha256"]:
                raise ValueError(
                    f"{processo_id}/{papel}: SHA-256 do original diverge do catálogo"
                )
            documento_id = f"{processo_id}:{papel.lower()}"
            esboco = esboco_documento(
                caminho,
                document_id=documento_id,
                document_type=DocumentType(papel),
            )
            documentos.append(
                _materializar_documento(esboco, por_documento.get(papel, []))
            )
            fontes.append(
                {
                    "papel": papel,
                    "documento_id_catalogo": registro["documento_id"],
                    "arquivo": registro["arquivo"],
                    "sha256": hash_original,
                }
            )

        payload = ProcurementProcess(
            id=processo_id,
            documents=documentos,
            findings=[],
        )
        serializado = (
            json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n"
        )
        destino = DESTINO / f"{processo_id}.json"
        destino.write_text(serializado, encoding="utf-8")
        manifestos.append(
            {
                "processo_id": processo_id,
                "annotation_provenance": "manual",
                "annotation_count": len(processo["annotations"]),
                "artifact": str(destino.relative_to(ROOT)),
                "artifact_sha256": _sha256(destino),
                "documents": fontes,
            }
        )

    manifesto = {
        "schema_version": "0.1.0",
        "collection_policy_version": especificacao["collection_policy_version"],
        "processes": manifestos,
    }
    MANIFESTO.write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifesto


if __name__ == "__main__":
    resultado = construir()
    print(f"R2: {len(resultado['processes'])} processos materializados em {DESTINO}")
