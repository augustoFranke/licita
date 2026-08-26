"""Catálogo do corpus: metadados, cadeia documental e relatório do gate.

Três artefatos são gravados em ``corpus/catalogo/``:

``processos.json``
    Um registro por processo — órgão, processo administrativo, datas, objeto,
    valores, fontes (URLs) e a cadeia documental já resolvida.
``documentos.jsonl``
    Um registro por arquivo — papel, título, URL de origem, caminho local,
    SHA-256, tamanho, páginas e resultado da verificação de abertura.
``relacoes.json``
    As arestas ``ETP → TR → edital → contrato`` de cada processo, mais as
    marcas de cópia/reuso entre documentos.

``gate.md`` em ``corpus/`` traduz esses arquivos no relatório do gate do R1.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from .classify import CONTRATO, EDITAL, ETP, TR
from .pncp import url_contrato, url_processo

#: Ordem canônica da cadeia. As arestas de ``relacoes.json`` são os pares
#: consecutivos desta sequência que existirem no processo.
CADEIA = (ETP, TR, EDITAL, CONTRATO)


def escrever_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def escrever_jsonl(caminho: Path, registros: Iterable[dict[str, Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as saida:
        for registro in registros:
            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")


def documento_id(processo_id: str, papel: str, sequencial: int | None, ordem: int) -> str:
    return f"{processo_id}#{papel.lower()}-{sequencial if sequencial is not None else ordem:02d}"


def _url_do_contrato(contrato: dict[str, Any]) -> str:
    """Endereço público do contrato no PNCP."""
    return url_contrato(contrato["numero_controle_pncp"])


def montar_relacoes(processo_id: str, cadeia: dict[str, list[str]]) -> list[dict[str, str]]:
    """Arestas entre elos consecutivos presentes.

    Elos ausentes são atravessados: um processo com ETP, TR e contrato (sem
    edital publicado) gera ``ETP→TR`` e ``TR→contrato``. A cadeia real do
    processo administrativo não deixa de existir porque um arquivo não foi
    publicado no PNCP.
    """
    presentes = [papel for papel in CADEIA if cadeia.get(papel)]
    arestas: list[dict[str, str]] = []
    for origem, destino in zip(presentes, presentes[1:]):
        for id_origem in cadeia[origem]:
            for id_destino in cadeia[destino]:
                arestas.append(
                    {
                        "processo_id": processo_id,
                        "de_papel": origem,
                        "para_papel": destino,
                        "de": id_origem,
                        "para": id_destino,
                        "relacao": "precede_em",
                    }
                )
    return arestas


def montar_processo(
    compra: dict[str, Any],
    extras: dict[str, Any] | None,
    documentos: Sequence[dict[str, Any]],
    contratos: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Registro de processo com metadados, fontes e cadeia documental.

    ``extras`` traz o que não vem da busca: número do processo administrativo,
    totais derivados dos itens da compra e o caminho do arquivo de itens. Cada
    valor carrega de onde veio, porque as fontes têm confiabilidades diferentes
    — o número do processo, por exemplo, é o que o órgão declarou no contrato.
    """
    numero = compra["numero_controle_pncp"]
    identificador = numero.replace("/", "-")
    extras = extras or {}

    cadeia: dict[str, list[str]] = {papel: [] for papel in CADEIA}
    for documento in documentos:
        if documento["papel"] in cadeia:
            cadeia[documento["papel"]].append(documento["documento_id"])

    return {
        "processo_id": identificador,
        "numero_controle_pncp": numero,
        "orgao": {
            "cnpj": compra["cnpj_orgao"],
            "razao_social": compra.get("orgao"),
            "esfera": compra.get("esfera"),
            "poder": compra.get("poder"),
            "unidade": compra.get("unidade"),
            "uf": compra.get("uf"),
            "municipio": compra.get("municipio"),
        },
        "processo_administrativo": extras.get("processo_administrativo"),
        "processo_administrativo_fonte": extras.get("processo_administrativo_fonte"),
        "compra": {
            "ano": compra["ano_compra"],
            "sequencial": compra["sequencial_compra"],
            "titulo": compra.get("titulo"),
            "modalidade_id": compra.get("modalidade_id"),
            "modalidade": compra.get("modalidade"),
            "situacao": compra.get("situacao"),
            "tem_resultado": compra.get("tem_resultado"),
            "instrumento_convocatorio_codigo": compra.get("instrumento_convocatorio_codigo"),
            "instrumento_convocatorio": compra.get("instrumento_convocatorio"),
            "amparo_legal_codigo": compra.get("amparo_legal_codigo"),
            "amparo_legal_nome": compra.get("amparo_legal_nome"),
            "amparo_legal_descricao": compra.get("amparo_legal_descricao"),
            "srp": compra.get("srp"),
        },
        "datas": {
            "publicacao_pncp": compra.get("data_publicacao_pncp"),
            "inicio_propostas": compra.get("data_inicio_proposta"),
            "fim_propostas": compra.get("data_fim_proposta"),
        },
        "objeto": compra.get("objeto"),
        "categoria_objeto": compra.get("categoria_objeto"),
        "valores": {
            "total_estimado_itens": extras.get("valor_total_estimado_itens"),
            "total_homologado": compra.get("valor_total_homologado"),
            "quantidade_itens": extras.get("quantidade_itens"),
            "total_contratado": sum(
                c.get("valor_global") or 0 for c in contratos
            )
            or None,
        },
        "fontes": {
            "portal_pncp": url_processo(numero),
            "api_arquivos": (
                f"https://pncp.gov.br/api/pncp/v1/orgaos/{compra['cnpj_orgao']}"
                f"/compras/{compra['ano_compra']}/{compra['sequencial_compra']}/arquivos"
            ),
            "api_itens": (
                f"https://pncp.gov.br/api/pncp/v1/orgaos/{compra['cnpj_orgao']}"
                f"/compras/{compra['ano_compra']}/{compra['sequencial_compra']}/itens"
            ),
            "api_contratos_associados": (
                f"https://pncp.gov.br/api/pncp/v1/orgaos/{compra['cnpj_orgao']}"
                f"/contratos/contratacao/{compra['ano_compra']}/{compra['sequencial_compra']}"
            ),
            "itens_local": extras.get("arquivo_itens"),
            "descoberta": compra.get("origem_descoberta", "contratacoes_publicadas_pncp"),
        },
        "contratos": [
            {
                "numero_controle_pncp": contrato["numero_controle_pncp"],
                "numero_controle_pncp_compra": contrato.get("numero_controle_pncp_compra"),
                "numero_contrato": contrato.get("numero_contrato"),
                "processo_administrativo": contrato.get("processo"),
                "categoria_processo": contrato.get("categoria_processo"),
                "tipo_contrato": contrato.get("tipo_contrato"),
                "fornecedor": contrato.get("fornecedor"),
                "ni_fornecedor": contrato.get("ni_fornecedor"),
                "data_assinatura": contrato.get("data_assinatura"),
                "data_atualizacao_global": contrato.get("data_atualizacao_global"),
                "numero_retificacao": contrato.get("numero_retificacao"),
                "vigencia_inicio": contrato.get("vigencia_inicio"),
                "vigencia_fim": contrato.get("vigencia_fim"),
                "valor_global": contrato.get("valor_global"),
                "objeto": contrato.get("objeto"),
                "fonte": contrato.get("fonte", "pncp"),
                "criterio_vinculo": contrato.get("criterio_vinculo", "numeroControlePncpCompra"),
                "url_portal": _url_do_contrato(contrato),
            }
            for contrato in contratos
        ],
        "cadeia": cadeia,
        # O scope.md exige exatamente um documento por papel. O corpus registra
        # o que o órgão publicou e sinaliza quando isso não vale, em vez de
        # descartar o processo: quem consome decide o que fazer com a duplicata.
        "escopo_documental": {
            "um_documento_por_papel": all(len(cadeia[papel]) == 1 for papel in CADEIA),
            "contagem": {papel: len(cadeia[papel]) for papel in CADEIA},
        },
        "documentos": [d["documento_id"] for d in documentos],
    }


