"""Promove processos históricos adicionando o elo CONTRATO.

O contrato é o único elo que não vem em ``arquivos_compra``: ele é assinado
depois da licitação e vive sob outro recurso do PNCP. A descoberta usa o
endpoint oficial que lista diretamente os contratos e empenhos vinculados à
contratação:

    contratos/contratacao/{ano}/{sequencial}
    ->  arquivos do contrato  ->  baixa o instrumento (tipoDocumentoNome
        "Contrato"; aditivo, empenho e apostilamento ficam de fora)

Consequências práticas, medidas:
- nem toda compra gera contrato, e compras recentes ainda não o têm;
- a API do PNCP oscila, então a consulta é limitada e retomável — o progresso fica em
  ``corpus/catalogo/contratos_encontrados.json`` e uma execução interrompida
  não perde o que já achou.

Este utilitário é uma ferramenta de promoção/reparo de processos históricos;
não é uma segunda estratégia de descoberta. A coleta de processos novos fica
em ``licita_corpus.collect.coletar`` e começa sempre pelo feed de contratos,
exigindo os quatro documentos da cadeia antes de publicar.
Processos marcados como ``OUT_OF_SCOPE``/``FORA_DO_PERFIL`` são ignorados antes
de qualquer consulta ou download de anexo.

Uso:
    uv run python tools/fetch_contratos.py --all
    uv run python tools/fetch_contratos.py --all --max-paginas 4
    uv run python tools/fetch_contratos.py <processo_id> [...]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from _corpus_sync import (
    CORPUS,
    PROCESSOS,
    ROOT,
    carregar_catalogo,
    para_publico,
    publicar,
)
from licita_corpus.classify import CONTRATO, normalizar, papel_documento_contrato
from licita_corpus.collect import _normalizar_contrato, _registrar_documento
from licita_corpus.catalog import documento_id, ocr_historico_utilizavel
from licita_corpus.pncp import Pncp, PncpError
from licita_corpus.store import baixar_documento

PROGRESSO = CORPUS / "catalogo" / "contratos_encontrados.json"


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


def _carregar_progresso() -> dict[str, Any]:
    if PROGRESSO.exists():
        return json.loads(PROGRESSO.read_text(encoding="utf-8"))
    return {}


def _salvar_progresso(dados: dict[str, Any]) -> None:
    PROGRESSO.parent.mkdir(parents=True, exist_ok=True)
    PROGRESSO.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def localizar_contrato(
    pncp: Pncp, numero_controle: str, *, max_paginas: int
) -> dict[str, Any] | None:
    """Primeiro contrato vinculado à compra, excluindo empenhos."""
    for pagina in range(1, max_paginas + 1):
        contratos, total_paginas = pncp.pagina_contratos_da_compra(
            numero_controle, pagina=pagina
        )
        for contrato in contratos:
            tipo = contrato.get("tipoContrato")
            if isinstance(tipo, Mapping):
                tipo_id = tipo.get("id")
                tipo_nome = tipo.get("nome")
            else:
                tipo_id = contrato.get("tipoContratoId")
                tipo_nome = tipo or contrato.get("tipoContratoNome")
            if str(tipo_id) == "1" or normalizar(str(tipo_nome or "")) in {
                "contrato",
                "contrato termo inicial",
                "contrato administrativo",
                "termo de contrato",
                "instrumento contratual",
            }:
                return contrato
        if pagina >= total_paginas:
            return None
    return None


def baixar_instrumento(
    pncp: Pncp,
    contrato: dict[str, Any],
    pid: str,
    numero_controle: str,
    *,
    contrato_normalizado: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Baixa o instrumento contratual e devolve o registro no formato do estado."""
    # O feed atual traz ``orgaoEntidadeCnpj`` no nível superior e pode omitir
    # ano/sequencial; o número de controle contém esses valores. Use sempre o
    # contrato normalizado, que já validou o vínculo exato com a compra, em vez
    # de depender do formato incidental da resposta crua.
    normalizado = contrato_normalizado
    if not isinstance(normalizado, Mapping):
        try:
            normalizado = _normalizar_contrato(
                contrato, {"numero_controle_pncp": numero_controle}
            )
        except ValueError:
            return None
    cnpj = normalizado.get("cnpj_orgao")
    ano = normalizado.get("ano_contrato")
    seq = normalizado.get("sequencial_contrato")
    if not (cnpj and ano and seq):
        return None

    arquivos = pncp.arquivos_contrato(cnpj, int(ano), int(seq))
    candidatos = [
        a for a in arquivos
        if a.get("statusAtivo", True)
        and (a.get("url") or a.get("uri"))
        and papel_documento_contrato(
            a.get("tipoDocumentoNome"),
            str(a.get("titulo") or ""),
            a.get("tipoDocumentoId"),
        ) == CONTRATO
    ]
    if not candidatos:
        return None

    escolhido = candidatos[0]
    titulo = f"c{seq}-{escolhido.get('titulo') or 'contrato'}"
    baixado = baixar_documento(
        pncp,
        escolhido.get("url") or escolhido.get("uri"),
        CORPUS / "documentos" / pid,
        CONTRATO,
        escolhido.get("sequencialDocumento"),
        titulo,
    )
    if baixado is None:
        return None

    arquivo = {
        "papel": CONTRATO,
        "titulo": titulo,
        "tipo_documento_pncp": escolhido.get("tipoDocumentoNome"),
        "tipo_documento_id": escolhido.get("tipoDocumentoId"),
        "url": escolhido.get("url") or escolhido.get("uri"),
        "data_publicacao_pncp": escolhido.get("dataPublicacaoPncp"),
    }
    ident = documento_id(pid, CONTRATO, escolhido.get("sequencialDocumento"), 0)
    registro = _registrar_documento(
        ident, pid, numero_controle, arquivo, baixado, CORPUS
    )
    if registro["verificacao"].get("precisa_ocr"):
        registro = _registrar_documento(
            ident, pid, numero_controle, arquivo, baixado, CORPUS, ocr=True
        )
        usavel = ocr_historico_utilizavel(
            registro, abriu=registro["verificacao"].get("abriu", False)
        )
    else:
        v = registro["verificacao"]
        usavel = bool(v.get("abriu") and int(v.get("caracteres") or 0) > 0)
    return registro if usavel else None


