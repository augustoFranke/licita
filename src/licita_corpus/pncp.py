"""Cliente da API pública do PNCP usado pelo coletor rarest-first.

A descoberta começa no endpoint documentado de contratações por publicação,
filtrado na origem para Pregão Eletrônico. Só compras com ETP, TR e edital
publicados avançam para a consulta de contratos associados. Não há busca
textual, UASG, similaridade, scraping ou fonte externa.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

CONSULTA = "https://pncp.gov.br/api/consulta/v1"
PNCP_API = "https://pncp.gov.br/api/pncp/v1"
PORTAL = "https://pncp.gov.br/app"
USER_AGENT = "licita-corpus/0.1 (coleta de corpus de pesquisa; contato via repositorio)"


class PncpError(RuntimeError):
    """Falha da API após esgotar as retentativas ou resposta inválida."""


class PncpNotFound(PncpError):
    """Recurso definitivamente ausente (HTTP 404/204), não falha transitória."""


class _Limitador:
    def __init__(self, intervalo: float) -> None:
        self.intervalo = intervalo
        self.lock = threading.Lock()
        self.proximo = 0.0

    def esperar(self) -> None:
        # Dormir sob o lock preserva a ordem das reservas entre threads. Se o
        # sono ocorresse depois de liberar o lock, uma thread atrasada poderia
        # disparar junto da seguinte e violar o intervalo global.
        with self.lock:
            agora = time.monotonic()
            espera = max(0.0, self.proximo - agora)
            if espera:
                time.sleep(espera)
            self.proximo = time.monotonic() + self.intervalo


@dataclass
class Pncp:
    timeout: float = 90.0
    tentativas: int = 7
    intervalo: float = 0.25
    _client: httpx.Client = field(init=False, repr=False)
    _limitador: _Limitador = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=20.0),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )
        self._limitador = _Limitador(self.intervalo)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Pncp":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET com retentativas; nunca converte falha de API em coleção vazia."""
        ultimo: object = None
        for tentativa in range(1, self.tentativas + 1):
            self._limitador.esperar()
            try:
                resposta = self._client.get(url, params=params)
            except httpx.HTTPError as erro:
                ultimo = erro
            else:
                if resposta.status_code < 500 and resposta.status_code != 429:
                    return resposta
                ultimo = f"HTTP {resposta.status_code}"
            if tentativa < self.tentativas:
                espera = min(0.75 * (2 ** (tentativa - 1)), 20.0)
                time.sleep(espera + random.uniform(0.0, min(1.0, espera / 3)))
        raise PncpError(f"falha definitiva em {url} ({params}): {ultimo}")

    def _json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        ausente_ok: bool = False,
        sem_conteudo_ok: bool = False,
    ) -> Any:
        resposta = self._request(url, params)
        if resposta.status_code == 204 and (ausente_ok or sem_conteudo_ok):
            return None
        if resposta.status_code == 404 and ausente_ok:
            return None
        if resposta.status_code >= 400:
            detalhe = resposta.text[:300].replace("\n", " ")
            raise PncpError(f"HTTP {resposta.status_code} em {resposta.url}: {detalhe}")
        if not resposta.content:
            if ausente_ok:
                return None
            raise PncpError(f"resposta vazia em {resposta.url}")
        try:
            return resposta.json()
        except ValueError as erro:
            raise PncpError(f"JSON inválido em {resposta.url}") from erro

    # ---------------------------------------------------------- rarest-first

    def pagina_contratacoes_publicadas(
        self,
        data_inicial: str,
        data_final: str,
        *,
        pagina: int,
        modalidade: int = 6,
        cnpj: str | None = None,
        tamanho_pagina: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Uma página do feed oficial de contratações por publicação.

        O chamador persiste ``pagina`` em SQLite depois de processá-la. Assim,
        uma falha nunca vira lista vazia e a retomada não relê o período inteiro.
        """
        params: dict[str, Any] = {
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "codigoModalidadeContratacao": modalidade,
            "pagina": pagina,
            "tamanhoPagina": tamanho_pagina,
        }
        if cnpj:
            params["cnpj"] = cnpj
        payload = self._json(
            f"{CONSULTA}/contratacoes/publicacao", params, sem_conteudo_ok=True
        )
        if payload is None:
            return [], 0
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PncpError("resposta de contratações sem campo 'data' válido")
        total = payload.get("totalPaginas")
        if not isinstance(total, int) or total < 0:
            raise PncpError("resposta de contratações sem 'totalPaginas' válido")
        dados = payload["data"]
        if pagina <= total and not dados:
            raise PncpError("paginação de contratações terminou antes de totalPaginas")
        return dados, total

    def contratos_da_compra(
        self, cnpj: str, ano: int, sequencial: int, *, tamanho_pagina: int = 50
    ) -> list[dict[str, Any]]:
        """Consulta oficial dos contratos associados exatamente à contratação."""
        registros: list[dict[str, Any]] = []
        pagina = 1
        while True:
            payload = self._json(
                f"{PNCP_API}/orgaos/{cnpj}/contratos/contratacao/{ano}/{sequencial}",
                {"pagina": pagina, "tamanhoPagina": tamanho_pagina},
                ausente_ok=True,
            )
            if payload is None:
                return registros
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise PncpError("resposta de contratos da contratação inválida")
            dados = payload["data"]
            registros.extend(dados)
            total = payload.get("totalPaginas", 1)
            if not isinstance(total, int):
                raise PncpError("paginação dos contratos da contratação inválida")
            if pagina >= total:
                return registros
            if not dados:
                raise PncpError("paginação dos contratos da contratação interrompida")
            pagina += 1

    def arquivos_compra(self, cnpj: str, ano: int, sequencial: int) -> list[dict[str, Any]]:
        return self._lista_arquivos(f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos")

    def arquivos_contrato(self, cnpj: str, ano: int, sequencial: int) -> list[dict[str, Any]]:
        return self._lista_arquivos(
            f"{PNCP_API}/orgaos/{cnpj}/contratos/{ano}/{sequencial}/arquivos"
        )

    def _lista_arquivos(self, url: str) -> list[dict[str, Any]]:
        payload = self._json(url, ausente_ok=True)
        if payload is None:
            return []
        if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
            raise PncpError(f"lista de arquivos inválida em {url}")
        return payload

    def itens_compra(self, cnpj: str, ano: int, sequencial: int) -> list[dict[str, Any]]:
        url = f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
        itens: list[dict[str, Any]] = []
        vistos: set[str] = set()
        pagina = 1
        while True:
            payload = self._json(
                url,
                {"pagina": pagina, "tamanhoPagina": 500},
                ausente_ok=True,
            )
            if payload is None:
                return itens
            if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
                raise PncpError("lista de itens inválida")
            novos = 0
            for item in payload:
                chave = str(item.get("numeroItem") or item.get("sequencialItem") or item)
                if chave not in vistos:
                    vistos.add(chave)
                    itens.append(item)
                    novos += 1
            if len(payload) < 500:
                return itens
            if novos == 0:
                raise PncpError("paginação de itens repetiu a página anterior")
            pagina += 1

    def baixar(self, url: str) -> tuple[bytes, str | None, str | None]:
        resposta = self._request(url)
        if resposta.status_code in (204, 404):
            raise PncpNotFound(f"arquivo ausente: {url}")
        if resposta.status_code >= 400:
            raise PncpError(f"HTTP {resposta.status_code} ao baixar {url}")
        disposicao = resposta.headers.get("content-disposition", "")
        nome = None
        if "filename=" in disposicao:
            nome = disposicao.split("filename=", 1)[1].strip().strip('"').strip("'")
        return resposta.content, resposta.headers.get("content-type"), nome


# ------------------------------------------------------------ identificadores


_CONTROLE_PNCP = re.compile(r"^(\d{14})-[12]-(\d{1,10})/(\d{4})$")


def partes_controle(numero_controle_pncp: str) -> tuple[str, int, int]:
    """Valida e decompõe um número de controle oficial do PNCP."""
    achado = _CONTROLE_PNCP.fullmatch(numero_controle_pncp)
    if not achado:
        raise ValueError(f"número de controle PNCP inválido: {numero_controle_pncp!r}")
    cnpj, sequencial, ano = achado.groups()
    return cnpj, int(ano), int(sequencial)


def url_processo(numero_controle_pncp: str) -> str:
    cnpj, ano, sequencial = partes_controle(numero_controle_pncp)
    return f"{PORTAL}/editais/{cnpj}/{ano}/{sequencial}"


def url_contrato(numero_controle_pncp: str) -> str:
    cnpj, ano, sequencial = partes_controle(numero_controle_pncp)
    return f"{PORTAL}/contratos/{cnpj}/{ano}/{sequencial}"
