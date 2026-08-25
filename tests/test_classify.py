"""Classificação documental e de objeto — o filtro que define o que entra no corpus."""

from licita_corpus.classify import (
    AVISO_DIRETA,
    CONTRATO,
    EDITAL,
    ETP,
    MINUTA_CONTRATO,
    OUTRO,
    TR,
    categoria_objeto,
    papel_documento,
    papel_documento_contrato,
    parece_aquisicao_de_bens,
)


class TestPapelDocumento:
    def test_tipo_do_pncp_prevalece_sobre_o_titulo(self):
        assert papel_documento(2, "Termo de Referência anexo") == EDITAL

    def test_tipos_conhecidos(self):
        assert papel_documento(4, "qualquer") == TR
        assert papel_documento(7, "qualquer") == ETP
        assert papel_documento(1, "qualquer") == AVISO_DIRETA
        assert papel_documento(3, "qualquer") == MINUTA_CONTRATO

    def test_outros_documentos_cai_no_titulo(self):
        assert papel_documento(16, "ANEXO I - TERMO DE REFERENCIA") == TR
        assert papel_documento(16, "Estudo Técnico Preliminar 2025") == ETP
        assert papel_documento(16, "Edital de Pregão 13/2025") == EDITAL

    def test_tipo_desconhecido_nao_vira_documento_da_cadeia(self):
        assert papel_documento(9, "Termo de Referência") == OUTRO

    def test_documentos_acessorios_nao_sao_confundidos_com_o_principal(self):
        for titulo in (
            "Errata do Termo de Referência",
            "Retificação do Edital",
            "Ata de Sessão",
            "Resultado de julgamento",
            "Impugnação ao Termo de Referência",
        ):
            assert papel_documento(16, titulo) == OUTRO, titulo

    def test_titulo_sem_pista_vira_outro(self):
        assert papel_documento(16, "documento assinado") == OUTRO


class TestPapelAnexoDeContrato:
    def test_instrumento_contratual(self):
        assert papel_documento_contrato("Contrato", "Contrato 44/2025") == CONTRATO

    def test_acessorios_do_contrato_nao_sao_o_contrato(self):
        assert papel_documento_contrato("Nota de Empenho", "NE 2025NE000123") == OUTRO
        assert papel_documento_contrato("Termo Aditivo", "1º Termo Aditivo") == OUTRO


class TestCategoriaObjeto:
    def test_categorias_distintas(self):
        assert categoria_objeto("Aquisição de material de limpeza") == "material_de_limpeza_e_higiene"
        assert categoria_objeto("Aquisição de medicamentos") == "medicamentos_e_insumos_farmaceuticos"
        assert categoria_objeto("Aquisição de gêneros alimentícios") == "generos_alimenticios"

    def test_objeto_sem_categoria_conhecida(self):
        assert categoria_objeto("Aquisição de itens diversos") == "outros_bens"


class TestParaceAquisicaoDeBens:
    def test_aceita_aquisicao_de_bem(self):
        assert parece_aquisicao_de_bens("Aquisição de material de expediente")
        assert parece_aquisicao_de_bens("Registro de preços para aquisição de cadeiras")

    def test_rejeita_servicos_obras_e_locacao(self):
        for objeto in (
            "Contratação de empresa para prestação de serviços de limpeza",
            "Execução de obra de reforma do prédio",
            "Locação de veículos com motorista",
            "Aquisição de peças com manutenção preventiva de frota",
        ):
            assert not parece_aquisicao_de_bens(objeto), objeto

    def test_rejeita_objeto_que_nao_menciona_aquisicao(self):
        assert not parece_aquisicao_de_bens("Credenciamento de leiloeiros")
