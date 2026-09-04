"""Clientes das APIs públicas usadas pela coleta de cadeias completas.

O ponto de entrada da coleta é o feed de contratos do PNCP. Cada registro do
feed aponta para uma contratação por ``numeroControlePNCPCompra``; o detalhe da
contratação fornece os metadados de perfil e a lista de anexos com ETP, TR e
edital. O instrumento contratual vem da lista de arquivos do próprio contrato.

Compras.gov.br e a busca textual do portal continuam expostos para consumidores
legados, mas não fazem parte da estratégia de coleta vigente.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass
from email.message import Message
from typing import Any, Callable

import httpx

CONSULTA = "https://pncp.gov.br/api/consulta/v1"
PNCP_API = "https://pncp.gov.br/api/pncp/v1"
PORTAL = "https://pncp.gov.br/app"
COMPRAS_API = "https://dadosabertos.compras.gov.br"
BUSCA_PNCP = "https://pncp.gov.br/api/search/"
USER_AGENT = "licita-etp-tr/0.2 (public-data-research; contact-via-repository)"


class PncpError(RuntimeError):
    """Falha da API depois das retentativas ou resposta inválida."""


class PncpNotFound(PncpError):
    """Recurso não publicado ou removido (HTTP 404/204)."""


class _IntervaloGlobal:
    """Limitador único compartilhado entre PNCP e Compras.gov.br."""

    def __init__(self, intervalo: float) -> None:
        self.intervalo = max(0.0, intervalo)
        self.lock = threading.Lock()
        self.proximo = 0.0

    def esperar(self) -> None:
        with self.lock:
            agora = time.monotonic()
            espera = max(0.0, self.proximo - agora)
            if espera:
                time.sleep(espera)
            self.proximo = time.monotonic() + self.intervalo


class ClientePublico:
    """Transporte HTTP conservador, com retry e orçamento opcional."""

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        tentativas: int = 5,
        intervalo: float = 0.75,
        reservar: Callable[[], int] | None = None,
        throttle: _IntervaloGlobal | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout = timeout
        self.tentativas = max(1, tentativas)
        self.reservar = reservar
        self.throttle = throttle or _IntervaloGlobal(intervalo)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=20.0),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            follow_redirects=True,
            # O gateway do PNCP encerra conexões ociosas com frequência. Não
            # reutilizar keep-alive evita que a próxima página herde um socket
            # morto e pare a varredura inteira.
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
        )
        self._fecha_client = client is None

    def close(self) -> None:
        if self._fecha_client:
            self._client.close()

    def _espera_retry(self, tentativa: int, resposta: httpx.Response | None) -> None:
        if resposta is not None:
            valor = resposta.headers.get("retry-after")
            if valor:
                try:
                    time.sleep(min(60.0, max(0.0, float(valor))))
                    return
                except ValueError:
                    pass
        base = min(1.0 * (2 ** (tentativa - 1)), 20.0)
        time.sleep(base + random.uniform(0.0, min(1.0, base / 3)))

    def _request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        ausente_ok: bool = False,
        sem_conteudo_ok: bool = False,
    ) -> httpx.Response | None:
        ultimo: object = None
        for tentativa in range(1, self.tentativas + 1):
            if self.reservar is not None:
                self.reservar()
            self.throttle.esperar()
            try:
                resposta = self._client.get(url, params=params)
            except (httpx.HTTPError, OSError) as erro:
                ultimo = erro
                resposta = None
                if self._fecha_client:
                    # Reabre o transporte para não repetir um reset de conexão
                    # causado por um keep-alive inválido no gateway público.
                    self._client.close()
                    self._client = httpx.Client(
                        timeout=httpx.Timeout(self.timeout, connect=20.0),
                        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                        follow_redirects=True,
                        limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
                    )
            else:
                if resposta.status_code == 204:
                    if ausente_ok or sem_conteudo_ok:
                        return None
                    ultimo = "HTTP 204"
                elif resposta.status_code == 404 and ausente_ok:
                    return None
                elif resposta.status_code == 429 or resposta.status_code >= 500:
                    ultimo = f"HTTP {resposta.status_code}"
                elif resposta.status_code >= 400:
                    detalhe = resposta.text[:300].replace("\n", " ")
                    raise PncpError(
                        f"HTTP {resposta.status_code} em {resposta.url}: {detalhe}"
                    )
                else:
                    return resposta
            if tentativa < self.tentativas:
                self._espera_retry(tentativa, resposta)
        raise PncpError(f"falha definitiva em {url} ({params}): {ultimo}")

    def json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        ausente_ok: bool = False,
        sem_conteudo_ok: bool = False,
    ) -> Any:
        resposta = self._request(
            url,
            params,
            ausente_ok=ausente_ok,
            sem_conteudo_ok=sem_conteudo_ok,
        )
        if resposta is None:
            return None
        if not resposta.content:
            if ausente_ok or sem_conteudo_ok:
                return None
            raise PncpError(f"resposta vazia em {resposta.url}")
        try:
            return resposta.json()
        except ValueError as erro:
            raise PncpError(f"JSON inválido em {resposta.url}") from erro

    def bytes(self, url: str) -> tuple[bytes, str | None, str | None]:
        resposta = self._request(url)
        if resposta is None or resposta.status_code in (204, 404):
            raise PncpNotFound(f"arquivo ausente: {url}")
        disposicao = resposta.headers.get("content-disposition", "")
        nome = _nome_disposicao(disposicao)
        return resposta.content, resposta.headers.get("content-type"), nome


def _nome_disposicao(valor: str) -> str | None:
    if not valor:
        return None
    mensagem = Message()
    mensagem["content-disposition"] = valor
    nome = mensagem.get_param("filename", header="content-disposition")
    return str(nome) if nome else None


class Pncp:
    """Endpoints públicos do PNCP necessários para uma cadeia completa."""

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        tentativas: int = 5,
        intervalo: float = 0.75,
        reservar: Callable[[], int] | None = None,
        throttle: _IntervaloGlobal | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._http = ClientePublico(
            timeout=timeout,
            tentativas=tentativas,
            intervalo=intervalo,
            reservar=reservar,
            throttle=throttle,
            client=client,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Pncp":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def busca_portal(
        self,
        termo: str,
        *,
        pagina: int,
        tamanho_pagina: int = 50,
        tipo: str = "edital",
    ) -> tuple[list[dict[str, Any]], int]:
        """Acelerador público usado pelo portal; não substitui a confirmação."""
        if not 1 <= tamanho_pagina <= 50:
            raise ValueError("a busca do portal aceita no máximo 50 resultados")
        payload = self._http.json(
            BUSCA_PNCP,
            {
                "q": termo,
                "tipos_documento": tipo,
                "pagina": pagina,
                "tam_pagina": tamanho_pagina,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise PncpError("resposta da busca do PNCP sem 'items' válido")
        total = payload.get("total")
        if not isinstance(total, int) or total < 0:
            raise PncpError("resposta da busca do PNCP sem 'total' válido")
        return payload["items"], total

    def detalhe_compra(self, cnpj: str, ano: int, sequencial: int) -> dict[str, Any]:
        payload = self._http.json(
            f"{CONSULTA}/orgaos/{cnpj}/compras/{ano}/{sequencial}"
        )
        if not isinstance(payload, dict):
            raise PncpError("detalhe de contratação inválido")
        return payload

    def pagina_contratacoes_publicadas(
        self,
        data_inicial: str,
        data_final: str,
        *,
        pagina: int,
        modalidade: int = 6,
        uf: str | None = None,
        cnpj: str | None = None,
        tamanho_pagina: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fallback oficial documentado do PNCP (até 500 por página)."""
        if not 1 <= tamanho_pagina <= 500:
            raise ValueError("tamanho_pagina deve estar entre 1 e 500")
        params: dict[str, Any] = {
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "codigoModalidadeContratacao": modalidade,
            "pagina": pagina,
            "tamanhoPagina": tamanho_pagina,
        }
        if uf:
            params["uf"] = uf
        if cnpj:
            params["cnpj"] = cnpj
        payload = self._http.json(
            f"{CONSULTA}/contratacoes/publicacao",
            params,
            sem_conteudo_ok=True,
        )
        if payload is None:
            return [], 0
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PncpError("resposta do feed do PNCP sem 'data' válido")
        total = payload.get("totalPaginas")
        if not isinstance(total, int) or total < 0:
            raise PncpError("resposta do feed do PNCP sem 'totalPaginas' válido")
        dados = payload["data"]
        if pagina <= total and not dados:
            raise PncpError("paginação do feed terminou antes de totalPaginas")
        return dados, total

    def arquivos_compra(
        self, cnpj: str, ano: int, sequencial: int
    ) -> list[dict[str, Any]]:
        payload = self._http.json(
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos",
            ausente_ok=True,
        )
        if payload is None:
            return []
        if isinstance(payload, dict):
            payload = payload.get("documentos", payload.get("Documentos"))
        if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
            raise PncpError("lista de arquivos da contratação inválida")
        return payload

    def arquivos_contrato(
        self, cnpj: str, ano: int, sequencial: int
    ) -> list[dict[str, Any]]:
        """Arquivos publicados sob um contrato.

        Os anexos de contrato vêm com ``tipoDocumentoId`` nulo; o papel sai de
        ``tipoDocumentoNome`` (ver ``classify.papel_documento_contrato``).
        """
        payload = self._http.json(
            f"{PNCP_API}/orgaos/{cnpj}/contratos/{ano}/{sequencial}/arquivos",
            ausente_ok=True,
        )
        if payload is None:
            return []
        if isinstance(payload, dict):
            payload = payload.get("documentos", payload.get("Documentos"))
        if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
            raise PncpError("lista de arquivos do contrato inválida")
        return payload

    def pagina_contratos_da_compra(
        self, numero_controle_compra: str, *, pagina: int = 1
    ) -> tuple[list[dict[str, Any]], int]:
        """Contratos/empenhos vinculados diretamente a uma contratação.

        O serviço devolve uma lista de contratos, mas o gateway exige
        ``pagina`` na query string. A primeira chamada devolve a lista e
        informa um total lógico de uma página. Também aceitamos o envelope
        ``{"data": [...], "totalPaginas": n}`` produzido por gateways antigos,
        sem exigir esse formato do endpoint oficial.
        """
        if pagina < 1:
            raise ValueError("pagina deve ser positiva")
        cnpj, ano, sequencial = partes_controle(numero_controle_compra)
        payload = self._http.json(
            f"{PNCP_API}/orgaos/{cnpj}/contratos/contratacao/{ano}/{sequencial}",
            {"pagina": pagina},
            sem_conteudo_ok=True,
            ausente_ok=True,
        )
        if payload is None:
            return [], 0
        if isinstance(payload, list):
            contratos = payload
            total_paginas = 1 if contratos else 0
        elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
            contratos = payload["data"]
            # O envelope não é o formato do manual, mas alguns gateways
            # legados ainda o devolvem. Preserve seu total quando presente;
            # sem total, a lista inteira é uma única página.
            if "totalPaginas" in payload:
                total_paginas = payload["totalPaginas"]
            elif "total" in payload:
                total_paginas = payload["total"]
            else:
                total_paginas = 1 if contratos else 0
            if not isinstance(total_paginas, int) or total_paginas < 0:
                raise PncpError("resposta de contratos sem total válido")
        else:
            raise PncpError("resposta de contratos da contratação inválida")
        if not all(isinstance(contrato, dict) for contrato in contratos):
            raise PncpError("lista de contratos da contratação inválida")
        if pagina <= total_paginas and not contratos and total_paginas > 0:
            raise PncpError(
                "resposta de contratos da contratação terminou antes do total"
            )
        if pagina > 1:
            # A resposta em lista não oferece paginação real. Envelopes
            # legados que anunciam mais páginas não devem fazer o promotor
            # processar a mesma lista repetidamente.
            return [], total_paginas
        return contratos, int(total_paginas)

    def pagina_contratos_publicados(
        self,
        data_inicial: str,
        data_final: str,
        *,
        pagina: int,
        tamanho_pagina: int | None = None,
        uf: str | None = None,
        cnpj: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Lê uma página do feed oficial de contratos do PNCP.

        O feed é a raiz da estratégia atual: contratos publicados já contêm o
        vínculo ``numeroControlePNCPCompra`` e, portanto, não exigem uma
        varredura separada para descobrir contratos de cada compra. O PNCP
        aceita ``tamanhoPagina`` em instalações que o expõem; quando omitido,
        preservamos o formato mínimo aceito pelo gateway público.
        """
        if pagina < 1:
            raise ValueError("pagina deve ser positiva")
        if tamanho_pagina is not None and not 1 <= tamanho_pagina <= 500:
            raise ValueError("tamanho_pagina deve estar entre 1 e 500")
        params: dict[str, Any] = {
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "pagina": pagina,
        }
        if tamanho_pagina is not None:
            params["tamanhoPagina"] = tamanho_pagina
        if uf:
            params["uf"] = uf
        if cnpj:
            params["cnpjOrgao"] = cnpj
        payload = self._http.json(
            f"{CONSULTA}/contratos",
            params,
            sem_conteudo_ok=True,
            ausente_ok=True,
        )
        if payload is None:
            return [], 0
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PncpError("resposta do feed de contratos sem 'data' válido")
        contratos = payload["data"]
        if not all(isinstance(contrato, dict) for contrato in contratos):
            raise PncpError("lista do feed de contratos inválida")
        total = payload.get("totalPaginas")
        if not isinstance(total, int) or total < 0:
            # Algumas respostas antigas usavam ``total`` para indicar a
            # quantidade de páginas. Aceitamos o alias, mas nunca inferimos
            # um total a partir de uma lista vazia.
            total = payload.get("total")
        if not isinstance(total, int) or total < 0:
            raise PncpError("resposta do feed de contratos sem total válido")
        if pagina <= total and not contratos:
            raise PncpError("paginação do feed de contratos terminou antes do total")
        return contratos, total

    # Aliases explícitos facilitam integrações pequenas sem reintroduzir uma
    # segunda estratégia: todos apontam para o mesmo endpoint e contrato.
    pagina_feed_contratos = pagina_contratos_publicados
    feed_contratos = pagina_contratos_publicados

    def contratos_da_compra(
        self,
        numero_controle_compra: str,
        *,
        data_inicial: str,
        data_final: str,
        cnpj_orgao: str | None = None,
        pagina: int = 1,
    ) -> list[dict[str, Any]]:
        """Compatibilidade: filtra uma página do mesmo feed por compra.

        A coleta vigente não chama este método nem faz uma consulta dedicada
        por contratação. Ele permanece para consumidores legados, mas delega
        ao único endpoint de descoberta e aceita o nome oficial
        ``numeroControlePNCPCompra`` (além do alias usado por integrações
        antigas).
        """
        contratos, _total = self.pagina_contratos_publicados(
            data_inicial,
            data_final,
            pagina=pagina,
            cnpj=cnpj_orgao,
        )
        return [
            contrato
            for contrato in contratos
            if (
                contrato.get("numeroControlePNCPCompra")
                or contrato.get("numeroControlePncpCompra")
                or contrato.get("numero_controle_pncp_compra")
            )
            == numero_controle_compra
        ]

    def baixar(self, url: str) -> tuple[bytes, str | None, str | None]:
        return self._http.bytes(url)


def _primeiro(dados: dict[str, Any], *chaves: str) -> Any:
    for chave in chaves:
        if chave in dados and dados[chave] is not None:
            return dados[chave]
    return None


class ComprasGov:
    """Endpoint público de dados abertos usado para descobrir compras."""

    def __init__(
        self,
        *,
        timeout: float = 45.0,
        tentativas: int = 5,
        intervalo: float = 0.75,
        reservar: Callable[[], int] | None = None,
        throttle: _IntervaloGlobal | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._http = ClientePublico(
            timeout=timeout,
            tentativas=tentativas,
            intervalo=intervalo,
            reservar=reservar,
            throttle=throttle,
            client=client,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ComprasGov":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def pagina_contratacoes(
        self,
        data_inicial: str,
        data_final: str,
        *,
        pagina: int,
        tamanho_pagina: int = 500,
        uf: str | None = None,
        cnpj: str | None = None,
        modalidade: int = 5,
        amparo_legal: int = 1,
    ) -> tuple[list[dict[str, Any]], int]:
        """Consulta PNCP 14.133 via Compras.gov.br.

        Neste endpoint o código interno ``5`` representa Pregão Eletrônico,
        cujo ``modalidadeIdPncp`` retornado é ``6``. A API rejeita páginas
        menores que 10 ou maiores que 500.
        """
        if not 10 <= tamanho_pagina <= 500:
            raise ValueError("Compras.gov.br aceita tamanho entre 10 e 500")
        params: dict[str, Any] = {
            "pagina": pagina,
            "tamanhoPagina": tamanho_pagina,
            "dataPublicacaoPncpInicial": data_inicial,
            "dataPublicacaoPncpFinal": data_final,
            "codigoModalidade": modalidade,
            "amparoLegalCodigoPncp": amparo_legal,
            "contratacaoExcluida": "false",
        }
        if uf:
            params["unidadeOrgaoUfSigla"] = uf
        if cnpj:
            params["orgaoEntidadeCnpj"] = cnpj
        payload = self._http.json(
            f"{COMPRAS_API}/modulo-contratacoes/1_consultarContratacoes_PNCP_14133",
            params,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("resultado"), list):
            raise PncpError("resposta do Compras.gov.br sem 'resultado' válido")
        total = payload.get("totalPaginas")
        if not isinstance(total, int) or total < 0:
            raise PncpError("resposta do Compras.gov.br sem 'totalPaginas' válido")
        dados = payload["resultado"]
        if pagina <= total and not dados:
            raise PncpError("paginação do Compras.gov.br terminou antes do total")
        return dados, total


# ------------------------------------------------------------ identificadores

_CONTROLE_PNCP = re.compile(r"^(\d{14})-\d+-(\d{1,10})/(\d{4})$")


def partes_controle(numero_controle_pncp: str) -> tuple[str, int, int]:
    """Valida e decompõe número de controle de uma contratação."""
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
