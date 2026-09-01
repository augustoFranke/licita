"""Mede o rendimento real de cadeias documentais completas no PNCP.

Pergunta que responde, com número e não com estimativa: partindo dos CONTRATOS
publicados (que garantem, por construção, que o elo final existe), qual a
fração de processos que também publica ETP, TR e EDITAL?

Estratégia — inversão da busca:
    feed de contratos  ->  numeroControlePncpCompra  ->  arquivos da compra
Assim o contrato nunca é "torcida": ele já existe. O que se mede é quanto do
resto da cadeia o órgão publicou.

O endpoint de arquivos do PNCP responde na casa de ~10s, então o levantamento
usa concorrência limitada com o mesmo throttle global do coletor. Grava
incrementalmente: pode ser interrompido e o parcial continua válido.

Uso:
    uv run python tools/survey_cadeia.py --meses 2024-06 --alvo 150
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from licita_corpus.classify import papel_documento
from licita_corpus.pncp import CONSULTA, Pncp, partes_controle

ROOT = Path(__file__).resolve().parent.parent
SAIDA = ROOT / "corpus" / "catalogo" / "survey_cadeia.json"

PAPEIS_ALVO = ("ETP", "TR", "EDITAL")


def _ultimo_dia(mes: str) -> tuple[str, str]:
    ano, m = (int(x) for x in mes.split("-"))
    fim = {1: 31, 2: 29 if ano % 4 == 0 else 28, 3: 31, 4: 30, 5: 31, 6: 30,
           7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[m]
    return f"{ano}{m:02d}01", f"{ano}{m:02d}{fim}"


def coletar_compras_com_contrato(p: Pncp, mes: str, paginas: int) -> list[str]:
    """Números de controle de COMPRAS que possuem contrato publicado."""
    ini, fim = _ultimo_dia(mes)
    vistos: list[str] = []
    conhecidos: set[str] = set()
    for pagina in range(1, paginas + 1):
        r = p._http.json(f"{CONSULTA}/contratos",
                         {"dataInicial": ini, "dataFinal": fim, "pagina": pagina},
                         sem_conteudo_ok=True, ausente_ok=True)
        if not isinstance(r, dict):
            break
        dados = r.get("data") or []
        if not dados:
            break
        for c in dados:
            if (c.get("orgaoEntidade") or {}).get("esferaId") != "M":
                continue
            nc = c.get("numeroControlePncpCompra")
            if nc and nc not in conhecidos:
                conhecidos.add(nc)
                vistos.append(nc)
    return vistos


def papeis_da_compra(p: Pncp, nc: str) -> tuple[str, set[str], int]:
    cnpj, ano, seq = partes_controle(nc)
    arqs = p.arquivos_compra(cnpj, ano, seq)
    papeis = {
        papel_documento(a.get("tipoDocumentoId"), str(a.get("titulo") or ""))
        for a in arqs if a.get("url")
    }
    return nc, papeis, len(arqs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meses", nargs="+", default=["2024-06"])
    ap.add_argument("--alvo", type=int, default=150, help="compras a inspecionar")
    ap.add_argument("--paginas", type=int, default=2, help="páginas do feed por mês")
    ap.add_argument("--concorrencia", type=int, default=6)
    args = ap.parse_args()

    t0 = time.time()
    resultados: dict[str, dict] = {}
    if SAIDA.exists():
        resultados = json.loads(SAIDA.read_text(encoding="utf-8")).get("processos", {})
        print(f"retomando: {len(resultados)} já medidos")

    lock = threading.Lock()
    with Pncp(intervalo=0.35) as p:
        candidatos: list[str] = []
        for mes in args.meses:
            candidatos.extend(coletar_compras_com_contrato(p, mes, args.paginas))
            print(f"[feed] {mes}: acumulado {len(candidatos)} compras com contrato", flush=True)

        pendentes = [nc for nc in candidatos if nc not in resultados][: args.alvo]
        print(f"[alvo] inspecionando {len(pendentes)} compras\n", flush=True)

        def tarefa(nc: str):
            try:
                return papeis_da_compra(p, nc)
            except Exception as e:
                return nc, {f"__erro__{type(e).__name__}"}, 0

        feito = 0
        with ThreadPoolExecutor(max_workers=args.concorrencia) as ex:
            futuros = [ex.submit(tarefa, nc) for nc in pendentes]
            for fut in as_completed(futuros):
                nc, papeis, n_arq = fut.result()
                completa = set(PAPEIS_ALVO) <= papeis
                with lock:
                    resultados[nc] = {
                        "papeis": sorted(papeis),
                        "n_arquivos": n_arq,
                        "cadeia_completa": completa,
                    }
                    feito += 1
                    if feito % 10 == 0:
                        SAIDA.parent.mkdir(parents=True, exist_ok=True)
                        SAIDA.write_text(json.dumps(
                            {"processos": resultados}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
                        print(f"  ... {feito}/{len(pendentes)} ({time.time()-t0:.0f}s)", flush=True)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"processos": resultados}, ensure_ascii=False, indent=2),
                     encoding="utf-8")

    stats = Counter()
    for nc, r in resultados.items():
        stats["total"] += 1
        for x in PAPEIS_ALVO:
            if x in r["papeis"]:
                stats[x] += 1
        if r["cadeia_completa"]:
            stats["completa"] += 1
        if {"ETP", "TR"} <= set(r["papeis"]):
            stats["etp_tr"] += 1

    t = stats["total"] or 1
    print(f"\n===== RENDIMENTO MEDIDO (n={t}, {time.time()-t0:.0f}s) =====")
    for k in ("ETP", "TR", "EDITAL", "etp_tr", "completa"):
        print(f"  {k:<10} {stats[k]:>4}/{t}  ({stats[k]/t*100:.1f}%)")
    print(f"\nsaída: {SAIDA.relative_to(ROOT)}")
    completas = [nc for nc, r in resultados.items() if r["cadeia_completa"]]
    print(f"cadeias completas ({len(completas)}): {completas[:20]}")


if __name__ == "__main__":
    main()
