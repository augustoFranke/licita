"""Promove processos históricos adicionando o elo EDITAL.

O edital vem na MESMA lista de ``arquivos_compra`` que a coleta de cadeias
completas consulta; o coletor vigente o seleciona e baixa junto com
ETP/TR. Esta ferramenta, restrita e idempotente, existe apenas para promover
processos históricos indicados, verifica que o edital abre com texto utilizável
e anexa a entrada ao catálogo — sem tocar nas linhas ETP/TR já existentes.

Ela não é uma segunda estratégia de descoberta: processos novos são sempre
descobertos pelo feed de contratos em ``licita_corpus.collect.coletar``.
Antes de consultar ou baixar anexos, o utilitário também descarta processos
marcados como ``OUT_OF_SCOPE``/``FORA_DO_PERFIL`` no catálogo.

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
    POLICY_VERSION,
    _escolher_mais_recente,
    _registrar_documento,
    _resumir_arquivo,
)
from _corpus_sync import (
    CORPUS,
    ROOT,
    PROCESSOS,
    carregar_catalogo,
    para_publico,
    publicar,
    registrar_no_estado,
)
from licita_corpus.catalog import (
    PAPEIS_OPCIONAIS,
    documento_id,
    ocr_historico_utilizavel,
)
from licita_corpus.pncp import Pncp, partes_controle
from licita_corpus.store import baixar_documento

GOLDEN_DIRS = (ROOT / "r4" / "data" / "dev", ROOT / "r4" / "data" / "eval")


def _pids_golden() -> set[str]:
    pids: set[str] = set()
    for d in GOLDEN_DIRS:
        for p in d.glob("*.json"):
            pids.add(p.stem)
    return pids


def _processos_promoviveis() -> set[str]:
    """Retorna processos no perfil; falha de catálogo bloqueia downloads."""
    if not PROCESSOS.exists():
        return set()
    try:
        bruto = json.loads(PROCESSOS.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return set()
    registros = bruto.get("processos", []) if isinstance(bruto, dict) else bruto
    if not isinstance(registros, list):
        return set()
    promoviveis: set[str] = set()
    for processo in registros:
        if not isinstance(processo, dict) or not processo.get("processo_id"):
            continue
        status_escopo = str(processo.get("scope_status") or "").upper()
        status_perfil = str(processo.get("perfil_status") or "").upper()
        if status_escopo == "OUT_OF_SCOPE" or status_perfil in {
            "OUT_OF_SCOPE",
            "FORA_DO_PERFIL",
            "UNSUPPORTED",
        }:
            continue
        promoviveis.add(str(processo["processo_id"]))
    return promoviveis


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



def enriquecer(pids: list[str], *, limite: int | None = None) -> None:
    catalogo = carregar_catalogo()
    promoviveis = _processos_promoviveis()
    por_processo: dict[str, list[dict[str, Any]]] = {}
    controle: dict[str, str] = {}
    for d in catalogo:
        por_processo.setdefault(d["processo_id"], []).append(d)
        controle.setdefault(d["processo_id"], d["numero_controle_pncp_origem"])

    alvos = [p for p in pids if p in por_processo]
    ausentes = [p for p in pids if p not in por_processo]
    for p in ausentes:
        print(f"[ignorado] {p}: não está no catálogo")
    fora_perfil = [
        p for p in alvos
        if p not in promoviveis
    ]
    for p in fora_perfil:
        print(f"[ignorado] {p}: processo fora do perfil, sem download")
    alvos = [p for p in alvos if p not in fora_perfil]

    ja_tem = [p for p in alvos if any(x.get("papel") == EDITAL for x in por_processo[p])]
    pendentes = [p for p in alvos if p not in ja_tem]
    for p in ja_tem:
        print(f"[ok-já-existe] {p}: EDITAL já no catálogo")
    if limite is not None:
        pendentes = pendentes[:limite]

    novos: list[dict[str, Any]] = []
    # registro completo (com _texto) por processo, para gravar no estado
    para_estado: dict[str, dict[str, Any]] = {}
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

            publico = para_publico(registro)
            novos.append(publico)
            por_processo[pid].append(publico)
            para_estado[pid] = registro
            print(f"[edital+] {pid}: {publico['arquivo']} "
                  f"({publico['bytes']} bytes, {registro['verificacao'].get('caracteres')} chars, "
                  f"ocr={registro['verificacao'].get('ocr_usado')})")

    publicar(novos, para_estado)



def reparar_estado() -> None:
    """Registra no estado os elos opcionais que só existem no catálogo.

    Necessário uma vez para os elos baixados antes de o registro no estado
    existir. ``_texto`` não é reconstruído aqui: a catalogação o recalcula ao
    abrir o arquivo, e só o preserva quando veio de OCR — nenhum destes veio.
    """
    catalogo = carregar_catalogo()
    opcionais = {}
    for d in catalogo:
        if d.get("papel") in PAPEIS_OPCIONAIS:
            opcionais[d["processo_id"]] = {
                k: v for k, v in d.items() if k != "reuso"
            }
    print(f"[reparo] {len(opcionais)} elo(s) opcional(is) no catálogo")
    registrar_no_estado(opcionais)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pids", nargs="*", help="processo_id(s) explícitos")
    ap.add_argument(
        "--reparar-estado",
        action="store_true",
        help="registra no estado os elos que já estão no catálogo, sem baixar nada",
    )
    ap.add_argument("--golden", action="store_true", help="os processos do golden (dev+eval)")
    ap.add_argument("--all", action="store_true", help="todos os processos do catálogo")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.reparar_estado:
        reparar_estado()
        return

    if args.all:
        pids = sorted({d["processo_id"] for d in carregar_catalogo()})
    elif args.golden:
        pids = sorted(_pids_golden())
    else:
        pids = args.pids
    if not pids:
        ap.error("informe --golden, --all ou pid(s)")
    enriquecer(pids, limite=args.limit)


if __name__ == "__main__":
    main()
