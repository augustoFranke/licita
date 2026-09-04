"""Classificação documental e de objeto — o filtro que define o que entra no corpus."""

from licita_corpus.classify import (
    CONTRATO,
    DFD,
    EDITAL,
    ETP,
    OUTROS,
    PERFIL_FORA,
    PERFIL_SUPPORTED,
    PESQUISA_PRECOS,
    TR,
    categoria_objeto,
    classificar_perfil_inicial,
    papel_documento,
    papel_documento_contrato,
    parece_aquisicao_de_bens,
)


class TestPapelDocumento:
    def test_tipo_do_pncp_prevalece_sobre_o_titulo(self):
        assert papel_documento(2, "Termo de Referência anexo") == EDITAL

    def test_tipo_oficial_nao_transforma_publicacao_em_documento_principal(self):
        for titulo in (
            "Publicação PNCP",
            "Extrato do Edital",
            "Comprovante de publicação",
        ):
            assert papel_documento(2, titulo) == OUTROS

    def test_tipos_conhecidos(self):
        assert papel_documento(4, "qualquer") == TR
        assert papel_documento(7, "qualquer") == ETP
        assert papel_documento(1, "qualquer") == OUTROS
        assert papel_documento(3, "qualquer") == OUTROS

    def test_outros_documentos_cai_no_titulo(self):
        assert papel_documento(16, "ANEXO I - TERMO DE REFERENCIA") == TR
        assert papel_documento(16, "Estudo Técnico Preliminar 2025") == ETP
        assert papel_documento(16, "Edital de Pregão 13/2025") == EDITAL

    def test_tipo_desconhecido_nao_vira_documento_da_cadeia(self):
        assert papel_documento(9, "Termo de Referência") == OUTROS

    def test_referencial_nao_e_referencia(self):
        assert papel_documento(16, "Termo de Referencial") == OUTROS
        assert papel_documento(16, "Termo de Referência") == TR
        assert papel_documento(16, "Estudo Técnico Preliminar") == ETP

    def test_documentos_acessorios_nao_sao_confundidos_com_o_principal(self):
        for titulo in (
            "Errata do Termo de Referência",
            "Retificação do Edital",
            "Ata de Sessão",
            "Resultado de julgamento",
            "Impugnação ao Termo de Referência",
        ):
            assert papel_documento(16, titulo) == OUTROS, titulo

    def test_titulo_sem_pista_vira_outro(self):
        assert papel_documento(16, "documento assinado") == OUTROS
        assert papel_documento(16, "Documento de Formalização da Demanda") == DFD
        assert papel_documento(16, "Pesquisa de Preços") == PESQUISA_PRECOS


class TestPapelAnexoDeContrato:
    def test_instrumento_contratual(self):
        assert papel_documento_contrato("Contrato", "Contrato 44/2025") == CONTRATO

    def test_acessorios_do_contrato_nao_sao_o_contrato(self):
        assert papel_documento_contrato("Nota de Empenho", "NE 2025NE000123") == OUTROS
        assert papel_documento_contrato("Termo Aditivo", "1º Termo Aditivo") == OUTROS

    def test_instrumento_e_reconhecido_por_codigo_ou_titulo(self):
        assert papel_documento_contrato(None, "Instrumento contratual") == CONTRATO
        assert papel_documento_contrato(None, "arquivo assinado", 12) == CONTRATO
        assert papel_documento_contrato(None, "Contrato aditivo") == OUTROS

    def test_minuta_ou_rascunho_nao_e_instrumento_assinado(self):
        assert papel_documento_contrato("Minuta de contrato", "Minuta de contrato", 3) == OUTROS
        assert papel_documento_contrato("Outros documentos", "Contrato", 3) == OUTROS
        assert papel_documento_contrato(None, "Rascunho do contrato") == OUTROS

    def test_extrato_publicacao_ou_comprovante_nao_e_instrumento(self):
        for tipo, titulo in (
            (None, "Extrato de contrato"),
            ("Extrato de contrato", "Contrato"),
            ("Contrato", "Publicação do contrato"),
            (None, "Comprovante de publicação do contrato"),
        ):
            assert papel_documento_contrato(tipo, titulo) == OUTROS


class TestCategoriaObjeto:
    def test_categorias_distintas(self):
        assert categoria_objeto("Aquisição de material de limpeza") == "material_de_limpeza_e_higiene"
        assert categoria_objeto("Aquisição de medicamentos") == "medicamentos_e_insumos_farmaceuticos"
        assert categoria_objeto("Aquisição de gêneros alimentícios") == "generos_alimenticios"

    def test_objeto_sem_categoria_conhecida(self):
        assert categoria_objeto("Aquisição de itens diversos") == "outros_bens"

    def test_casos_de_regressao(self):
        casos = {
            "Kits de higiene bucal": "material_de_limpeza_e_higiene",
            "Cateteres periféricos": "material_medico_hospitalar",
            "SRP informática": "equipamentos_de_informatica",
            "Asfalto frio": "material_de_construcao_e_ferramentas",
            "Peças automotivas": "veiculos_pecas_e_combustiveis",
            "Implementos agrícolas": "material_agropecuario_e_jardinagem",
        }
        for objeto, categoria in casos.items():
            assert categoria_objeto(objeto) == categoria, objeto

    def test_cimento_nao_casa_dentro_de_fornecimento(self):
        assert categoria_objeto("Fornecimento de energia elétrica") == "outros_bens"
        assert categoria_objeto("Fornecimento de cimento") == "material_de_construcao_e_ferramentas"

    def test_equipamento_hospitalar_vem_antes_de_material(self):
        assert categoria_objeto("Equipamento médico-hospitalar") == "equipamentos_medico_hospitalares"

    def test_plural_de_material_de_expediente(self):
        assert categoria_objeto("Materiais de expediente") == "material_de_expediente_e_escritorio"

    def test_termos_exigem_limites_dos_dois_lados(self):
        assert categoria_objeto("Mudas de plantas") == "material_agropecuario_e_jardinagem"
        assert categoria_objeto("Mudança de sistema") == "outros_bens"
        assert categoria_objeto("EPI") == "epi_uniformes_e_textil"
        assert categoria_objeto("Epígrafe do documento") == "outros_bens"
        assert categoria_objeto("Asfaltamento de estrada") == "outros_bens"


