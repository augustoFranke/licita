"""Enriquece o corpus com o CONTRATO de cada processo já coletado.

O contrato é o único elo que não vem em ``arquivos_compra``: ele é assinado
depois da licitação e vive sob outro recurso do PNCP. Não existe endpoint que
devolva "os contratos desta compra" — o vínculo é o campo
``numeroControlePncpCompra`` de cada contrato do feed. Foi verificado que
``/orgaos/{cnpj}/compras/{ano}/{seq}/contratos`` devolve vazio, então a
descoberta é necessariamente por varredura filtrada:

    feed de contratos do órgão (cnpjOrgao)  ->  casa numeroControlePncpCompra
    ->  arquivos do contrato  ->  baixa o instrumento (tipoDocumentoNome
        "Contrato"; aditivo, empenho e apostilamento ficam de fora)

Consequências práticas, medidas:
- nem toda compra gera contrato, e compras recentes ainda não o têm;
- o feed é paginado em 500 e a API de consulta do PNCP oscila, então a
  varredura é limitada por página e retomável — o progresso fica em
  ``corpus/catalogo/contratos_encontrados.json`` e uma execução interrompida
  não perde o que já achou.

Uso:
    uv run python tools/fetch_contratos.py --all
    uv run python tools/fetch_contratos.py --all --max-paginas 4
    uv run python tools/fetch_contratos.py <processo_id> [...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _corpus_sync import (
    CORPUS,
    ROOT,
    carregar_catalogo,
    para_publico,
    publicar,
)
from licita_corpus.classify import CONTRATO, papel_documento_contrato
from licita_corpus.collect import _registrar_documento
from licita_corpus.catalog import documento_id, ocr_historico_utilizavel
from licita_corpus.pncp import CONSULTA, Pncp, PncpError, partes_controle
from licita_corpus.store import baixar_documento

PROGRESSO = CORPUS / "catalogo" / "contratos_encontrados.json"


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
    """Contrato cujo ``numeroControlePncpCompra`` é esta compra, ou ``None``.

    A janela vai do ano da compra ao ano seguinte: o contrato é assinado depois
    da licitação e pode atravessar o exercício.
    """
    cnpj, ano, _seq = partes_controle(numero_controle)
    for pagina in range(1, max_paginas + 1):
        payload = pncp._http.json(
            f"{CONSULTA}/contratos",
            {
                "dataInicial": f"{ano}0101",
                "dataFinal": f"{ano + 1}1231",
                "cnpjOrgao": cnpj,
                "pagina": pagina,
            },
            sem_conteudo_ok=True,
            ausente_ok=True,
        )
        if not isinstance(payload, dict):
            return None
        dados = payload.get("data") or []
        for contrato in dados:
            if contrato.get("numeroControlePncpCompra") == numero_controle:
                return contrato
        if pagina >= int(payload.get("totalPaginas") or 1):
            return None
    return None


def baixar_instrumento(
    pncp: Pncp, contrato: dict[str, Any], pid: str, numero_controle: str
) -> dict[str, Any] | None:
    """Baixa o instrumento contratual e devolve o registro no formato do estado."""
    cnpj = (contrato.get("orgaoEntidade") or {}).get("cnpj")
    ano = contrato.get("anoContrato")
    seq = contrato.get("sequencialContrato")
    if not (cnpj and ano and seq):
        return None

    arquivos = pncp.arquivos_contrato(cnpj, int(ano), int(seq))
    candidatos = [
        a for a in arquivos
        if a.get("statusAtivo", True)
        and (a.get("url") or a.get("uri"))
        and papel_documento_contrato(
            a.get("tipoDocumentoNome"), str(a.get("titulo") or "")
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
    controle: dict[str, str] = {}
    ja_tem: set[str] = set()
    for documento in catalogo:
        controle.setdefault(documento["processo_id"], documento["numero_controle_pncp_origem"])
        if documento.get("papel") == CONTRATO:
            ja_tem.add(documento["processo_id"])

    progresso = _carregar_progresso()
    alvos = [p for p in pids if p in controle and p not in ja_tem]
    for pid in pids:
        if pid in ja_tem:
            print(f"[ok-já-existe] {pid}: CONTRATO já no catálogo")

    novos: list[dict[str, Any]] = []
    para_estado: dict[str, dict[str, Any]] = {}
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

            progresso[pid] = {
                "status": "encontrado",
                "contrato": contrato.get("numeroControlePNCP"),
                "assinatura": contrato.get("dataAssinatura"),
                "valor_global": contrato.get("valorGlobal"),
            }
            _salvar_progresso(progresso)

            try:
                registro = baixar_instrumento(pncp, contrato, pid, numero)
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
            print(
                f"[contrato+] {pid}: {publico['arquivo']} "
                f"({publico['bytes']} bytes, {registro['verificacao'].get('caracteres')} chars)"
            )

    _salvar_progresso(progresso)
    publicar(novos, para_estado)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pids", nargs="*", help="processo_id(s) explícitos")
    ap.add_argument("--all", action="store_true", help="todos os processos do catálogo")
    ap.add_argument(
        "--max-paginas",
        type=int,
        default=4,
        help="páginas do feed varridas por processo (500 contratos cada)",
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
