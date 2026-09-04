"""Layout em disco, identificação de formato e montagem da cadeia documental."""

import json

import pytest

from licita_corpus.catalog import estatisticas, montar_processo, montar_relacoes
from licita_corpus.store import identificar_extensao, processo_id, slug


class TestIdentificacaoDeFormato:
    def test_pdf_pela_assinatura(self):
        assert identificar_extensao(b"%PDF-1.7\n...", "qualquer.txt") == "pdf"

    def test_docx_precisa_do_corpo_do_word(self, tmp_path):
        import zipfile

        caminho = tmp_path / "a.docx"
        with zipfile.ZipFile(caminho, "w") as arquivo:
            arquivo.writestr("word/document.xml", "<w:document/>")
        assert identificar_extensao(caminho.read_bytes(), "a.docx") == "docx"

    def test_zip_sem_corpo_do_word_nao_e_docx(self, tmp_path):
        import zipfile

        caminho = tmp_path / "a.zip"
        with zipfile.ZipFile(caminho, "w") as arquivo:
            arquivo.writestr("edital.pdf", "conteudo")
        assert identificar_extensao(caminho.read_bytes(), "a.docx") == "zip"

    def test_doc_legado_e_reconhecido(self):
        assert identificar_extensao(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1resto", None) == "doc"

    def test_sem_assinatura_usa_o_nome(self):
        assert identificar_extensao(b"conteudo qualquer", "arquivo.PDF") == "pdf"
        assert identificar_extensao(b"conteudo qualquer", None) == "bin"


class TestNomes:
    def test_slug_remove_acento_e_pontuacao(self):
        assert slug("ANEXO I - TERMO DE REFERÊNCIA nº 13/2025") == "anexo-i-termo-de-referencia-no-13-2025"

    def test_slug_de_titulo_vazio(self):
        assert slug("") == "sem-titulo"

    def test_processo_id_e_seguro_em_disco(self):
        assert "/" not in processo_id("10806496000149-1-000070/2025")


class TestRelacoes:
    def test_cadeia_completa_gera_tres_arestas(self):
        arestas = montar_relacoes("p", {"ETP": ["a"], "TR": ["b"], "EDITAL": ["c"], "CONTRATO": ["d"]})
        assert [(x["de_papel"], x["para_papel"]) for x in arestas] == [
            ("ETP", "TR"),
            ("TR", "EDITAL"),
            ("EDITAL", "CONTRATO"),
        ]

    def test_elo_ausente_e_atravessado(self):
        arestas = montar_relacoes("p", {"ETP": ["a"], "TR": ["b"], "EDITAL": [], "CONTRATO": ["d"]})
        assert [(x["de_papel"], x["para_papel"]) for x in arestas] == [("ETP", "TR"), ("TR", "CONTRATO")]

    def test_documento_unico_nao_gera_aresta(self):
        assert montar_relacoes("p", {"ETP": [], "TR": ["b"], "EDITAL": [], "CONTRATO": []}) == []

    def test_multiplos_documentos_do_mesmo_papel_geram_produto(self):
        arestas = montar_relacoes("p", {"ETP": ["a1", "a2"], "TR": ["b"], "EDITAL": [], "CONTRATO": []})
        assert len(arestas) == 2


class TestMontagemDeProcesso:
    @pytest.fixture
    def compra(self):
        return {
            "numero_controle_pncp": "10806496000149-1-000070/2025",
            "cnpj_orgao": "10806496000149",
            "ano_compra": 2025,
            "sequencial_compra": 70,
            "orgao": "MUNICIPIO DE EXEMPLO",
            "esfera": "M",
            "uf": "PI",
            "objeto": "Aquisição de material de limpeza",
            "categoria_objeto": "material_de_limpeza_e_higiene",
            "modalidade_id": 6,
            "instrumento_convocatorio_codigo": 1,
            "amparo_legal_codigo": 1,
            "amparo_legal_nome": "Lei 14.133/2021, Art. 28, I",
        }

    def test_funciona_sem_metadados_extras(self, compra):
        registro = montar_processo(compra, None, [], [])
        assert registro["processo_id"] == "10806496000149-1-000070-2025"
        assert registro["fontes"]["portal_pncp"].endswith("/editais/10806496000149/2025/70")
        assert registro["cadeia"] == {
            "DFD": [],
            "ETP": [],
            "TR": [],
            "EDITAL": [],
            "CONTRATO": [],
            "PESQUISA_PRECOS": [],
        }
        assert registro["perfil_id"] == "PUBLICO_14133_PREGAO_ELETRONICO_BENS"
        assert registro["perfil_status"] == registro["perfil_inicial"] == "SUPPORTED"
        assert registro["scope_status"] == "SUPPORTED"

    def test_estatisticas_separam_elegiveis_de_controle_negativo(self, compra):
        elegivel = montar_processo(compra, None, [], [])
        fora = montar_processo(
            {**compra, "numero_controle_pncp": "10806496000149-1-000071/2025", "objeto": "Aquisição de energia elétrica"},
            None,
            [],
            [],
        )

        assert fora["scope_status"] == "OUT_OF_SCOPE"
        # O estado de escopo explícito prevalece sobre aliases legados obsoletos.
        fora["perfil_status"] = fora["perfil_inicial"] = "SUPPORTED"
        resumo = estatisticas([elegivel, fora], [])
        assert resumo["processos"] == 2
        assert resumo["processos_elegiveis"] == 1
        assert resumo["processos_out_of_scope"] == 1
        assert resumo["categorias_distintas_elegiveis"] == 1

    def test_agrupa_documentos_por_papel(self, compra):
        documentos = [
            {"documento_id": "x#tr-01", "papel": "TR"},
            {"documento_id": "x#etp-02", "papel": "ETP"},
            {"documento_id": "x#outro", "papel": "OUTROS"},
        ]
        registro = montar_processo(compra, None, documentos, [])
        assert registro["cadeia"]["TR"] == ["x#tr-01"]
        assert registro["cadeia"]["ETP"] == ["x#etp-02"]
        assert "x#outro" not in json.dumps(registro["cadeia"])

    def test_extras_enriquecem_sem_sobrescrever_a_busca(self, compra):
        extras = {
            "processo_administrativo": "23000.000123/2025-11",
            "processo_administrativo_fonte": "contrato_pncp",
            "valor_total_estimado_itens": 1234.56,
            "quantidade_itens": 7,
        }
        registro = montar_processo(compra, extras, [], [])
        assert registro["processo_administrativo"] == "23000.000123/2025-11"
        assert registro["processo_administrativo_fonte"] == "contrato_pncp"
        assert registro["valores"]["total_estimado_itens"] == 1234.56
        assert registro["valores"]["quantidade_itens"] == 7
        assert registro["objeto"] == "Aquisição de material de limpeza"

    def test_sinaliza_duplicata_de_papel_em_vez_de_descartar(self, compra):
        documentos = [
            {"documento_id": "x#tr-01", "papel": "TR"},
            {"documento_id": "x#tr-02", "papel": "TR"},
            {"documento_id": "x#etp-03", "papel": "ETP"},
            {"documento_id": "x#edital-04", "papel": "EDITAL"},
            {"documento_id": "x#contrato-05", "papel": "CONTRATO"},
        ]
        registro = montar_processo(compra, None, documentos, [])
        escopo = registro["escopo_documental"]
        assert escopo["um_documento_por_papel"] is False
        assert escopo["contagem"] == {
            "DFD": 0,
            "ETP": 1,
            "TR": 2,
            "EDITAL": 1,
            "CONTRATO": 1,
            "PESQUISA_PRECOS": 0,
        }

    def test_cadeia_completa_com_um_documento_por_papel(self, compra):
        documentos = [
            {"documento_id": f"x#{papel.lower()}-0{i}", "papel": papel}
            for i, papel in enumerate(("ETP", "TR", "EDITAL", "CONTRATO"), start=1)
        ]
        registro = montar_processo(compra, None, documentos, [])
        assert registro["escopo_documental"]["um_documento_por_papel"] is True
        # Os quatro IDs não bastam para provar a cadeia: falta o contrato
        # explicitamente vinculado à mesma contratação.
        assert registro["escopo_documental"]["cadeia_completa"] is False
        assert estatisticas([registro], documentos)["processos_cadeia_completa"] == 0

    def test_manifesto_sem_documentos_nao_infla_cadeia_completa(self, compra):
        documentos = [
            {"documento_id": f"x#{papel.lower()}-01", "papel": papel}
            for papel in ("ETP", "TR", "EDITAL", "CONTRATO")
        ]
        contrato = {
            "numero_controle_pncp": "10806496000149-2-000070/2025",
            "numero_controle_pncp_compra": compra["numero_controle_pncp"],
            "criterio_vinculo": "numeroControlePncpCompra",
        }
        registro = montar_processo(compra, None, documentos, [contrato])

        assert registro["escopo_documental"]["cadeia_completa"] is True
        assert estatisticas([registro], [])["processos_cadeia_completa"] == 0

    def test_valor_contratado_soma_os_contratos(self, compra):
        contratos = [
            {"numero_controle_pncp": "10806496000149-2-000001/2026", "valor_global": 100.0},
            {"numero_controle_pncp": "10806496000149-2-000002/2026", "valor_global": 250.0},
        ]
        registro = montar_processo(compra, None, [], contratos)
        assert registro["valores"]["total_contratado"] == 350.0
        assert len(registro["contratos"]) == 2


class TestReaproveitamentoDeDownload:
    def test_arquivo_ja_em_disco_dispensa_nova_requisicao(self, tmp_path):
        from licita_corpus.store import baixar_documento

        class PncpQueFalhaSeChamado:
            def baixar(self, url):
                raise AssertionError("não deveria baixar de novo")

        caminho = tmp_path / "tr-03-termo-de-referencia.pdf"
        caminho.write_bytes(b"%PDF-1.4 conteudo")

        resultado = baixar_documento(
            PncpQueFalhaSeChamado(), "http://x", tmp_path, "TR", 3, "Termo de Referência"
        )
        assert resultado is not None
        assert resultado.ja_existia is True
        assert resultado.caminho == caminho
        assert resultado.extensao == "pdf"

    def test_nome_base_diferente_nao_reaproveita(self, tmp_path):
        from licita_corpus.store import baixar_documento

        class PncpFalso:
            def baixar(self, url):
                return b"%PDF-1.4 novo", "application/pdf", "novo.pdf"

        (tmp_path / "tr-03-outro-titulo.pdf").write_bytes(b"%PDF-1.4 antigo")
        resultado = baixar_documento(
            PncpFalso(), "http://x", tmp_path, "TR", 3, "Termo de Referência"
        )
        assert resultado.ja_existia is False
        assert resultado.caminho.name == "tr-03-termo-de-referencia.pdf"