# ------------------------------------------------------------------ relatório


def _contar(processos: Sequence[dict[str, Any]], papel: str) -> int:
    return sum(1 for p in processos if p["cadeia"].get(papel))


def estatisticas(
    processos: Sequence[dict[str, Any]], documentos: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    por_papel = Counter(d["papel"] for d in documentos)
    return {
        "processos": len(processos),
        "orgaos_distintos": len({p["orgao"]["cnpj"] for p in processos}),
        "categorias_distintas": len({p["categoria_objeto"] for p in processos}),
        "esferas": dict(Counter(p["orgao"]["esfera"] for p in processos)),
        "documentos": len(documentos),
        "documentos_por_papel": dict(por_papel),
        "processos_com_tr": _contar(processos, TR),
        "processos_com_etp": _contar(processos, ETP),
        "processos_com_edital": _contar(processos, EDITAL),
        "processos_com_contrato": _contar(processos, CONTRATO),
        "processos_cadeia_completa": sum(
            1 for p in processos if all(p["cadeia"].get(papel) for papel in CADEIA)
        ),
        "documentos_abertos": sum(1 for d in documentos if d["verificacao"]["abriu"]),
        "documentos_com_texto": sum(
            1 for d in documentos if d["verificacao"]["abriu"] and not d["verificacao"]["precisa_ocr"]
        ),
        "documentos_precisam_ocr": sum(1 for d in documentos if d["verificacao"]["precisa_ocr"]),
        "categorias": dict(Counter(p["categoria_objeto"] for p in processos)),
    }
