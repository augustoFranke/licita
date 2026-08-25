"""Verificação independente do gate do R1.

Roda contra o que está em disco, não contra o que a coleta acha que fez: relê
``catalogo/processos.json`` e ``catalogo/documentos.jsonl``, abre **todos** os
arquivos de novo, reconfere o SHA-256 e reconstrói a cadeia documental.

Critérios (Plano.md, R1):

- ≥30 processos, ≥5 órgãos, ≥3 categorias de bens;
- cada processo com ETP, TR, edital e contrato;
- todo documento abre localmente;
- toda relação ``ETP → TR → edital → contrato`` catalogada.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .catalog import CADEIA, escrever_json
from .classify import normalizar, parece_aquisicao_de_bens
from .verify import sha256_arquivo, verificar


@dataclass(slots=True)
class Criterio:
    nome: str
    exigido: str
    obtido: str
    passou: bool


def _ler(raiz: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    catalogo = raiz / "catalogo"
    processos = json.loads((catalogo / "processos.json").read_text(encoding="utf-8"))
    documentos = [
        json.loads(linha)
        for linha in (catalogo / "documentos.jsonl").read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]
    relacoes = json.loads((catalogo / "relacoes.json").read_text(encoding="utf-8"))
    return processos, documentos, relacoes


def conferir(raiz: Path, minimo_processos: int = 30) -> dict[str, Any]:
    processos, documentos, relacoes = _ler(raiz)

    falhas: list[dict[str, str]] = []
    abertos = 0
    for documento in documentos:
        caminho = raiz / documento["arquivo"]
        if not caminho.exists():
            falhas.append({"documento_id": documento["documento_id"], "erro": "arquivo ausente"})
            continue
        if sha256_arquivo(caminho) != documento["sha256"]:
            falhas.append({"documento_id": documento["documento_id"], "erro": "SHA-256 divergente"})
            continue
        resultado = verificar(caminho)
        if not resultado.abriu:
            falhas.append(
                {"documento_id": documento["documento_id"], "erro": resultado.erro or "não abriu"}
            )
            continue
        abertos += 1

    completos = [p for p in processos if all(p["cadeia"].get(papel) for papel in CADEIA)]
    exatos = [p for p in processos if all(len(p["cadeia"].get(papel) or []) == 1 for papel in CADEIA)]
    federais = [
        p
        for p in processos
        if p["orgao"].get("esfera") == "F" and p["orgao"].get("poder") == "E"
    ]
    no_escopo = [
        p
        for p in processos
        if str(p["compra"].get("modalidade_id")) == "6"
        and str(p["compra"].get("instrumento_convocatorio_codigo")) == "1"
        and normalizar(p["compra"].get("instrumento_convocatorio") or "") == "edital"
        and str(p["compra"].get("amparo_legal_codigo")) == "1"
        and "lei 14 133 2021" in normalizar(p["compra"].get("amparo_legal_nome") or "")
        and parece_aquisicao_de_bens(p.get("objeto") or "")
    ]
    vinculos_exatos = [
        p
        for p in processos
        if p.get("contratos")
        and all(
            c.get("numero_controle_pncp_compra") == p["numero_controle_pncp"]
            and c.get("criterio_vinculo") == "numeroControlePncpCompra"
            for c in p["contratos"]
        )
    ]
    arestas_por_processo = {p["processo_id"]: 0 for p in processos}
    for aresta in relacoes["cadeia"]:
        arestas_por_processo[aresta["processo_id"]] = (
            arestas_por_processo.get(aresta["processo_id"], 0) + 1
        )
    sem_relacoes = [p["processo_id"] for p in processos if arestas_por_processo.get(p["processo_id"], 0) < 3]

    orgaos = {p["orgao"]["cnpj"] for p in processos}
    categorias = {p["categoria_objeto"] for p in processos}

    criterios = [
        Criterio("processos", f"≥{minimo_processos}", str(len(processos)), len(processos) >= minimo_processos),
        Criterio("órgãos distintos", "≥5", str(len(orgaos)), len(orgaos) >= 5),
        Criterio("categorias de bens", "≥3", str(len(categorias)), len(categorias) >= 3),
        Criterio(
            "processos do Poder Executivo federal",
            f"{len(processos)}",
            str(len(federais)),
            len(federais) == len(processos) and bool(processos),
        ),
        Criterio(
            "processos no escopo normativo e material",
            f"{len(processos)}",
            str(len(no_escopo)),
            len(no_escopo) == len(processos) and bool(processos),
        ),
        Criterio(
            "processos com cadeia completa",
            f"{len(processos)}",
            str(len(completos)),
            len(completos) == len(processos) and bool(processos),
        ),
        Criterio(
            "processos com exatamente um documento por papel",
            f"{len(processos)}",
            str(len(exatos)),
            len(exatos) == len(processos) and bool(processos),
        ),
        Criterio(
            "vínculos compra–contrato por numeroControlePncpCompra",
            f"{len(processos)}",
            str(len(vinculos_exatos)),
            len(vinculos_exatos) == len(processos) and bool(processos),
        ),
        Criterio(
            "documentos que abrem localmente",
            f"{len(documentos)}",
            str(abertos),
            abertos == len(documentos) and bool(documentos),
        ),
        Criterio(
            "relações ETP→TR→edital→contrato catalogadas",
            f"{len(processos)} processos",
            f"{len(processos) - len(sem_relacoes)} processos",
            not sem_relacoes,
        ),
    ]

    for papel in CADEIA:
        quantos = sum(1 for d in documentos if d["papel"] == papel)
        criterios.append(
            Criterio(f"documentos {papel}", f"≥{minimo_processos}", str(quantos), quantos >= minimo_processos)
        )

    return {
        "passou": all(c.passou for c in criterios),
        "criterios": [asdict(c) for c in criterios],
        "falhas_de_abertura": falhas,
        "processos_sem_relacoes": sem_relacoes,
    }


def como_markdown(raiz: Path, resultado: dict[str, Any]) -> str:
    processos, documentos, _ = _ler(raiz)
    linhas = [
        "# Gate R1 — corpus real",
        "",
        f"**Resultado: {'PASSOU' if resultado['passou'] else 'NÃO PASSOU'}**",
        "",
        "Verificação independente: cada arquivo listado no catálogo foi reaberto",
        "a partir do disco, com conferência de SHA-256, e a cadeia documental foi",
        "reconstruída a partir de `catalogo/relacoes.json`.",
        "",
        "| Critério | Exigido | Obtido | |",
        "|---|---|---|---|",
    ]
    for criterio in resultado["criterios"]:
        marca = "✅" if criterio["passou"] else "❌"
        linhas.append(
            f"| {criterio['nome']} | {criterio['exigido']} | {criterio['obtido']} | {marca} |"
        )

    linhas += ["", "## Processos", "", "| # | Processo | Órgão | UF | Categoria | ETP | TR | Edital | Contrato |", "|---|---|---|---|---|---|---|---|---|"]
    for posicao, processo in enumerate(sorted(processos, key=lambda p: p["processo_id"]), start=1):
        cadeia = processo["cadeia"]
        marcas = "".join(
            f" {len(cadeia.get(papel) or [])} |" for papel in CADEIA
        )
        linhas.append(
            f"| {posicao} | [{processo['numero_controle_pncp']}]({processo['fontes']['portal_pncp']}) "
            f"| {processo['orgao']['razao_social']} | {processo['orgao']['uf'] or '—'} "
            f"| {processo['categoria_objeto']} |{marcas}"
        )

    if resultado["falhas_de_abertura"]:
        linhas += ["", "## Documentos que não abriram", ""]
        for falha in resultado["falhas_de_abertura"]:
            linhas.append(f"- `{falha['documento_id']}`: {falha['erro']}")

    linhas += [
        "",
        f"Total de documentos: **{len(documentos)}**.",
        "",
    ]
    return "\n".join(linhas)


def principal(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verifica o gate do R1 sobre o corpus em disco.")
    parser.add_argument("--raiz", type=Path, default=Path("corpus"))
    parser.add_argument("--processos", type=int, default=30)
    argumentos = parser.parse_args(argv)

    resultado = conferir(argumentos.raiz, argumentos.processos)
    escrever_json(argumentos.raiz / "catalogo" / "gate.json", resultado)
    markdown = como_markdown(argumentos.raiz, resultado)
    (argumentos.raiz / "GATE_R1.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if resultado["passou"] else 1


if __name__ == "__main__":
    raise SystemExit(principal())
