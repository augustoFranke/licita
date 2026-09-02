"""Catálogo local dos documentos coletados.

Novas coletas publicam uma cadeia completa (ETP, TR, EDITAL e CONTRATO). Os
processos históricos existentes, inclusive os que só têm ETP/TR, continuam
legíveis e são mantidos como exceção de compatibilidade até que seus elos
faltantes sejam promovidos.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable, Sequence

from .classify import (
    CONTRATO,
    DFD,
    EDITAL,
    ETP,
    PESQUISA_PRECOS,
    PERFIL_PUBLICO_14133_PREGAO_ELETRONICO_BENS,
    PERFIL_SUPPORTED,
    TR,
    classificar_perfil_inicial,
)
from .pncp import url_contrato, url_processo

CADEIA = (DFD, ETP, TR, EDITAL, CONTRATO, PESQUISA_PRECOS)
#: Papéis exigidos pela coleta vigente, em ordem documental.
PAPEIS_CADEIA_COMPLETA = (ETP, TR, EDITAL, CONTRATO)
PAPEIS_OBRIGATORIOS = PAPEIS_CADEIA_COMPLETA
#: Papéis que podem ser acrescentados por ferramentas de promoção de registros
#: históricos. Eles não são opcionais para uma coleta nova: nessa coleta todos
#: os quatro papéis abaixo são obrigatórios.
PAPEIS_OPCIONAIS = (EDITAL, CONTRATO)
PAPEIS_OPCIONAIS_HISTORICOS = PAPEIS_OPCIONAIS
PAPEIS_DO_LOTE = PAPEIS_CADEIA_COMPLETA
#: ETP/TR continuam sendo o par compartilhado por regras de comparação e por
#: catálogos históricos.
PAPEIS_PAR_ETP_TR = (ETP, TR)
PAPEIS_MATERIAIS = (ETP, TR, EDITAL, CONTRATO)
CRITERIO_VINCULO_CONTRATO = "numeroControlePncpCompra"


def metadados_verificacao(
    documento: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Separa verificação e metadados de OCR de um registro de documento."""
    verificacao_bruta = documento.get("verificacao")
    verificacao = verificacao_bruta if isinstance(verificacao_bruta, Mapping) else {}
    ocr_bruto = verificacao.get("ocr") or documento.get("ocr")
    ocr = ocr_bruto if isinstance(ocr_bruto, Mapping) else {}
    return verificacao, ocr


def ocr_historico_utilizavel(documento: Mapping[str, Any], *, abriu: bool) -> bool:
    """Decide se o texto de OCR histórico de um documento pode ser usado.

    Fonte única da coleta e do gate: um texto derivado só conta quando é
    auditável (SHA-256 do derivado, versão do pipeline e idioma registrados),
    conforme a policy ``4-municipal-historical-ocr``. Coletar sob um critério
    mais frouxo do que o do gate deixa entrar no corpus documento que o gate
    depois rejeita.
    """
    verificacao, ocr = metadados_verificacao(documento)
    cache_bruto = verificacao.get("ocr_cache") or documento.get("ocr_cache")
    cache = cache_bruto if isinstance(cache_bruto, Mapping) else {}
    texto_sha256 = str(cache.get("texto_sha256") or "").strip().lower()
    derivado_auditavel = bool(
        re.fullmatch(r"[0-9a-f]{64}", texto_sha256)
        and str(cache.get("pipeline_version") or "").strip()
        and str(cache.get("idioma") or "").strip()
    )
    usado = bool(
        verificacao.get("ocr_usado")
        or documento.get("ocr_usado")
        or ocr.get("usado")
    )
    try:
        caracteres = int(
            verificacao.get("caracteres", documento.get("caracteres", 0)) or 0
        )
    except (TypeError, ValueError):
        caracteres = 0
    texto = (
        documento.get("_texto")
        or verificacao.get("texto")
        or documento.get("texto")
        or ""
    )
    precisa_ocr = bool(
        verificacao.get("precisa_ocr", documento.get("precisa_ocr", False))
    )
    return bool(
        abriu
        and usado
        and derivado_auditavel
        and (caracteres > 0 or str(texto).strip())
        and not precisa_ocr
    )


