"""Constrói anotações golden R4 a partir do formato achatado do worksheet.

Uma anotação achatada tem: process, document (ETP/TR), block_id, page, item
(nº do lote), field_type (um dos 9 FieldType ou um atributo livre), value, unit.

Regras de conversão:
- field_type que casa um FieldType do schema  -> FieldValue.
- qualquer outro texto                         -> Requirement (attribute livre).
- operador do Requirement: EQUAL por padrão; >=,<=,>,< no início do valor
  viram o operador correspondente.
- a Evidence.quote é resolvida contra o texto real do bloco (substring literal),
  então nenhuma citação é inventada; se o bloco não existir, falha explícita.
- item "01" -> Item.id "item-01" (o número é a chave que pareia ETP<->TR no R7).

Uso:
    uv run python tools/build_golden.py <flat.json> [--provenance assistant_annotated]
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

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
from licita_ingest.extractor import extract_document

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CATALOG = CORPUS / "catalogo" / "documentos.jsonl"
MANIFEST = ROOT / "r4" / "manifest.json"

FIELD_TYPES = {ft.value for ft in FieldType}
_OP = {">=": "GREATER_THAN_OR_EQUAL", "<=": "LESS_THAN_OR_EQUAL",
       ">": "GREATER_THAN", "<": "LESS_THAN"}


def _catalog() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[(str(r["processo_id"]), str(r["papel"]))] = r
    return out


def _num(text: str):
    """Converte '5.103,60' / '40' para Decimal; devolve o texto se não for número."""
    t = text.strip()
    for op in _OP:
        if t.startswith(op):
            t = t[len(op):].strip()
    limpo = re.sub(r"[^\d,.-]", "", t)
    if not limpo:
        return text.strip()
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        d = Decimal(limpo)
        return int(d) if d == d.to_integral_value() else d
    except InvalidOperation:
        return text.strip()


def _operator(value_text: str) -> RequirementOperator:
    v = value_text.strip()
    for op, name in _OP.items():
        if v.startswith(op):
            return RequirementOperator(name)
    return RequirementOperator.EQUAL


def _resolve_quote(block_text: str, hint: str) -> str:
    """Escolhe uma citação literal do bloco: a linha que contém o valor, ou o bloco."""
    alvo = hint.strip()
    for linha in block_text.splitlines():
        candidato = linha.strip()
        # linha curta demais (ex.: célula de tabela "40") não é evidência útil;
        # cai para o bloco inteiro, que é sempre substring de si mesmo.
        if alvo and alvo in linha and len(candidato) >= 12:
            return candidato
    return block_text.strip()


def _item_id(item: str | None) -> str | None:
    if not item:
        return None
    m = re.search(r"\d+", item)
    if not m:
        raise ValueError(
            f"Item '{item}' sem número: não pareia no R7. Use o nº do lote."
        )
    return f"item-{int(m.group()):02d}"


def build(flat_path: Path, provenance: str) -> None:
    data = json.loads(flat_path.read_text(encoding="utf-8"))
    annotations = data.get("annotations", data)
    catalog = _catalog()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    split_of = {p["processo_id"]: p["split"] for p in manifest["processes"]}

    by_process: dict[str, list[dict]] = {}
    for a in annotations:
        by_process.setdefault(a["process"], []).append(a)

    for pid, anns in by_process.items():
        # esqueletos ETP/TR com blocos reais (R3)
        docs: dict[str, Document] = {}
        block_index: dict[tuple[str, str], str] = {}  # (doc_id, block_id) -> text
        for papel in ("ETP", "TR"):
            if (pid, papel) not in catalog:
                continue
            path = CORPUS / catalog[(pid, papel)]["arquivo"]
            doc_id = f"{pid}:{papel.lower()}"
            skel = esboco_documento(path, document_id=doc_id, document_type=DocumentType(papel))
            docs[papel] = skel
            ext = extract_document(path, document_id=doc_id)
            # inclui células de tabela (children): são os blocos citáveis, iguais
            # aos que o esqueleto R2 guarda nas seções.
            for b in ext.iter_blocks(include_children=True):
                block_index[(doc_id, b.id)] = b.text

        # acumula field_values/requirements por (documento, item)
        doc_fields: dict[str, list[FieldValue]] = {p: [] for p in docs}
        doc_reqs: dict[str, list[Requirement]] = {p: [] for p in docs}
        items: dict[str, dict[str, dict]] = {p: {} for p in docs}  # item_id -> {fv:[],req:[],ev}

        for a in anns:
            papel = a["document"]
            if papel not in docs:
                raise ValueError(f"{pid}: documento {papel} não está no lote")
            doc_id = f"{pid}:{papel.lower()}"
            key = (doc_id, a["block_id"])
            if key not in block_index:
                raise ValueError(f"{pid}: bloco {a['block_id']} inexistente em {papel}")
            quote = _resolve_quote(block_index[key], str(a["value"]))
            ev = Evidence(document_id=doc_id, page=int(a["page"]),
                          block_id=a["block_id"], quote=quote)
            iid = _item_id(a.get("item"))
            ftype = str(a["field_type"]).strip()
            unit = (a.get("unit") or "").strip() or None

            if ftype.upper() in FIELD_TYPES:
                fv = FieldValue(field_type=FieldType(ftype.upper()),
                                value=_num(str(a["value"])), unit=unit,
                                item_id=iid, evidence=[ev])
                if iid:
                    items[papel].setdefault(iid, {"fv": [], "req": [], "ev": ev})
                    items[papel][iid]["fv"].append(fv)
                else:
                    doc_fields[papel].append(fv)
            else:
                req = Requirement(attribute=ftype, operator=_operator(str(a["value"])),
                                  value=_num(str(a["value"])), unit=unit,
                                  item_id=iid, evidence=[ev])
                if iid:
                    items[papel].setdefault(iid, {"fv": [], "req": [], "ev": ev})
                    items[papel][iid]["req"].append(req)
                else:
                    doc_reqs[papel].append(req)

        documents = []
        for papel, skel in docs.items():
            item_objs = [
                Item(id=iid, field_values=v["fv"], requirements=v["req"], evidence=[v["ev"]])
                for iid, v in sorted(items[papel].items())
            ]
            documents.append(Document(
                id=skel.id, type=skel.type, format=skel.format, title=skel.title,
                sections=skel.sections, items=item_objs,
                field_values=doc_fields[papel], requirements=doc_reqs[papel],
            ))

        proc = ProcurementProcess(id=pid, documents=documents, findings=[])
        proc = ProcurementProcess.model_validate(proc.model_dump(mode="json"))  # revalida

        split = split_of.get(pid, "dev")
        out = ROOT / "r4" / "data" / split / f"{pid}.json"
        out.write_text(json.dumps(proc.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        n_fv = sum(len(d.field_values) + sum(len(i.field_values) for i in d.items) for d in documents)
        n_rq = sum(len(d.requirements) + sum(len(i.requirements) for i in d.items) for d in documents)
        print(f"{pid} [{split}] -> {out.relative_to(ROOT)}  ({n_fv} campos, {n_rq} requisitos)")

        # provenance no manifesto
        for p in manifest["processes"]:
            if p["processo_id"] == pid:
                p["annotation_provenance"] = provenance
                p.pop("engine_agreement_pct", None)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("flat", type=Path)
    ap.add_argument("--provenance", default="assistant_annotated")
    args = ap.parse_args()
    build(args.flat, args.provenance)