def enriquecer(pids: list[str], *, max_paginas: int) -> None:
    catalogo = carregar_catalogo()
    promoviveis = _processos_promoviveis()
    controle: dict[str, str] = {}
    ja_tem: set[str] = set()
    for documento in catalogo:
        controle.setdefault(documento["processo_id"], documento["numero_controle_pncp_origem"])
        if documento.get("papel") == CONTRATO:
            ja_tem.add(documento["processo_id"])

    progresso = _carregar_progresso()
    alvos = [p for p in pids if p in controle and p not in ja_tem]
    fora_perfil = [
        p for p in alvos
        if p not in promoviveis
    ]
    for p in fora_perfil:
        print(f"[ignorado] {p}: processo fora do perfil, sem download")
    alvos = [p for p in alvos if p not in fora_perfil]
    for pid in pids:
        if pid in ja_tem:
            print(f"[ok-já-existe] {pid}: CONTRATO já no catálogo")

    novos: list[dict[str, Any]] = []
    para_estado: dict[str, dict[str, Any]] = {}
    contratos_estado: dict[str, dict[str, Any]] = {}
    with Pncp(timeout=45.0, tentativas=3, intervalo=0.5) as pncp:
        for pid in alvos:
            numero = controle[pid]
            try:
                contrato = localizar_contrato(pncp, numero, max_paginas=max_paginas)
            except PncpError as erro:
                # A API de consulta do PNCP oscila; a falha é registrada e a
                # varredura continua, para uma instabilidade não derrubar o lote.
                print(f"[falha-api] {pid}: {str(erro)[:90]}")
                progresso[pid] = {"status": "falha_api"}
                continue

            if contrato is None:
                print(f"[sem-contrato] {pid}: nenhum contrato aponta para esta compra")
                progresso[pid] = {"status": "sem_contrato"}
                continue

            try:
                contrato_normalizado = _normalizar_contrato(
                    contrato, {"numero_controle_pncp": numero}
                )
            except ValueError as erro:
                print(f"[contrato-invalido] {pid}: {erro}")
                progresso[pid] = {
                    "status": "contrato_invalido",
                    "motivo": str(erro),
                }
                continue

            progresso[pid] = {
                "status": "encontrado",
                "contrato": contrato.get("numeroControlePNCP"),
                "assinatura": contrato.get("dataAssinatura"),
                "valor_global": contrato.get("valorGlobal"),
            }
            _salvar_progresso(progresso)

            try:
                registro = baixar_instrumento(
                    pncp,
                    contrato,
                    pid,
                    numero,
                    contrato_normalizado=contrato_normalizado,
                )
            except PncpError as erro:
                print(f"[falha-download] {pid}: {str(erro)[:90]}")
                continue
            if registro is None:
                print(f"[sem-arquivo] {pid}: contrato sem instrumento baixável e utilizável")
                progresso[pid]["status"] = "sem_arquivo"
                continue

            publico = para_publico(registro)
            novos.append(publico)
            para_estado[pid] = registro
            contratos_estado[pid] = contrato_normalizado
            print(
                f"[contrato+] {pid}: {publico['arquivo']} "
                f"({publico['bytes']} bytes, {registro['verificacao'].get('caracteres')} chars)"
            )

    _salvar_progresso(progresso)
    publicar(novos, para_estado, contratos_por_processo=contratos_estado)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pids", nargs="*", help="processo_id(s) explícitos")
    ap.add_argument("--all", action="store_true", help="todos os processos do catálogo")
    ap.add_argument(
        "--max-paginas",
        type=int,
        default=4,
        help="compatibilidade; o endpoint oficial de contratos vinculados não é paginado",
    )
    args = ap.parse_args()

    if args.all:
        pids = sorted({d["processo_id"] for d in carregar_catalogo()})
    else:
        pids = args.pids
    if not pids:
        ap.error("informe --all ou processo_id(s)")
    enriquecer(pids, max_paginas=args.max_paginas)


if __name__ == "__main__":
    main()
