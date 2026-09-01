"""Enriquece o corpus com o EDITAL de cada processo já coletado.

O edital vem na MESMA lista de ``arquivos_compra`` que o coletor de pares já
consulta; o coletor apenas o descartava (ver ``pncp.py``: "nenhum edital é
baixado"). Esta ferramenta, restrita e idempotente, baixa o edital dos
processos indicados, verifica que ele abre com texto utilizável e anexa a
entrada ao catálogo — sem tocar nas linhas ETP/TR já existentes.

Reusa os mesmos helpers do coletor (``_resumir_arquivo``, ``baixar_documento``,
``_registrar_documento``), então a entrada gravada é idêntica à que o coletor
produziria. O texto derivado de OCR, quando necessário, carrega o cache
auditável (SHA-256 do texto, versão do pipeline, idioma) que o gate exige.

Seleção do edital: entre os arquivos com ``tipoDocumentoId == 2`` (autoritativo
do PNCP), prefere os cujo título contém "edital" (evita certidões/avisos que o
PNCP também rotula como tipo 2) e, dentro deles, a revisão mais recente.

Uso:
    uv run python tools/fetch_editais.py --golden           # só os 10 do golden
    uv run python tools/fetch_editais.py --all              # todos os coletados
    uv run python tools/fetch_editais.py <pid> [<pid> ...]  # processos avulsos
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from licita_corpus.classify import EDITAL, normalizar
from licita_corpus.collect import (
    _escolher_mais_recente,
    _registrar_documento,
    _resumir_arquivo,
)
from licita_corpus.catalog import (
    CADEIA,
    documento_id,
    montar_relacoes,
    ocr_historico_utilizavel,
)
from licita_corpus.pncp import Pncp, partes_controle
from licita_corpus.store import baixar_documento, processo_id as pid_de_controle

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CATALOG = CORPUS / "catalogo" / "documentos.jsonl"
PROCESSOS = CORPUS / "catalogo" / "processos.json"
RELACOES = CORPUS / "catalogo" / "relacoes.json"
GOLDEN_DIRS = (ROOT / "r4" / "data" / "dev", ROOT / "r4" / "data" / "eval")


def _carregar_catalogo() -> list[dict[str, Any]]:
    return [json.loads(l) for l in CATALOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pids_golden() -> set[str]:
    pids: set[str] = set()
    for d in GOLDEN_DIRS:
        for p in d.glob("*.json"):
            pids.add(p.stem)
    return pids


def _escolher_edital(resumidos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Melhor candidato a edital: tipo 2, ativo, baixável, título preferido."""
    tipo2 = [
        a for a in resumidos
        if a.get("papel") == EDITAL
        and str(a.get("tipo_documento_id")) == "2"
        and a.get("url")
        and a.get("status_ativo", True)
    ]
    if not tipo2:
        return None
    com_titulo = [a for a in tipo2 if "edital" in normalizar(a.get("titulo") or "")]
    return _escolher_mais_recente(com_titulo or tipo2)


def _para_publico(registro: dict[str, Any]) -> dict[str, Any]:
    """Remove campos internos e alinha ao formato persistido do catálogo."""
    publico = {k: v for k, v in registro.items() if k not in ("_texto", "ocr_cache")}
    publico["reuso"] = []
    return publico


