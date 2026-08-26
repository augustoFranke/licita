"""Descoberta rarest-first: trio documental antes de consultar contratos."""

import copy
import sqlite3

import httpx
import pytest

from licita_corpus.harvest import (
    BancoHarvest,
    descobrir,
    inspecionar_compra,
    janelas_amplas,
    janelas_diarias,
    invalidar_download,
    motivo_compra,
)
from licita_corpus.pncp import Pncp, PncpError, partes_controle
from licita_corpus.select import Cotas


NUMERO_COMPRA = "12345678000199-1-000042/2025"
NUMERO_CONTRATO = "12345678000199-2-000007/2025"


def contrato():
    return {
        "numeroControlePNCP": NUMERO_CONTRATO,
        "numeroControlePncpCompra": NUMERO_COMPRA,
        "anoContrato": 2025,
        "sequencialContrato": 7,
        "numeroContratoEmpenho": "7/2025",
        "tipoContrato": {"id": 1, "nome": "Contrato (termo inicial)"},
        "categoriaProcesso": {"id": 2, "nome": "Compras"},
        "orgaoEntidade": {
            "cnpj": "12345678000199",
            "razaoSocial": "Órgão Federal",
            "esferaId": "F",
            "poderId": "E",
        },
        "unidadeOrgao": {"ufSigla": "DF", "municipioNome": "Brasília"},
        "objetoContrato": "Aquisição de material de expediente",
        "dataPublicacaoPncp": "2025-06-01T00:00:00",
        "valorGlobal": 1000,
    }


def compra():
    return {
        "numeroControlePNCP": NUMERO_COMPRA,
        "anoCompra": 2025,
        "sequencialCompra": 42,
        "numeroCompra": "90042/2025",
        "processo": "00001.000042/2025-00",
        "modalidadeId": 6,
        "modalidadeNome": "Pregão - Eletrônico",
        "tipoInstrumentoConvocatorioCodigo": 1,
        "tipoInstrumentoConvocatorioNome": "Edital",
        "amparoLegal": {"codigo": 1, "nome": "Lei 14.133/2021, Art. 28, I"},
        "objetoCompra": "Aquisição de material de expediente",
        "orgaoEntidade": {
            "cnpj": "12345678000199",
            "razaoSocial": "Órgão Federal",
            "esferaId": "F",
            "poderId": "E",
        },
        "unidadeOrgao": {
            "nomeUnidade": "Unidade 1",
            "ufSigla": "DF",
            "municipioNome": "Brasília",
        },
        "valorTotalEstimado": 1100,
    }


def arquivo(seq, titulo, tipo, nome):
    return {
        "sequencialDocumento": seq,
        "titulo": titulo,
        "tipoDocumentoId": tipo,
        "tipoDocumentoNome": nome,
        "url": f"https://arquivos/{seq}",
        "statusAtivo": True,
    }


class PncpFalso:
    def __init__(self, sem_etp=False, vinculo=NUMERO_COMPRA, etp_duplicado=False, dois_contratos=False):
        self.sem_etp = sem_etp
        self.vinculo = vinculo
        self.etp_duplicado = etp_duplicado
        self.dois_contratos = dois_contratos
        self.contratos_chamados = 0

    def arquivos_compra(self, cnpj, ano, sequencial):
        docs = [
            arquivo(1, "Edital", 2, "Edital"),
            arquivo(2, "Termo de Referência", 4, "Termo de Referência"),
            arquivo(3, "Estudo Técnico Preliminar", 7, "Estudo Técnico Preliminar"),
        ]
        saida = [d for d in docs if not (self.sem_etp and d["tipoDocumentoId"] == 7)]
        if self.etp_duplicado:
            saida.append(arquivo(4, "Outro ETP", 7, "Estudo Técnico Preliminar"))
        return saida

    def contratos_da_compra(self, cnpj, ano, sequencial):
        self.contratos_chamados += 1
        item = contrato()
        item["numeroControlePncpCompra"] = self.vinculo
        if not self.dois_contratos:
            return [item]
        outro = copy.deepcopy(item)
        outro["numeroControlePNCP"] = "12345678000199-2-000008/2025"
        outro["sequencialContrato"] = 8
        return [item, outro]

    def arquivos_contrato(self, cnpj, ano, sequencial):
        return [arquivo(1, "Contrato 7/2025", None, "Contrato")]


def _pncp_com_status(status: int) -> Pncp:
    pncp = Pncp(tentativas=1, intervalo=0)
    pncp._client.close()
    pncp._client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status))
    )
    return pncp


def test_404_no_feed_nao_vira_janela_vazia():
    with _pncp_com_status(404) as pncp:
        with pytest.raises(PncpError, match="HTTP 404"):
            pncp.pagina_contratacoes_publicadas("20250101", "20250101", pagina=1)


def test_204_no_feed_e_resultado_vazio_documentado():
    with _pncp_com_status(204) as pncp:
        assert pncp.pagina_contratacoes_publicadas("20250101", "20250101", pagina=1) == ([], 0)


def test_numero_controle_e_validado_antes_de_virar_rota():
    assert partes_controle(NUMERO_COMPRA) == ("12345678000199", 2025, 42)
    with pytest.raises(ValueError, match="inválido"):
        partes_controle("123-1-42/2025-lixo")


