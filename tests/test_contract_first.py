"""Contrato é a única porta de entrada da descoberta R1."""

import pytest

from licita_corpus.harvest import (
    inspecionar_candidato,
    janelas_periodo,
    motivo_compra,
    motivo_contrato_base,
)
from licita_corpus.pncp import partes_controle


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
    def __init__(self, sem_etp=False, vinculo=NUMERO_COMPRA):
        self.sem_etp = sem_etp
        self.vinculo = vinculo

    def compra(self, cnpj, ano, sequencial):
        return compra()

    def arquivos_compra(self, cnpj, ano, sequencial):
        docs = [
            arquivo(1, "Edital", 2, "Edital"),
            arquivo(2, "Termo de Referência", 4, "Termo de Referência"),
            arquivo(3, "Estudo Técnico Preliminar", 7, "Estudo Técnico Preliminar"),
        ]
        return [d for d in docs if not (self.sem_etp and d["tipoDocumentoId"] == 7)]

    def contratos_da_compra(self, cnpj, ano, sequencial):
        item = contrato()
        item["numeroControlePncpCompra"] = self.vinculo
        return [item]

    def arquivos_contrato(self, cnpj, ano, sequencial):
        return [arquivo(1, "Contrato 7/2025", None, "Contrato")]


def test_numero_controle_e_validado_antes_de_virar_rota():
    assert partes_controle(NUMERO_COMPRA) == ("12345678000199", 2025, 42)
    with pytest.raises(ValueError, match="inválido"):
        partes_controle("123-1-42/2025-lixo")


def test_periodo_e_dividido_em_janelas_diarias_estaveis():
    assert janelas_periodo("20241231", "20250102") == [
        ("20250102", "20250102"),
        ("20250101", "20250101"),
        ("20241231", "20241231"),
    ]


def test_triagem_exige_contrato_federal_inicial_de_compras():
    assert motivo_contrato_base(contrato()) is None
    item = contrato()
    item["orgaoEntidade"]["esferaId"] = "M"
    assert motivo_contrato_base(item) == "órgão não federal"


def test_gate_da_compra_exige_pregao_edital_lei_e_bens():
    assert motivo_compra(compra()) is None
    item = compra()
    item["tipoInstrumentoConvocatorioNome"] = "Aviso de Contratação Direta"
    assert motivo_compra(item) == "instrumento convocatório não é Edital"


def test_inspecao_fecha_vinculo_e_quatro_documentos():
    candidato, motivo = inspecionar_candidato(PncpFalso(), contrato())
    assert motivo is None
    assert candidato["numero_controle_pncp"] == NUMERO_COMPRA
    assert [d["papel"] for d in candidato["documentos_compra"]] == ["ETP", "TR", "EDITAL"]
    assert candidato["documento_contrato"]["papel"] == "CONTRATO"
    assert candidato["contratos"][0]["numero_controle_pncp_compra"] == NUMERO_COMPRA


def test_etp_ausente_reprova_sem_substituir_documento():
    candidato, motivo = inspecionar_candidato(PncpFalso(sem_etp=True), contrato())
    assert candidato is None
    assert motivo == "documentos da contratação ausentes: ETP"


def test_vinculo_divergente_nao_e_aceito_por_semelhanca():
    candidato, motivo = inspecionar_candidato(PncpFalso(vinculo="outro"), contrato())
    assert candidato is None
    assert motivo == "nenhum contrato inicial confirmado pela contratação"