def enriquecer(pids: list[str], *, limite: int | None = None) -> None:
    catalogo = _carregar_catalogo()
    por_processo: dict[str, list[dict[str, Any]]] = {}
    controle: dict[str, str] = {}
    for d in catalogo:
        por_processo.setdefault(d["processo_id"], []).append(d)
        controle.setdefault(d["processo_id"], d["numero_controle_pncp_origem"])

    alvos = [p for p in pids if p in por_processo]
    ausentes = [p for p in pids if p not in por_processo]
    for p in ausentes:
        print(f"[ignorado] {p}: não está no catálogo")

    ja_tem = [p for p in alvos if any(x.get("papel") == EDITAL for x in por_processo[p])]
    pendentes = [p for p in alvos if p not in ja_tem]
    for p in ja_tem:
        print(f"[ok-já-existe] {p}: EDITAL já no catálogo")
    if limite is not None:
        pendentes = pendentes[:limite]

    novos: list[dict[str, Any]] = []
    with Pncp() as pncp:
        for pid in pendentes:
            nc = controle[pid]
            cnpj, ano, seq = partes_controle(nc)
            try:
                brutos = pncp.arquivos_compra(cnpj, ano, seq)
            except Exception as e:  # rede: reporta e segue, nunca trava o lote
                print(f"[falha-api] {pid}: {type(e).__name__}: {str(e)[:80]}")
                continue
            resumidos = [_resumir_arquivo(b) for b in brutos]
            escolha = _escolher_edital(resumidos)
            if escolha is None:
                achados = sorted({a.get("papel") for a in resumidos})
                print(f"[sem-edital] {pid}: nenhum tipo-2 baixável (papeis: {achados})")
                continue

            destino = CORPUS / "documentos" / pid
            baixado = baixar_documento(
                pncp, escolha["url"], destino, EDITAL,
                escolha.get("sequencial_documento"), escolha.get("titulo") or "",
            )
            if baixado is None:
                print(f"[sem-arquivo] {pid}: PNCP não entregou PDF/DOCX do edital")
                continue

            ordem = len(por_processo[pid])
            ident = documento_id(pid, EDITAL, escolha.get("sequencial_documento"), ordem)
            registro = _registrar_documento(ident, pid, nc, escolha, baixado, CORPUS)
            # Documento escaneado: refaz com OCR para produzir texto auditável.
            if registro["verificacao"].get("precisa_ocr"):
                registro = _registrar_documento(
                    ident, pid, nc, escolha, baixado, CORPUS, ocr=True
                )
                usavel = ocr_historico_utilizavel(
                    registro, abriu=registro["verificacao"].get("abriu", False)
                )
            else:
                v = registro["verificacao"]
                usavel = bool(v.get("abriu") and int(v.get("caracteres") or 0) > 0)

            if not usavel:
                v = registro["verificacao"]
                print(f"[nao-utilizavel] {pid}: abriu={v.get('abriu')} "
                      f"chars={v.get('caracteres')} precisa_ocr={v.get('precisa_ocr')}")
                continue

            publico = _para_publico(registro)
            novos.append(publico)
            por_processo[pid].append(publico)
            print(f"[edital+] {pid}: {publico['arquivo']} "
                  f"({publico['bytes']} bytes, {registro['verificacao'].get('caracteres')} chars, "
                  f"ocr={registro['verificacao'].get('ocr_usado')})")

    if not novos:
        print("\nNenhum edital novo adicionado.")
        return

    catalogo.extend(novos)
    with CATALOG.open("w", encoding="utf-8") as saida:
        for r in catalogo:
            saida.write(json.dumps(r, ensure_ascii=False) + "\n")
    sincronizar_catalogo(catalogo)
    print(f"\n{len(novos)} edital(is) adicionado(s) ao catálogo ({CATALOG.relative_to(ROOT)}).")


def sincronizar_catalogo(catalogo: list[dict[str, Any]]) -> None:
    """Refaz ``cadeia`` e relações a partir do catálogo de documentos.

    O documento sozinho não basta: o gate lê a cadeia do processo e as arestas
    de ``relacoes.json``. Sem esta sincronização o catálogo fica internamente
    inconsistente — documento presente em disco e ausente da cadeia.
    """
    por_processo: dict[str, list[dict[str, Any]]] = {}
    for d in catalogo:
        por_processo.setdefault(d["processo_id"], []).append(d)

    processos = json.loads(PROCESSOS.read_text(encoding="utf-8"))
    registros = processos["processos"] if isinstance(processos, dict) else processos
    cadeias: dict[str, dict[str, list[str]]] = {}
    for processo in registros:
        pid = processo["processo_id"]
        cadeia = {papel: [] for papel in CADEIA}
        for doc in por_processo.get(pid, []):
            if doc.get("papel") in cadeia:
                cadeia[doc["papel"]].append(doc["documento_id"])
        processo["cadeia"] = cadeia
        cadeias[pid] = cadeia
    PROCESSOS.write_text(
        json.dumps(processos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    relacoes = json.loads(RELACOES.read_text(encoding="utf-8"))
    arestas: list[dict[str, str]] = []
    for pid, cadeia in cadeias.items():
        arestas.extend(montar_relacoes(pid, cadeia))
    relacoes["cadeia"] = arestas
    RELACOES.write_text(
        json.dumps(relacoes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"catálogo sincronizado: {len(arestas)} arestas de cadeia")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pids", nargs="*", help="processo_id(s) explícitos")
    ap.add_argument("--golden", action="store_true", help="os processos do golden (dev+eval)")
    ap.add_argument("--all", action="store_true", help="todos os processos do catálogo")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.all:
        pids = sorted({d["processo_id"] for d in _carregar_catalogo()})
    elif args.golden:
        pids = sorted(_pids_golden())
    else:
        pids = args.pids
    if not pids:
        ap.error("informe --golden, --all ou pid(s)")
    enriquecer(pids, limite=args.limit)


if __name__ == "__main__":
    main()
