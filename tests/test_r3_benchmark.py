"""Benchmark determinístico de reabertura de âncoras da fase R3.

Verifica se as evidências anotadas reabrem com fidelidade >= 95% a partir dos
arquivos brutos em disco via ``licita_ingest.extract_document``.

A taxa que fecha a fase é a das anotações de procedência ``manual``: uma quote
``engine_generated`` foi escrita pelo próprio extrator, então reabri-la só
mostra que a função concorda consigo mesma.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from licita_core.schema import ProcurementProcess
from licita_ingest.extractor import extract_document, sha256_file

ROOT_DIR = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT_DIR / "corpus"
CANDIDATES_DIR = ROOT_DIR / "r4" / "data" / "candidates"
CATALOG_PATH = CORPUS_DIR / "catalogo" / "documentos.jsonl"
MANIFEST_PATH = ROOT_DIR / "r4" / "manifest.json"

# Piso de âncoras escolhidas por pessoa para a medida ter valor probatório.
MIN_ANCORAS_MANUAIS = 50


def _carregar_catalogo_documentos() -> dict[tuple[str, str], dict[str, Any]]:
    assert CATALOG_PATH.exists(), f"Catálogo de documentos não encontrado em {CATALOG_PATH}"
    catalogo: dict[tuple[str, str], dict[str, Any]] = {}
    for linha in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        registro = json.loads(linha)
        chave = (str(registro["processo_id"]), str(registro["papel"]))
        catalogo[chave] = registro
    return catalogo


def _procedencias() -> dict[str, str]:
    """Procedência da anotação de cada processo, conforme ``r4/manifest.json``."""
    manifesto = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        p["processo_id"]: p.get("annotation_provenance", "desconhecida")
        for p in manifesto["processes"]
    }


def executar_benchmark_r3() -> dict[str, Any]:
    catalogo = _carregar_catalogo_documentos()
    procedencias = _procedencias()
    arquivos_candidatos = sorted(CANDIDATES_DIR.glob("*.json"))
    assert len(arquivos_candidatos) == 10, f"Esperados 10 candidatos, encontrados {len(arquivos_candidatos)}"

    total_evidencias_global = 0
    reabertas_ok_global = 0
    total_manuais = 0
    reabertas_manuais = 0
    falhas_detalhadas: list[dict[str, Any]] = []
    estatisticas_processos: list[dict[str, Any]] = []

    for caminho_candidato in arquivos_candidatos:
        conteudo = json.loads(caminho_candidato.read_text(encoding="utf-8"))
        processo = ProcurementProcess.model_validate(conteudo)
        pid = processo.id

        documentos_extraidos: dict[str, Any] = {}
        for doc in processo.documents:
            chave = (pid, doc.type.value)
            assert chave in catalogo, f"Documento ({pid}, {doc.type.value}) ausente do catálogo"
            info_catalogo = catalogo[chave]
            caminho_arquivo = CORPUS_DIR / info_catalogo["arquivo"]
            assert caminho_arquivo.exists(), f"Arquivo físico ausente: {caminho_arquivo}"

            # C2: Imutabilidade do original via SHA-256
            hash_calculado = sha256_file(caminho_arquivo)
            assert hash_calculado == info_catalogo["sha256"], (
                f"SHA-256 divergente no arquivo {caminho_arquivo}: {hash_calculado} != {info_catalogo['sha256']}"
            )

            # Extração R3
            extraido = extract_document(caminho_arquivo, document_id=doc.id)
            assert len(extraido.blocks) > 0, f"Documento extraído com zero blocos: {doc.id}"
            documentos_extraidos[doc.id] = extraido

        total_proc = 0
        ok_proc = 0

        for evid in processo._iter_evidence():
            total_evidencias_global += 1
            total_proc += 1

            doc_extraido = documentos_extraidos.get(evid.document_id)
            if not doc_extraido:
                falhas_detalhadas.append({
                    "processo_id": pid,
                    "document_id": evid.document_id,
                    "erro": "document_id_nao_extraido",
                    "evidence": evid.model_dump(),
                })
                continue

            bloco = doc_extraido.get_block(evid.block_id)
            if not bloco:
                falhas_detalhadas.append({
                    "processo_id": pid,
                    "document_id": evid.document_id,
                    "erro": "block_id_nao_encontrado",
                    "block_id": evid.block_id,
                    "evidence": evid.model_dump(),
                })
                continue

            if evid.page < 1:
                falhas_detalhadas.append({
                    "processo_id": pid,
                    "document_id": evid.document_id,
                    "erro": "pagina_invalida",
                    "page": evid.page,
                    "evidence": evid.model_dump(),
                })
                continue

            if evid.quote not in bloco.text:
                falhas_detalhadas.append({
                    "processo_id": pid,
                    "document_id": evid.document_id,
                    "erro": "quote_divergente",
                    "quote_esperado": evid.quote,
                    "texto_bloco": bloco.text,
                    "evidence": evid.model_dump(),
                })
                continue

            reabertas_ok_global += 1
            ok_proc += 1

        taxa_proc = (ok_proc / total_proc * 100.0) if total_proc > 0 else 100.0
        procedencia = procedencias.get(pid, "desconhecida")
        # manual e assistant_annotated: âncora escolhida por leitura (não pelo
        # extrator sob teste). engine_generated não conta.
        if procedencia in ("manual", "assistant_annotated"):
            total_manuais += total_proc
            reabertas_manuais += ok_proc
        estatisticas_processos.append({
            "processo_id": pid,
            "procedencia": procedencia,
            "total_evidencias": total_proc,
            "evidencias_reabertas": ok_proc,
            "taxa_reabertura": taxa_proc,
        })

    taxa_global = (reabertas_ok_global / total_evidencias_global * 100.0) if total_evidencias_global > 0 else 100.0
    taxa_manual = (reabertas_manuais / total_manuais * 100.0) if total_manuais > 0 else 0.0
    return {
        "evidencias_manuais": total_manuais,
        "evidencias_manuais_reabertas": reabertas_manuais,
        "taxa_manual": taxa_manual,
        "total_processos": len(arquivos_candidatos),
        "total_documentos": len(arquivos_candidatos) * 2,
        "total_evidencias": total_evidencias_global,
        "evidencias_reabertas": reabertas_ok_global,
        "taxa_global": taxa_global,
        "processos": estatisticas_processos,
        "falhas": falhas_detalhadas,
    }


def test_r3_benchmark_reabertura_minimo_95_porcento() -> None:
    """Reabertura das âncoras escolhidas por pessoa: piso de 95% da saída da R3."""
    resultado = executar_benchmark_r3()

    lidas = [p for p in resultado["processos"]
             if p["procedencia"] in ("manual", "assistant_annotated")]
    gerados = [p for p in resultado["processos"] if p["procedencia"] == "engine_generated"]

    print(
        f"\n[R3 ANCHOR BENCHMARK]\n"
        f"  Processos: {resultado['total_processos']} "
        f"({len(lidas)} lidas [manual/assistant], {len(gerados)} engine_generated)\n"
        f"  Âncoras lidas:  {resultado['evidencias_manuais_reabertas']}/"
        f"{resultado['evidencias_manuais']} ({resultado['taxa_manual']:.2f}%)\n"
        f"  Âncoras totais (não probatórias): {resultado['evidencias_reabertas']}/"
        f"{resultado['total_evidencias']} ({resultado['taxa_global']:.2f}%)"
    )

    assert resultado["total_processos"] == 10
    assert resultado["total_documentos"] == 20
    assert len(resultado["falhas"]) == 0, f"Falhas encontradas no benchmark: {resultado['falhas']}"

    assert resultado["evidencias_manuais"] >= MIN_ANCORAS_MANUAIS, (
        f"Só {resultado['evidencias_manuais']} âncoras de leitura "
        f"(manual/assistant, mínimo {MIN_ANCORAS_MANUAIS}). Âncora "
        f"engine_generated não prova reabertura: a quote veio do próprio "
        f"extrator que a reabre."
    )
    assert resultado["taxa_manual"] >= 95.0, (
        f"Reabertura das âncoras lidas insuficiente: {resultado['taxa_manual']:.2f}% < 95.0%"
    )

    for proc_stat in lidas:
        assert proc_stat["taxa_reabertura"] >= 95.0, (
            f"Processo {proc_stat['processo_id']} abaixo de 95%: "
            f"{proc_stat['taxa_reabertura']:.2f}%"
        )
