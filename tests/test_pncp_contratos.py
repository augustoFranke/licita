from __future__ import annotations

import httpx
import pytest

from licita_corpus.pncp import Pncp, PncpError


def test_consulta_contratos_diretamente_pela_contratacao() -> None:
    requisicoes: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(
            200,
            json=[{"numeroControlePNCP": "12345678000199-2-000007/2025"}],
        )

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    with Pncp(client=cliente, intervalo=0) as pncp:
        contratos, total = pncp.pagina_contratos_da_compra(
            "12345678000199-1-000042/2024", pagina=1
        )

    assert contratos == [{"numeroControlePNCP": "12345678000199-2-000007/2025"}]
    assert total == 1
    assert requisicoes[0].url.path == (
        "/api/pncp/v1/orgaos/12345678000199/contratos/contratacao/2024/42"
    )
    assert dict(requisicoes[0].url.params) == {"pagina": "1"}


def test_consulta_contratos_aceita_envelope_legado_sem_reexigir_parametro() -> None:
    requisicoes: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"numeroControlePNCP": "12345678000199-2-000007/2025"}],
                "totalPaginas": 2,
            },
        )

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    with Pncp(client=cliente, intervalo=0) as pncp:
        contratos, total = pncp.pagina_contratos_da_compra(
            "12345678000199-1-000042/2024", pagina=1
        )
        segunda, total_segunda = pncp.pagina_contratos_da_compra(
            "12345678000199-1-000042/2024", pagina=2
        )

    assert contratos
    assert total == 2
    assert segunda == []
    assert total_segunda == 2
    assert [dict(requisicao.url.params) for requisicao in requisicoes] == [
        {"pagina": "1"},
        {"pagina": "2"},
    ]


def test_feed_de_contratos_e_a_raiz_da_descoberta() -> None:
    requisicoes: list[httpx.Request] = []
    registro = {
        "numeroControlePNCP": "12345678000199-2-000007/2025",
        "numeroControlePNCPCompra": "12345678000199-1-000042/2024",
    }

    def responder(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(
            200,
            json={"data": [registro], "totalPaginas": 3},
        )

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    with Pncp(client=cliente, intervalo=0) as pncp:
        contratos, total = pncp.pagina_contratos_publicados(
            "20250101",
            "20250131",
            pagina=2,
            tamanho_pagina=500,
            uf="DF",
            cnpj="12345678000199",
        )

    assert contratos == [registro]
    assert total == 3
    assert requisicoes[0].url.path == "/api/consulta/v1/contratos"
    assert dict(requisicoes[0].url.params) == {
        "dataInicial": "20250101",
        "dataFinal": "20250131",
        "pagina": "2",
        "tamanhoPagina": "500",
        "uf": "DF",
        "cnpjOrgao": "12345678000199",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}, "totalPaginas": 1},
        {"data": [{}], "totalPaginas": None},
        {"data": [], "totalPaginas": 1},
    ],
)
def test_feed_de_contratos_rejeita_respostas_invalidas(payload: object) -> None:
    cliente = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    )
    with Pncp(client=cliente, intervalo=0) as pncp:
        with pytest.raises(PncpError):
            pncp.pagina_contratos_publicados(
                "20250101", "20250131", pagina=1, tamanho_pagina=500
            )


def test_listas_de_arquivos_aceitam_payload_documentos_do_manual() -> None:
    arquivo = {
        "sequencialDocumento": 1,
        "tipoDocumentoNome": "Contrato",
        "titulo": "Contrato 1",
        "url": "https://arquivos.test/contrato.pdf",
    }

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/compras/2024/42/arquivos"):
            return httpx.Response(200, json={"documentos": [arquivo]})
        return httpx.Response(200, json={"Documentos": [arquivo]})

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    with Pncp(client=cliente, intervalo=0) as pncp:
        assert pncp.arquivos_compra("12345678000199", 2024, 42) == [arquivo]
        assert pncp.arquivos_contrato("12345678000199", 2025, 7) == [arquivo]


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": {}, "totalPaginas": 1}, {"data": [], "totalPaginas": None}],
)
def test_rejeita_resposta_invalida_de_contratos(payload: object) -> None:
    cliente = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    )
    with Pncp(client=cliente, intervalo=0) as pncp:
        with pytest.raises(PncpError):
            pncp.pagina_contratos_da_compra("12345678000199-1-000042/2024")