class TestParaceAquisicaoDeBens:
    def test_aceita_aquisicao_de_bem(self):
        assert parece_aquisicao_de_bens("Aquisição de material de expediente")
        assert parece_aquisicao_de_bens("Registro de preços para aquisição de cadeiras")

    def test_aceita_lista_inequivoca_de_bens_sem_verbo_de_aquisicao(self):
        for objeto in (
            "Kits de higiene bucal",
            "Cateteres periféricos",
            "SRP informática",
            "Asfalto frio",
            "Peças automotivas",
        ):
            assert parece_aquisicao_de_bens(objeto), objeto

    def test_rejeita_servicos_obras_e_locacao(self):
        for objeto in (
            "Contratação de empresa para prestação de serviços de limpeza",
            "Execução de obra de reforma do prédio",
            "Locação de veículos com motorista",
            "Aquisição de peças com manutenção preventiva de frota",
        ):
            assert not parece_aquisicao_de_bens(objeto), objeto

    def test_rejeita_servicos_atendimentos_e_plurais_normalizados(self):
        for objeto in (
            "Aquisição de serviços",
            "Fornecimento de serviços",
            "Serviço hospitalar",
            "Atendimento hospitalar",
            "Manutenções de equipamentos médico-hospitalares",
            "manutencoes de equipamentos",
            "Locações de veículos",
            "locacoes de veiculos",
            "Serviços de limpeza",
            "servicos de limpeza",
            "Atendimentos hospitalares",
        ):
            assert not parece_aquisicao_de_bens(objeto), objeto

    def test_rejeita_servicos_de_saude_com_prefixos_e_flexoes(self):
        for prefixo in ("Aquisição de", "Fornecimento de", "Contratação de"):
            for servico in (
                "internação hospitalar",
                "internações hospitalares",
                "exame laboratorial",
                "exames laboratoriais",
                "consulta médica",
                "consultas médicas",
                "procedimento hospitalar",
                "procedimentos hospitalares",
                "atendimento hospitalar",
                "atendimentos hospitalares",
            ):
                objeto = f"{prefixo} {servico}"
                assert not parece_aquisicao_de_bens(objeto), objeto

    def test_aceita_materiais_e_equipamentos_hospitalares_e_laboratoriais(self):
        for objeto in (
            "Aquisição de materiais hospitalares",
            "Fornecimento de materiais laboratoriais",
            "Contratação de equipamentos hospitalares",
            "Aquisição de equipamentos laboratoriais",
        ):
            assert parece_aquisicao_de_bens(objeto), objeto

    def test_energia_nao_e_aquisicao_de_bens(self):
        for objeto in ("Fornecimento de energia elétrica", "Aquisição de energia elétrica"):
            assert not parece_aquisicao_de_bens(objeto), objeto

    def test_rejeita_objeto_que_nao_menciona_aquisicao(self):
        assert not parece_aquisicao_de_bens("Credenciamento de leiloeiros")


class TestPerfilInicial:
    def test_municipal_14133_pregao_eletronico_bens_e_supported(self):
        assert (
            classificar_perfil_inicial(
                esfera="M",
                amparo_legal_nome="Lei 14.133/2021, Art. 28, I",
                modalidade_id=6,
                objeto="Aquisição de material de limpeza",
            )
            == PERFIL_SUPPORTED
        )

    def test_todas_as_esferas_da_uniao_aos_municipios_sao_suportadas(self):
        """A esfera deixou de restringir o perfil (F/E/D/M valem)."""
        for esfera in ("F", "E", "D", "M", "m"):
            assert (
                classificar_perfil_inicial(
                    esfera=esfera,
                    amparo_legal_nome="Lei 14.133/2021, Art. 28, I",
                    modalidade_id=6,
                    objeto="Aquisição de material de limpeza",
                )
                == PERFIL_SUPPORTED
            )

    def test_esfera_ausente_ou_desconhecida_fica_fora(self):
        """Sem esfera conhecida não há prova de ente público sob o regime."""
        for esfera in (None, "", "X", "  "):
            assert (
                classificar_perfil_inicial(
                    esfera=esfera,
                    amparo_legal_nome="Lei 14.133/2021, Art. 28, I",
                    modalidade_id=6,
                    objeto="Aquisição de material de limpeza",
                )
                == PERFIL_FORA
            )

    def test_pregao_eletronico_ausente_ou_incorreto_fica_fora(self):
        for modalidade in (None, "", 5, 7):
            assert (
                classificar_perfil_inicial(
                    esfera="M",
                    amparo_legal_nome="Lei 14.133/2021, Art. 28, I",
                    modalidade_id=modalidade,
                    objeto="Aquisição de material de limpeza",
                )
                == PERFIL_FORA
            )
