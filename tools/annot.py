"""Utilitários de anotação aditiva do golden R4.

Duas operações, ambas para permitir adicionar campos (ex.: prazo de entrega,
garantia) a um processo já anotado sem perder o que já existe:

``export <pid>``  imprime as anotações atuais do golden no formato flat que o
                  ``build_golden.py`` consome. A evidência é reduzida a
                  (block_id, page); o quote é re-resolvido no rebuild.

``scan <pid> [papel ...]``  extrai ETP/TR/EDITAL e lista os blocos que casam
                  palavras de prazo/garantia/vigência, com block_id e página,
                  para a leitura ser focada.

Fluxo aditivo:
    uv run python tools/annot.py export <pid> > /tmp/<pid>.flat.json
    # editar o flat: acrescentar as linhas novas (prazo/garantia/edital)
    uv run python tools/annot.py scan <pid>        # achar block_id das linhas novas
    uv run python tools/build_golden.py /tmp/<pid>.flat.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from licita_core.schema import DocumentType, ProcurementProcess, RequirementOperator
from licita_ingest.extractor import extract_document

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CATALOG = CORPUS / "catalogo" / "documentos.jsonl"
GOLDEN_DIRS = (ROOT / "r4" / "data" / "dev", ROOT / "r4" / "data" / "eval")

_OP_PREFIX = {
    RequirementOperator.GREATER_THAN_OR_EQUAL: ">=",
    RequirementOperator.LESS_THAN_OR_EQUAL: "<=",
    RequirementOperator.GREATER_THAN: ">",
    RequirementOperator.LESS_THAN: "<",
}

# Palavras que sinalizam campos de nível documental ainda pouco anotados.
_KEYWORDS = {
    "DELIVERY_DEADLINE": re.compile(
        r"prazo\s+(de\s+)?(entrega|fornecimento|execu)", re.I),
    "WARRANTY_TERM": re.compile(
        r"garantia|assist[êe]ncia\s+t[ée]cnica|validade", re.I),
    "CONTRACT_TERM": re.compile(
        r"vig[êe]ncia|vigente|dura[çc][ãa]o\s+do\s+contrato", re.I),
    "PAYMENT_DEADLINE": re.compile(r"prazo\s+(de\s+)?pagamento|pagamento", re.I),
}


def _catalog() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[(str(r["processo_id"]), str(r["papel"]))] = r
    return out


def _golden_path(pid: str) -> Path:
    for d in GOLDEN_DIRS:
        p = d / f"{pid}.json"
        if p.exists():
            return p
    raise SystemExit(f"golden não encontrado para {pid}")


def _item_num(item_id: str) -> str | None:
    m = re.search(r"\d+", item_id or "")
    return m.group() if m else None


def export(pid: str) -> None:
    proc = ProcurementProcess.model_validate(
        json.loads(_golden_path(pid).read_text(encoding="utf-8")))
    rows: list[dict] = []

    def emit_fv(papel, item, fv):
        ev = fv.evidence[0]
        rows.append({"process": pid, "document": papel, "block_id": ev.block_id,
                     "page": ev.page, "item": item,
                     "field_type": fv.field_type.value,
                     "value": fv.value, "unit": fv.unit})

    def emit_req(papel, item, req):
        ev = req.evidence[0]
        prefix = _OP_PREFIX.get(req.operator, "")
        rows.append({"process": pid, "document": papel, "block_id": ev.block_id,
                     "page": ev.page, "item": item, "field_type": req.attribute,
                     "value": f"{prefix}{req.value}", "unit": req.unit})

    for doc in proc.documents:
        papel = doc.type.value
        for fv in doc.field_values:
            emit_fv(papel, None, fv)
        for req in doc.requirements:
            emit_req(papel, None, req)
        for it in doc.items:
            num = _item_num(it.id)
            for fv in it.field_values:
                emit_fv(papel, num, fv)
            for req in it.requirements:
                emit_req(papel, num, req)

    print(json.dumps({"annotations": rows}, ensure_ascii=False, indent=2, default=str))


_QUANTIFICADO = re.compile(
    r"\d+\s*\(?\s*[a-zçãéí ]*\)?\s*(dias?|meses|m[êe]s|anos?)", re.I)


def scan(pid: str, papeis: list[str], *, full: bool = False) -> None:
    catalog = _catalog()
    papeis = papeis or ["ETP", "TR", "EDITAL"]
    for papel in papeis:
        key = (pid, papel)
        if key not in catalog:
            print(f"\n### {papel}: ausente no catálogo", file=sys.stderr)
            continue
        path = CORPUS / catalog[key]["arquivo"]
        doc_id = f"{pid}:{papel.lower()}"
        ext = extract_document(path, document_id=doc_id)
        blocos = list(ext.iter_blocks(include_children=True))
        print(f"\n=== {papel}  ({len(blocos)} blocos)  {path.name} ===")
        for b in blocos:
            texto = (b.text or "").strip()
            if not texto:
                continue
            hits = [name for name, rx in _KEYWORDS.items() if rx.search(texto)]
            # Só interessa quando há valor quantificado (N dias/meses/anos):
            # é o que vira FieldValue. Menções sem número são cláusulas, não valor.
            if not hits or not _QUANTIFICADO.search(texto):
                continue
            corpo = re.sub(r"\s+", " ", texto) if full else re.sub(r"\s+", " ", texto)[:280]
            print(f"  [{b.id}] p?{'|'.join(hits)}\n     {corpo}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("export"); pe.add_argument("pid")
    ps = sub.add_parser("scan"); ps.add_argument("pid"); ps.add_argument("papeis", nargs="*")
    ps.add_argument("--full", action="store_true")
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.pid)
    else:
        scan(args.pid, args.papeis, full=args.full)


if __name__ == "__main__":
    main()