def test_janelas_globais_sao_diarias_e_reversas():
    assert janelas_diarias("20241231", "20250102") == [
        ("20250102", "20250102"),
        ("20250101", "20250101"),
        ("20241231", "20241231"),
    ]


def test_janelas_de_orgao_respeitam_limite_de_365_dias():
    janelas = janelas_amplas("20240101", "20251231")
    assert janelas[0] == ("20250101", "20251231")
    assert janelas[1] == ("20240102", "20241231")
    assert janelas[2] == ("20240101", "20240101")


def test_gate_da_compra_exige_executivo_federal_edital_lei_e_bens():
    assert motivo_compra(compra()) is None
    item = compra()
    item["orgaoEntidade"]["esferaId"] = "M"
    assert motivo_compra(item) == "contratação não federal"


def test_trio_com_contrato_fecha_cadeia():
    candidato = inspecionar_compra(PncpFalso(), compra())
    assert candidato["status"] == "COMPLETO"
    assert candidato["tem_trio"] is True
    assert [d["papel"] for d in candidato["candidato"]["documentos_compra"]] == [
        "ETP",
        "TR",
        "EDITAL",
    ]
    assert candidato["candidato"]["documento_contrato"]["papel"] == "CONTRATO"


def test_sem_etp_reprova_antes_de_consultar_contratos():
    pncp = PncpFalso(sem_etp=True)
    resultado = inspecionar_compra(pncp, compra())
    assert resultado["status"] == "SEM_TRIO"
    assert resultado["motivo"] == "documentos da contratação ausentes: ETP"
    assert pncp.contratos_chamados == 0


def test_vinculo_divergente_nao_e_aceito():
    resultado = inspecionar_compra(PncpFalso(vinculo="outro"), compra())
    assert resultado["status"] == "SEM_CONTRATO"


def test_duplicidade_de_papel_e_fora_do_escopo():
    resultado = inspecionar_compra(PncpFalso(etp_duplicado=True), compra())
    assert resultado["status"] == "DUPLICIDADE_DOCUMENTAL"
    assert resultado["motivo"] == "mais de um documento ativo: ETP"


def test_multiplos_contratos_iniciais_nao_sao_colapsados():
    resultado = inspecionar_compra(PncpFalso(dois_contratos=True), compra())
    assert resultado["status"] == "DUPLICIDADE_CONTRATO"


def test_cache_negativo_expira_e_pode_ser_reinspecionado(tmp_path):
    banco = BancoHarvest(tmp_path / "rarest_first.sqlite3", validade_dias=7)
    try:
        registro = inspecionar_compra(PncpFalso(sem_etp=True), compra())
        banco.salvar_inspecao(registro)
        assert banco.ja_inspecionados([NUMERO_COMPRA]) == {NUMERO_COMPRA}
        banco.conexao.execute(
            "UPDATE inspecoes SET atualizada_em = '2000-01-01T00:00:00+00:00'"
        )
        banco.conexao.commit()
        assert banco.ja_inspecionados([NUMERO_COMPRA]) == set()
    finally:
        banco.close()


def test_candidato_reprovado_no_download_sai_do_pool(tmp_path):
    banco_path = tmp_path / "rarest_first.sqlite3"
    banco = BancoHarvest(banco_path)
    try:
        registro = inspecionar_compra(PncpFalso(), compra())
        banco.salvar_inspecao(registro)
        assert len(banco.candidatos_completos()) == 1
    finally:
        banco.close()
    invalidar_download(banco_path, NUMERO_COMPRA, "DOCX vazio")
    banco = BancoHarvest(banco_path)
    try:
        assert banco.candidatos_completos() == []
    finally:
        banco.close()


def test_falha_de_janela_e_retentada_na_invocacao_seguinte(tmp_path):
    class PncpComJanelaIndisponivel(PncpFalso):
        def __init__(self):
            super().__init__()
            self.falhou = False

        def pagina_contratacoes_publicadas(
            self, inicio, fim, *, pagina, modalidade=6, cnpj=None, tamanho_pagina=50
        ):
            if inicio == "20250102" and not self.falhou:
                self.falhou = True
                raise PncpError("HTTP 504")
            if inicio == "20250101":
                return [], 0
            return [copy.deepcopy(compra())], 1

    banco = tmp_path / "rarest_first.sqlite3"
    pncp = PncpComJanelaIndisponivel()
    argumentos = dict(
        data_inicial="20250101",
        data_final="20250102",
        cotas=Cotas(processos=1, orgaos_distintos=1, categorias_distintas=1),
        reserva=0,
        workers=1,
        log=lambda _mensagem: None,
    )
    primeira = descobrir(pncp, banco, **argumentos)
    assert primeira.falhas_api == 1
    assert primeira.candidatos == []

    segunda = descobrir(pncp, banco, **argumentos)
    assert segunda.falhas_api == 0
    assert len(segunda.candidatos) == 1
    with sqlite3.connect(banco) as conexao:
        estado = conexao.execute(
            "SELECT status, erro FROM consultas WHERE chave = 'global:20250102'"
        ).fetchone()
    assert estado == ("CONCLUIDA", None)
