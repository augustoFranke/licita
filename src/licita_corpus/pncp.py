"""Cliente da API pública do PNCP usado pelo coletor contract-first.

O fluxo tem uma única porta de entrada: ``/api/consulta/v1/contratos``. Cada
contrato aponta para sua contratação por ``numeroControlePncpCompra``; desse
identificador derivam o detalhe e os arquivos da compra, os contratos associados
e os arquivos do contrato. Nenhuma busca textual, UASG ou fonte externa é usada.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

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
        with self.lock:
            agora = time.monotonic()
            espera = max(0.0, self.proximo - agora)
            self.proximo = max(agora, self.proximo) + self.intervalo
        if espera:
            time.sleep(espera)


@dataclass
class Pncp:
    timeout: float = 90.0
    tentativas: int = 7
    intervalo: float = 0.75
    _client: httpx.Client = field(init=False, repr=False)
    _limitador: _Limitador = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=20.0),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
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
    ) -> Any:
        resposta = self._request(url, params)
        if resposta.status_code in (204, 404) and ausente_ok:
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

    # -------------------------------------------------------- contract-first

    def contratos_publicados(
        self,
        data_inicial: str,
        data_final: str,
        *,
        pagina_inicial: int = 1,
        tamanho_pagina: int = 50,
        max_paginas: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Itera contratos/empenhos pela data de publicação no PNCP."""
        pagina = pagina_inicial
        lidas = 0
        while max_paginas is None or lidas < max_paginas:
            payload = self._json(
                f"{CONSULTA}/contratos",
                {
                    "dataInicial": data_inicial,
                    "dataFinal": data_final,
                    "pagina": pagina,
                    "tamanhoPagina": tamanho_pagina,
                },
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise PncpError("resposta de contratos sem campo 'data' válido")
            dados = payload["data"]
            total = payload.get("totalPaginas")
            if not isinstance(total, int) or total < 0:
                raise PncpError("resposta de contratos sem 'totalPaginas' válido")
            yield from dados
            lidas += 1
            if pagina >= total:
                return
            if not dados:
                raise PncpError("paginação de contratos terminou antes de totalPaginas")
            pagina += 1

    def compra(self, cnpj: str, ano: int, sequencial: int) -> dict[str, Any] | None:
        payload = self._json(
            f"{CONSULTA}/orgaos/{cnpj}/compras/{ano}/{sequencial}", ausente_ok=True
        )
        if payload is not None and not isinstance(payload, dict):
            raise PncpError("detalhe da contratação não é um objeto")
        return payload

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
        payload = self._json(
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens",
            {"pagina": 1, "tamanhoPagina": 500},
            ausente_ok=True,
        )
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise PncpError("lista de itens inválida")
        return payload

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