def escrever_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def escrever_jsonl(caminho: Path, registros: Iterable[dict[str, Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as saida:
        for registro in registros:
            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")


def documento_id(
    processo_id: str, papel: str, sequencial: int | None, ordem: int
) -> str:
    return f"{processo_id}#{papel.lower()}-{sequencial if sequencial is not None else ordem:02d}"


def montar_relacoes(
    processo_id: str, cadeia: dict[str, list[str]]
) -> list[dict[str, str]]:
    """Liga os elos presentes, atravessando elos ausentes.

    A coleta nova produz as quatro arestas consecutivas da cadeia. A travessia
    também mantém compatibilidade com catálogos históricos que ainda têm só o
    par ETP/TR ou que receberam algum elo por enriquecimento.
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
                        "relacao": "origina" if (origem, destino) == (ETP, TR) else "precede_em",
                    }
                )
    return arestas


def _url_do_contrato(contrato: dict[str, Any]) -> str:
    return url_contrato(contrato["numero_controle_pncp"])


def _contrato_vincula_processo(processo: Mapping[str, Any]) -> bool:
    """Confere o vínculo explícito de ao menos um contrato à compra.

    Os quatro papéis documentais, sozinhos, não provam a cadeia exigida pela
    coleta vigente: o instrumento contratual precisa apontar para a mesma
    contratação pelo campo canônico do PNCP. Catálogos históricos podem não
    ter esse metadado e continuam válidos como histórico, mas não como cadeia
    nova/completa.
    """
    numero_compra = str(processo.get("numero_controle_pncp") or "").strip()
    contratos = processo.get("contratos")
    if not isinstance(contratos, Sequence) or isinstance(contratos, (str, bytes)):
        return False
    return any(
        isinstance(contrato, Mapping)
        and str(contrato.get("numero_controle_pncp_compra") or "").strip()
        == numero_compra
        and contrato.get("criterio_vinculo") == CRITERIO_VINCULO_CONTRATO
        for contrato in contratos
    )


def montar_processo(
    compra: dict[str, Any],
    extras: dict[str, Any] | None,
    documentos: Sequence[dict[str, Any]],
    contratos: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Monta o registro canônico para um par histórico ou cadeia completa."""
    numero = compra["numero_controle_pncp"]
    identificador = numero.replace("/", "-")
    extras = extras or {}

    cadeia: dict[str, list[str]] = {papel: [] for papel in CADEIA}
    for documento in documentos:
        if documento.get("papel") in cadeia:
            cadeia[documento["papel"]].append(documento["documento_id"])

    contratos_registrados = [
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
            "criterio_vinculo": contrato.get(
                "criterio_vinculo", "numeroControlePncpCompra"
            ),
            "url_portal": _url_do_contrato(contrato),
        }
        for contrato in contratos
    ]
    processo_administrativo = extras.get(
        "processo_administrativo", compra.get("processo")
    )
    processo_fonte = extras.get(
        "processo_administrativo_fonte",
        "detalhe_publico_pncp" if compra.get("processo") else None,
    )
    total_estimado = extras.get("valor_total_estimado_itens", compra.get("valor_global"))
    quantidade_itens = extras.get("quantidade_itens")
    total_contratado = sum(c.get("valor_global") or 0 for c in contratos) or None
    contrato_vinculado = bool(contratos_registrados) and any(
        str(contrato.get("numero_controle_pncp_compra") or "").strip()
        == str(numero).strip()
        and contrato.get("criterio_vinculo") == CRITERIO_VINCULO_CONTRATO
        for contrato in contratos_registrados
    )

    perfil_status = classificar_perfil_inicial(
        esfera=compra.get("esfera"),
        amparo_legal_nome=compra.get("amparo_legal_nome"),
        modalidade_id=compra.get("modalidade_id"),
        objeto=compra.get("objeto") or "",
    )

    return {
        "processo_id": identificador,
        "numero_controle_pncp": numero,
        "orgao": {
            "cnpj": compra.get("cnpj_orgao"),
            "razao_social": compra.get("orgao"),
            "esfera": compra.get("esfera"),
            "poder": compra.get("poder"),
            "unidade": compra.get("unidade"),
            "uf": compra.get("uf"),
            "municipio": compra.get("municipio"),
        },
        "processo_administrativo": processo_administrativo,
        "processo_administrativo_fonte": processo_fonte,
        "compra": {
            "ano": compra.get("ano_compra"),
            "sequencial": compra.get("sequencial_compra"),
            "titulo": compra.get("titulo"),
            "modalidade_id": compra.get("modalidade_id"),
            "modalidade": compra.get("modalidade"),
            "instrumento_convocatorio_codigo": compra.get(
                "instrumento_convocatorio_codigo"
            ),
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
        "objeto": compra.get("objeto") or "",
        "categoria_objeto": compra.get("categoria_objeto"),
        "valores": {
            "total_estimado": compra.get("valor_global"),
            "total_estimado_itens": total_estimado,
            "quantidade_itens": quantidade_itens,
            "total_homologado": compra.get("valor_total_homologado"),
            "total_contratado": total_contratado,
        },
        "fontes": {
            "portal_pncp": url_processo(numero),
            "api_detalhe_pncp": compra.get("url_detalhe_pncp"),
            "api_arquivos": compra.get("url_arquivos_pncp"),
            "descoberta": compra.get("origem_descoberta"),
        },
        "contratos": contratos_registrados,
        # Campos novos são aditivos; ``perfil_inicial`` permanece como alias
        # de compatibilidade para consumidores do catálogo anterior.
        "perfil_id": PERFIL_PUBLICO_14133_PREGAO_ELETRONICO_BENS,
        "perfil_status": perfil_status,
        "perfil_inicial": perfil_status,
        "scope_status": (
            "SUPPORTED" if perfil_status == PERFIL_SUPPORTED else "OUT_OF_SCOPE"
        ),
        "cadeia": cadeia,
        "escopo_documental": {
            "par_etp_tr_valido": all(
                len(cadeia[papel]) == 1 for papel in PAPEIS_PAR_ETP_TR
            ),
            "um_documento_por_papel": all(
                len(cadeia[papel]) == 1 for papel in PAPEIS_MATERIAIS
            ),
            "cadeia_completa": all(
                len(cadeia[papel]) == 1 for papel in PAPEIS_CADEIA_COMPLETA
            ) and contrato_vinculado,
            "contagem": {papel: len(cadeia[papel]) for papel in CADEIA},
        },
        "documentos": [d["documento_id"] for d in documentos],
        "extras": extras,
    }


def _contar(processos: Sequence[dict[str, Any]], papel: str) -> int:
    return sum(1 for p in processos if p.get("cadeia", {}).get(papel))


def estatisticas(
    processos: Sequence[dict[str, Any]], documentos: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    por_papel = Counter(d.get("papel") for d in documentos)
    elegiveis = []
    for processo in processos:
        scope_status = processo.get("scope_status")
        if scope_status is not None:
            supported = scope_status == "SUPPORTED"
        else:
            supported = (
                processo.get("perfil_status") == PERFIL_SUPPORTED
                or processo.get("perfil_inicial") == PERFIL_SUPPORTED
            )
        if supported:
            elegiveis.append(processo)
    return {
        "processos": len(processos),
        "processos_elegiveis": len(elegiveis),
        "processos_out_of_scope": len(processos) - len(elegiveis),
        "orgaos_distintos": len(
            {p.get("orgao", {}).get("cnpj") for p in processos} - {None, ""}
        ),
        "orgaos_distintos_elegiveis": len(
            {p.get("orgao", {}).get("cnpj") for p in elegiveis} - {None, ""}
        ),
        "categorias_distintas": len(
            {p.get("categoria_objeto") for p in processos} - {None, ""}
        ),
        "categorias_distintas_elegiveis": len(
            {p.get("categoria_objeto") for p in elegiveis} - {None, ""}
        ),
        "esferas": dict(
            Counter(p.get("orgao", {}).get("esfera") for p in processos)
        ),
        "documentos": len(documentos),
        "documentos_por_papel": dict(por_papel),
        "processos_com_tr": _contar(processos, TR),
        "processos_com_etp": _contar(processos, ETP),
        "processos_com_edital": _contar(processos, EDITAL),
        "processos_com_contrato": _contar(processos, CONTRATO),
        "processos_com_par_etp_tr": sum(
            1
            for p in processos
            if all(p.get("cadeia", {}).get(papel) for papel in PAPEIS_PAR_ETP_TR)
        ),
        "processos_elegiveis_com_par_etp_tr": sum(
            1
            for p in elegiveis
            if all(p.get("cadeia", {}).get(papel) for papel in PAPEIS_PAR_ETP_TR)
        ),
        "processos_cadeia_completa": sum(
            1
            for p in processos
            if all(p.get("cadeia", {}).get(papel) for papel in PAPEIS_CADEIA_COMPLETA)
            and _contrato_vincula_processo(p)
        ),
        "documentos_abertos": sum(
            1 for d in documentos if d.get("verificacao", {}).get("abriu")
        ),
        "documentos_com_texto": sum(
            1
            for d in documentos
            if d.get("verificacao", {}).get("abriu")
            and not d.get("verificacao", {}).get("precisa_ocr")
        ),
        "documentos_precisam_ocr": sum(
            1 for d in documentos if d.get("verificacao", {}).get("precisa_ocr")
        ),
        "categorias": dict(
            Counter(
                p.get("categoria_objeto")
                for p in processos
                if p.get("categoria_objeto")
            )
        ),
        "categorias_elegiveis": dict(
            Counter(
                p.get("categoria_objeto")
                for p in elegiveis
                if p.get("categoria_objeto")
            )
        ),
    }
