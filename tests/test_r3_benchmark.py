"""Benchmark determinístico de reabertura de âncoras da fase R3.

Verifica se nos 10 processos candidatos reais (20 documentos: 10 ETPs + 10 TRs),
as evidências anotadas reabrem com fidelidade >= 95% a partir dos arquivos brutos
em disco via ``licita_ingest.extract_document``.
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


def executar_benchmark_r3() -> dict[str, Any]:
    catalogo = _carregar_catalogo_documentos()
    arquivos_candidatos = sorted(CANDIDATES_DIR.glob("*.json"))
    assert len(arquivos_candidatos) == 10, f"Esperados 10 candidatos, encontrados {len(arquivos_candidatos)}"

    total_evidencias_global = 0
    reabertas_ok_global = 0
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
        estatisticas_processos.append({
            "processo_id": pid,
            "total_evidencias": total_proc,
            "evidencias_reabertas": ok_proc,
            "taxa_reabertura": taxa_proc,
        })

    taxa_global = (reabertas_ok_global / total_evidencias_global * 100.0) if total_evidencias_global > 0 else 100.0
    return {
        "total_processos": len(arquivos_candidatos),
        "total_documentos": len(arquivos_candidatos) * 2,
        "total_evidencias": total_evidencias_global,
        "evidencias_reabertas": reabertas_ok_global,
        "taxa_global": taxa_global,
        "processos": estatisticas_processos,
        "falhas": falhas_detalhadas,
    }


def test_r3_benchmark_reabertura_minimo_95_porcento() -> None:
    """Verifica se a taxa global e individual de reabertura atende ao DoD da R3 (>= 95%)."""
    resultado = executar_benchmark_r3()

    assert resultado["total_processos"] == 10
    assert resultado["total_documentos"] == 20
    assert resultado["total_evidencias"] >= 50, "Volume de evidências avaliado insuficiente"
    assert resultado["taxa_global"] >= 95.0, (
        f"Taxa global de reabertura insuficiente: {resultado['taxa_global']:.2f}% < 95.0%"
    )
    assert len(resultado["falhas"]) == 0, f"Falhas encontradas no benchmark: {resultado['falhas']}"

    for proc_stat in resultado["processos"]:
        assert proc_stat["taxa_reabertura"] >= 95.0, (
            f"Processo {proc_stat['processo_id']} abaixo de 95%: {proc_stat['taxa_reabertura']:.2f}%"
        )
