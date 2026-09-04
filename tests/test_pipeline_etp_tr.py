"""Testes dos componentes compartilhados da coleta documental."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pymupdf
import pytest

import licita_corpus.collect as collect_module
from licita_corpus.collect import (
    Caminhos,
    formar_candidato,
    janelas_calendario,
    normalizar_compra,
    round_robin_por_cnpj,
    termos_historicos,
)
from licita_corpus.pncp import ComprasGov, Pncp, PncpError
from licita_corpus.state import EstadoColeta, LimiteRequisicoes


NUMERO = "18025940000109-1-000260/2025"


def arquivo(seq, titulo, tipo, url=f"https://arquivos/{1}"):
    return {
        "sequencialDocumento": seq,
        "titulo": titulo,
        "tipoDocumentoId": tipo,
        "tipoDocumentoNome": "Outros Documentos" if tipo == 16 else titulo,
        "url": url,
        "statusAtivo": True,
    }


def compra_flat():
    return {
        "numeroControlePNCP": NUMERO,
        "anoCompraPncp": 2025,
        "sequencialCompraPncp": 260,
        "orgaoEntidadeCnpj": "18025940000109",
        "orgaoEntidadeRazaoSocial": "MUNICIPIO DE ITAJUBA",
        "orgaoEntidadeEsferaId": "M",
        "orgaoEntidadePoderId": "N",
        "unidadeOrgaoNomeUnidade": "PREFEITURA",
        "unidadeOrgaoUfSigla": "MG",
        "unidadeOrgaoMunicipioNome": "Itajubá",
        "numeroCompra": "46/2025",
        "modalidadeIdPncp": 6,
        "modalidadeNome": "Pregão - Eletrônico",
        "tipoInstrumentoConvocatorioCodigoPncp": 1,
        "tipoInstrumentoConvocatorioNome": "Edital",
        "amparoLegalCodigoPncp": 1,
        "amparoLegalNome": "Lei 14.133/2021, Art. 28, I",
        "objetoCompra": "Registro de preços para aquisição de equipamentos odontológicos",
        "dataPublicacaoPncp": "2025-11-13T22:32:58",
    }


def test_janelas_sao_reversas_e_limitam_periodo():
    assert janelas_calendario("20250101", "20250215", dias=31) == [
        ("2025-01-16", "2025-02-15"),
        ("2025-01-01", "2025-01-15"),
    ]


def test_normaliza_formato_flat_do_compras_gov():
    compra = normalizar_compra(compra_flat(), "compras_gov")
    assert compra["numero_controle_pncp"] == NUMERO
    assert compra["modalidade_id"] == 6
    assert compra["instrumento_convocatorio_codigo"] == 1
    assert compra["amparo_legal_codigo"] == 1
    assert compra["categoria_objeto"] == "material_medico_hospitalar"


def test_tipo_documento_string_e_outros_documentos_formam_par():
    candidato, motivo, todos = formar_candidato(
        normalizar_compra(compra_flat(), "compras_gov"),
        [
            arquivo(1, "edital", "2"),
            arquivo(2, "4._TR__Equipamentos_Odontologicos", 16),
            arquivo(3, "3._ETP__Equipamentos_Odontologicos", 16),
        ],
    )
    assert motivo is None
    assert candidato is not None
    assert [x["papel"] for x in candidato["documentos_compra"]] == ["ETP", "TR"]
    assert len(todos) == 3


def test_busca_pncp_e_compras_usam_respostas_publicas():
    chamadas = []

    def responder(request: httpx.Request) -> httpx.Response:
        chamadas.append(request)
        if request.url.host == "pncp.gov.br":
            return httpx.Response(
                200,
                json={"items": [{"numero_controle_pncp": NUMERO}], "total": 1},
            )
        return httpx.Response(
            200,
            json={"resultado": [compra_flat()], "totalPaginas": 1},
        )

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    pncp = Pncp(client=cliente, intervalo=0)
    compras = ComprasGov(client=cliente, intervalo=0)
    itens, total = pncp.busca_portal("ETP", pagina=1)
    registros, paginas = compras.pagina_contratacoes(
        "2025-01-01", "2025-01-31", pagina=1
    )
    assert itens[0]["numero_controle_pncp"] == NUMERO
    assert total == 1
    assert registros[0]["modalidadeIdPncp"] == 6
    assert paginas == 1
    assert chamadas[0].url.params["tam_pagina"] == "50"
    assert chamadas[1].url.params["tamanhoPagina"] == "500"
    pncp.close()
    compras.close()
    cliente.close()


def test_estado_persiste_cache_e_nao_deixa_estourar_orcamento(tmp_path):
    estado = EstadoColeta(tmp_path / "estado.sqlite3", max_requisicoes_dia=1)
    try:
        assert estado.reservar_requisicao() == 1
        try:
            estado.reservar_requisicao()
        except LimiteRequisicoes:
            pass
        else:  # pragma: no cover
            raise AssertionError("o orçamento deveria bloquear a segunda chamada")
        estado.salvar_resposta("x", {"resultado": []})
        assert estado.resposta("x") == {"resultado": []}
    finally:
        estado.close()


def test_download_compartilhado_etp_tr_preserva_escopo_historico(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import licita_corpus.collect as modulo
    from licita_corpus.collect import baixar_par

    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), "texto documental suficiente para validação local")
    saida = tmp_path / "arquivo.pdf"
    documento.save(saida)
    documento.close()
    conteudo = saida.read_bytes()

    def baixar(_pncp, url, destino, papel, seq, titulo):
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{papel.lower()}-{seq:02d}.pdf"
        caminho.write_bytes(conteudo)
        return SimpleNamespace(
            caminho=caminho,
            nome_original=None,
            sha256=hashlib.sha256(conteudo).hexdigest(),
            bytes=len(conteudo),
            extensao="pdf",
            content_type="application/pdf",
        )

    monkeypatch.setattr(modulo, "baixar_documento", baixar)
    compra = normalizar_compra(compra_flat(), "compras_gov")
    candidato, _, _ = formar_candidato(
        compra,
        [arquivo(2, "TR", 4), arquivo(3, "ETP", 7)],
    )
    resultado = baixar_par(object(), candidato, Caminhos(tmp_path))
    assert resultado.aprovado is True
    assert [d["papel"] for d in resultado.documentos] == ["ETP", "TR"]
    assert all("edital" not in d["arquivo"] for d in resultado.documentos)


def _verificacao_mock(path: Path, *, ocr: bool = False, idioma: str = "por"):
    return SimpleNamespace(
        abriu=True,
        paginas=1,
        caracteres=80,
        precisa_ocr=False,
        erro=None,
        texto="texto documental suficiente para o teste",
        texto_original="texto original",
        ocr_solicitado=ocr,
        ocr_usado=ocr,
        ocr_motor="tesseract" if ocr else None,
        ocr_idioma=idioma if ocr else None,
        paginas_ocr=(1,) if ocr else (),
        paginas_ocr_tentadas=(1,) if ocr else (),
        ocr_confianca_media=91.0 if ocr else None,
        ocr_erros=(),
        ocr={
            "solicitado": ocr,
            "usado": ocr,
            "motor": "tesseract" if ocr else None,
            "idioma": idioma if ocr else None,
            "paginas": [1] if ocr else [],
            "paginas_tentadas": [1] if ocr else [],
            "confianca_media": 91.0 if ocr else None,
            "erros": [],
        },
    )


def _instalar_download_mock(monkeypatch, *, ruim: set[str] | None = None):
    chamadas: list[str] = []
    ruins = ruim or set()

    def baixar(_pncp, url, destino, papel, seq, titulo):
        chamadas.append(url)
        destino.mkdir(parents=True, exist_ok=True)
        conteudo = b"%PDF-1.4 " + (b"ruim" if url in ruins else b"bom")
        caminho = destino / f"{papel.lower()}-{seq or 0}-{len(chamadas)}.pdf"
        caminho.write_bytes(conteudo)
        return SimpleNamespace(
            caminho=caminho,
            nome_original="origem.pdf",
            sha256=hashlib.sha256(conteudo).hexdigest(),
            bytes=len(conteudo),
            extensao="pdf",
            content_type="application/pdf",
        )

    def verificar_mock(path, **kwargs):
        if path.read_bytes().endswith(b"ruim"):
            resultado = _verificacao_mock(path, ocr=bool(kwargs.get("ocr")))
            resultado.caracteres = 0
            resultado.precisa_ocr = True
            resultado.texto = ""
            return resultado
        return _verificacao_mock(path, **kwargs)

    monkeypatch.setattr(collect_module, "baixar_documento", baixar)
    monkeypatch.setattr(collect_module, "verificar", verificar_mock)
    return chamadas


def test_query_historica_coloca_ano_no_q_e_prioriza_anos():
    assert termos_historicos(("ETP",), "20220101", "20251231") == (
        "ETP 2024",
        "ETP 2023",
        "ETP 2022",
        "ETP 2025",
    )


def test_normalizacao_valida_ano_da_compra_e_aceita_publicacao_posterior():
    compra = compra_flat()
    compra["anoCompraPncp"] = 2024
    with pytest.raises(ValueError, match="ano"):
        normalizar_compra(compra, "feed")

    compra = compra_flat()
    compra["dataPublicacaoPncp"] = "2026-03-17T16:01:52"
    normalizada = normalizar_compra(compra, "feed")
    assert normalizada["ano_compra"] == 2025
    assert normalizada["data_publicacao_pncp"] == "2026-03-17T16:01:52"

    compra["dataPublicacaoPncp"] = "data-inválida"
    with pytest.raises(ValueError, match="data de publicação inválida"):
        normalizar_compra(compra, "feed")


def test_round_robin_por_cnpj_intercala_a_a_b():
    compras = [
        {"numero_controle_pncp": "a1", "cnpj_orgao": "A"},
        {"numero_controle_pncp": "a2", "cnpj_orgao": "A"},
        {"numero_controle_pncp": "b1", "cnpj_orgao": "B"},
    ]
    assert [x["numero_controle_pncp"] for x in round_robin_por_cnpj(compras)] == [
        "a1",
        "b1",
        "a2",
    ]


def test_prioridade_coloca_detalhe_e_modalidade_conhecida_primeiro():
    desconhecido = ({"modalidade_id": None}, "busca", False)
    modalidade = ({"modalidade_id": 6}, "busca", False)
    detalhe = ({"modalidade_id": 6}, "compras", True)

    ordenados = sorted(
        [desconhecido, modalidade, detalhe],
        key=collect_module._prioridade_confirmacao,
    )

    assert ordenados == [detalhe, modalidade, desconhecido]


def test_baixar_par_aceita_ocr_e_preserva_hash_original(monkeypatch, tmp_path):
    chamadas = _instalar_download_mock(monkeypatch)
    compra = normalizar_compra(compra_flat(), "feed")
    candidato, _, _ = formar_candidato(
        compra,
        [arquivo(2, "TR", 4, "https://arquivos/tr"), arquivo(3, "ETP", 7, "https://arquivos/etp")],
    )
    resultado = collect_module.baixar_par(
        object(), candidato, Caminhos(tmp_path), ocr=True, idioma_ocr="por"
    )
    assert resultado.aprovado
    assert [d["papel"] for d in resultado.documentos] == ["ETP", "TR"]
    for documento in resultado.documentos:
        assert documento["sha256"] == documento["sha256_original"] == documento["hash_original"]
        assert documento["verificacao"]["ocr"]["usado"] is True
    assert chamadas == ["https://arquivos/etp", "https://arquivos/tr"]


def test_cache_ocr_persistente_reusa_e_separa_hash_idioma_config(
    monkeypatch, tmp_path
):
    caminho = tmp_path / "original.pdf"
    conteudo = b"%PDF-1.4 original imutavel para cache"
    caminho.write_bytes(conteudo)
    chamadas_ocr: list[dict[str, object]] = []

    def verificar_contado(path, **kwargs):
        if kwargs.get("ocr"):
            chamadas_ocr.append(dict(kwargs))
        return _verificacao_mock(
            path,
            ocr=bool(kwargs.get("ocr")),
            idioma=str(kwargs.get("idioma", "por")),
        )

    monkeypatch.setattr(collect_module, "verificar", verificar_contado)
    estado = EstadoColeta(tmp_path / "estado.sqlite3")
    arquivo_meta = {"papel": "ETP", "titulo": "ETP", "url": "https://arquivo"}

    def registrar(hash_original, *, idioma="por", opcoes=None):
        baixado = SimpleNamespace(
            caminho=caminho,
            nome_original="original.pdf",
            sha256=hash_original,
            bytes=len(conteudo),
            extensao="pdf",
            content_type="application/pdf",
        )
        return collect_module._registrar_documento(
            "doc",
            "processo",
            NUMERO,
            arquivo_meta,
            baixado,
            tmp_path,
            estado=estado,
            ocr=True,
            idioma_ocr=idioma,
            opcoes_ocr=opcoes,
        )

    hash_original = hashlib.sha256(conteudo).hexdigest()
    try:
        primeiro = registrar(hash_original, opcoes={"dpi_ocr": 200})
        segundo = registrar(hash_original, opcoes={"dpi_ocr": 200})
        assert len(chamadas_ocr) == 1
        assert primeiro["ocr_cache"]["cache_hit"] is False
        assert segundo["ocr_cache"]["cache_hit"] is True
        assert segundo["ocr_cache"]["pipeline_version"] == collect_module.OCR_PIPELINE_VERSION
        assert segundo["ocr_cache"]["texto_sha256"] == hashlib.sha256(
            segundo["_texto"].encode("utf-8")
        ).hexdigest()

        registrar(hash_original, opcoes={"dpi_ocr": 300})
        registrar(hash_original, idioma="eng", opcoes={"dpi_ocr": 200})
        registrar("b" * 64, opcoes={"dpi_ocr": 200})
        assert len(chamadas_ocr) == 4
        assert caminho.read_bytes() == conteudo
        for documento in (primeiro, segundo):
            assert documento["sha256"] == hash_original
            assert documento["sha256_original"] == hash_original
            assert documento["hash_original"] == hash_original
    finally:
        estado.close()


def test_revisao_recente_ruim_tenta_anterior_utilizavel(monkeypatch, tmp_path):
    chamadas = _instalar_download_mock(monkeypatch, ruim={"https://arquivos/etp-recente"})
    compra = normalizar_compra(compra_flat(), "feed")
    candidato, _, _ = formar_candidato(
        compra,
        [
            arquivo(1, "ETP anterior", 7, "https://arquivos/etp-anterior"),
            arquivo(2, "ETP recente", 7, "https://arquivos/etp-recente"),
            arquivo(3, "TR", 4, "https://arquivos/tr"),
        ],
    )
    resultado = collect_module.baixar_par(object(), candidato, Caminhos(tmp_path))
    assert resultado.aprovado
    assert [d["papel"] for d in resultado.documentos] == ["ETP", "TR"]
    assert chamadas == [
        "https://arquivos/etp-recente",
        "https://arquivos/etp-anterior",
        "https://arquivos/tr",
    ]
    assert len(candidato["revisoes_documentos"]["ETP"]) == 2


def test_policy_negativa_antiga_nao_bloqueia_politica_nova(tmp_path):
    numero = "00000000000000-1-000001/2025"
    caminho = tmp_path / "estado.sqlite3"
    antigo = EstadoColeta(caminho, policy_version="antiga", margem_requisicoes=0)
    antigo.salvar_inspecao(numero, {"numero_controle_pncp": numero}, status="FORA_DO_ESCOPO")
    antigo.close()
    atual = EstadoColeta(caminho, policy_version="nova", margem_requisicoes=0)
    try:
        assert atual.status_inspecao(numero) is None
        assert collect_module._reaproveitar_inspecao(atual, numero) is False
    finally:
        atual.close()


def test_aceitos_legados_de_todas_as_esferas_sao_migrados_sem_download(monkeypatch, tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conteudo = b"%PDF-1.4 legado"
    hash_ = hashlib.sha256(conteudo).hexdigest()
    antigo = EstadoColeta(caminho, policy_version="v1", margem_requisicoes=0)
    for posicao in range(1, 5):
        numero = f"00000000000000-1-{posicao:06d}/2025"
        pasta = tmp_path / "documentos" / numero.replace("/", "-")
        pasta.mkdir(parents=True)
        documentos = []
        for papel in ("ETP", "TR"):
            arquivo_local = pasta / f"{papel.lower()}.pdf"
            arquivo_local.write_bytes(conteudo)
            documentos.append(
                {
                    "documento_id": f"{numero}#{papel}",
                    "processo_id": numero.replace("/", "-"),
                    "papel": papel,
                    "arquivo": str(arquivo_local.relative_to(tmp_path)),
                    "sha256": hash_,
                    "bytes": len(conteudo),
                }
            )
        candidato = {
            "numero_controle_pncp": numero,
            "compra": {
                "numero_controle_pncp": numero,
                "cnpj_orgao": "00000000000000",
                "esfera": "M" if posicao < 4 else "F",
                "modalidade_id": 6,
                "instrumento_convocatorio_codigo": 1,
                "amparo_legal_codigo": 1,
                "amparo_legal_nome": "Lei 14.133/2021, Art. 28, I",
                "objeto": "Aquisição de material de limpeza",
            },
            "documentos_compra": [],
        }
        antigo.salvar_aceito(candidato, documentos)
    antigo.close()

    monkeypatch.setattr(collect_module, "verificar", _verificacao_mock)
    atual = EstadoColeta(caminho, policy_version="v2", margem_requisicoes=0)
    try:
        # Os quatro legados (três municipais e um federal) satisfazem o perfil
        # vigente. Sob o escopo anterior o federal ficava para trás; a migração
        # agora o aproveita sem novo download.
        assert collect_module._migrar_aceitos_legados(atual, tmp_path, log=lambda _: None) == 4
        aceitos = atual.aceitos()
        assert len(aceitos) == 4
        esferas = {
            (candidato.get("compra") or {}).get("esfera") for candidato, _ in aceitos
        }
        assert esferas == {"M", "F"}
    finally:
        atual.close()


def test_migracao_escolhe_promocao_mais_nova_e_preserva_edital(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect_module, "verificar", _verificacao_mock)
    numero = NUMERO
    compra = normalizar_compra(compra_flat(), "feed")
    conteudo = b"%PDF-1.4 cadeia historica"
    hash_ = hashlib.sha256(conteudo).hexdigest()

    def documento(papel: str, nome: str) -> dict:
        caminho = tmp_path / "documentos" / numero.replace("/", "-") / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        return {
            "documento_id": f"{numero}#{papel}",
            "processo_id": numero.replace("/", "-"),
            "papel": papel,
            "arquivo": str(caminho.relative_to(tmp_path)),
            "sha256": hash_,
            "bytes": len(conteudo),
        }

    etp = documento("ETP", "etp.pdf")
    tr = documento("TR", "tr.pdf")
    edital = documento("EDITAL", "edital.pdf")

    antigo = EstadoColeta(tmp_path / "estado.sqlite3", policy_version="v1")
    antigo.salvar_aceito(
        {"numero_controle_pncp": numero, "compra": compra}, [etp, tr]
    )
    antigo.close()
    promovido = EstadoColeta(tmp_path / "estado.sqlite3", policy_version="v2")
    promovido.salvar_aceito(
        {"numero_controle_pncp": numero, "compra": compra}, [etp, tr, edital]
    )
    promovido.close()

    atual = EstadoColeta(tmp_path / "estado.sqlite3", policy_version="v3")
    try:
        assert collect_module._migrar_aceitos_legados(
            atual, tmp_path, log=lambda _: None
        ) == 1
        aceite = atual.aceitos()[0]
        assert {documento["papel"] for documento in aceite[1]} == {
            "ETP",
            "TR",
            "EDITAL",
        }
        resumo = collect_module._catalogar(
            Caminhos(tmp_path),
            atual,
            alvo=1,
            fonte="pncp-contratos",
            log=lambda _: None,
        )
        assert resumo["documentos"] == 3
        processo = json.loads(
            (tmp_path / "catalogo" / "processos.json").read_text(encoding="utf-8")
        )[0]
        assert processo["cadeia"]["EDITAL"]
    finally:
        atual.close()


def test_migracao_completa_aceite_vigente_parcial_sem_perder_elos_legados(
    monkeypatch, tmp_path
):
    """Uma linha v6 parcial ainda deve herdar contrato/edital históricos."""
    monkeypatch.setattr(collect_module, "verificar", _verificacao_mock)
    numero = NUMERO
    compra = normalizar_compra(compra_flat(), "feed")
    conteudo = b"%PDF-1.4 cadeia historica"
    hash_ = hashlib.sha256(conteudo).hexdigest()

    def documento(papel: str, nome: str) -> dict:
        caminho = tmp_path / "documentos" / numero.replace("/", "-") / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        return {
            "documento_id": f"{numero}#{papel}",
            "processo_id": numero.replace("/", "-"),
            "papel": papel,
            "arquivo": str(caminho.relative_to(tmp_path)),
            "sha256": hash_,
            "bytes": len(conteudo),
        }

    documentos = [
        documento("ETP", "etp.pdf"),
        documento("TR", "tr.pdf"),
        documento("EDITAL", "edital.pdf"),
        documento("CONTRATO", "contrato.pdf"),
    ]
    contrato = {
        "numero_controle_pncp": "18025940000109-2-000001/2025",
        "numero_controle_pncp_compra": numero,
        "criterio_vinculo": "numeroControlePncpCompra",
    }
    antigo = EstadoColeta(tmp_path / "estado.sqlite3", policy_version="v1")
    antigo.salvar_aceito(
        {
            "numero_controle_pncp": numero,
            "compra": compra,
            "contrato": contrato,
            "contratos": [contrato],
        },
        documentos,
    )
    antigo.close()

    parcial = EstadoColeta(tmp_path / "estado.sqlite3", policy_version="v2")
    parcial.salvar_aceito(
        {"numero_controle_pncp": numero, "compra": compra}, documentos[:2]
    )
    try:
        assert collect_module._migrar_aceitos_legados(
            parcial, tmp_path, log=lambda _: None
        ) == 1
        candidato, documentos_migrados = parcial.aceitos()[0]
        assert {d["papel"] for d in documentos_migrados} == {
            "ETP",
            "TR",
            "EDITAL",
            "CONTRATO",
        }
        assert candidato["contratos"][0]["numero_controle_pncp_compra"] == numero
    finally:
        parcial.close()


def test_catalogo_nao_rotula_quatro_documentos_sem_vinculo_como_cadeia_nova(
    monkeypatch, tmp_path
):
    """IDs dos quatro papéis sem metadado contrato→compra seguem históricos."""
    monkeypatch.setattr(collect_module, "verificar", _verificacao_mock)
    numero = NUMERO
    compra = normalizar_compra(compra_flat(), "feed")
    conteudo = b"%PDF-1.4 aceite sem vinculo"
    hash_ = hashlib.sha256(conteudo).hexdigest()
    documentos = []
    for papel in ("ETP", "TR", "EDITAL", "CONTRATO"):
        caminho = tmp_path / "documentos" / numero.replace("/", "-") / f"{papel.lower()}.pdf"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        documentos.append(
            {
                "documento_id": f"{numero}#{papel.lower()}",
                "processo_id": numero.replace("/", "-"),
                "papel": papel,
                "arquivo": str(caminho.relative_to(tmp_path)),
                "sha256": hash_,
                "bytes": len(conteudo),
            }
        )

    estado = EstadoColeta(
        tmp_path / "estado.sqlite3",
        policy_version=collect_module.POLICY_VERSION,
        margem_requisicoes=0,
    )
    estado.salvar_aceito(
        {"numero_controle_pncp": numero, "compra": compra}, documentos
    )
    try:
        resumo = collect_module._catalogar(
            Caminhos(tmp_path),
            estado,
            alvo=1,
            fonte="pncp-contratos",
            log=lambda _: None,
        )
        processo = json.loads(
            (tmp_path / "catalogo" / "processos.json").read_text(encoding="utf-8")
        )[0]
        assert processo["collection_policy_version"] != collect_module.POLICY_VERSION
        assert processo["escopo_documental"]["cadeia_completa"] is False
        assert resumo["processos_cadeia_completa"] == 0
    finally:
        estado.close()


def test_coletor_aceita_todas_as_esferas_e_exige_esfera_conhecida(tmp_path):
    """Escopo de todas as esferas: F/E/D/M entram; sem esfera, não.

    A política precisa mudar junto: decisões ficam gravadas por
    (processo, policy_version), então reaproveitar a política municipal faria
    o coletor pular os processos que passaram a ser elegíveis.
    """
    assert collect_module.POLICY_VERSION == "8-cadeia-completa-documentos-utilizaveis"
    assert collect_module._aceitavel(
        normalizar_compra(compra_flat(), "feed"), None
    )[0]

    for esfera in ("F", "E", "D", "M"):
        compra = normalizar_compra(compra_flat(), "feed")
        compra["esfera"] = esfera
        assert collect_module._aceitavel(compra, None)[0] is True, esfera

    # Esfera ausente ou desconhecida continua fora: sem ela não há prova de
    # que a compra é de ente público sob o regime.
    for esfera in (None, "", "X"):
        compra = normalizar_compra(compra_flat(), "feed")
        compra["esfera"] = esfera
        assert collect_module._aceitavel(compra, None)[0] is False, esfera

    # Um filtro restrito a M continua válido e exclui as demais.
    compra_federal = normalizar_compra(compra_flat(), "feed")
    compra_federal["esfera"] = "F"
    assert collect_module._aceitavel(compra_federal, {"M"})[0] is False

    # Um filtro fora da tabela de esferas é erro de uso, não coleta silenciosa.
    with pytest.raises(ValueError, match="subconjunto"):
        collect_module.coletar(tmp_path, esferas={"X"})


def test_filtro_preliminar_adia_campos_ausentes_para_confirmacao():
    compra = normalizar_compra(compra_flat(), "busca")
    compra["instrumento_convocatorio_codigo"] = None
    compra["amparo_legal_codigo"] = None
    compra["amparo_legal_nome"] = None

    assert collect_module._aceitavel(compra, {"M"}, preliminar=True) == (
        True,
        None,
    )
    assert collect_module._aceitavel(compra, {"M"}, preliminar=False)[0] is False

    compra_servico = dict(compra)
    compra_servico["objeto"] = "Prestação de serviços de consultoria técnica"
    assert collect_module._aceitavel(
        compra_servico, {"M"}, preliminar=True
    )[0] is False


def test_recatalogacao_preserva_apenas_controle_negativo_municipal(tmp_path):
    caminhos = Caminhos(tmp_path)
    caminhos.catalogo.mkdir(parents=True)
    supported = {
        "processo_id": "supported",
        "scope_status": "SUPPORTED",
        "orgao": {"esfera": "M"},
    }
    controle = {
        "processo_id": "controle",
        "scope_status": "OUT_OF_SCOPE",
        "orgao": {"esfera": "M"},
    }
    (caminhos.catalogo / "processos.json").write_text(
        json.dumps([supported, controle]), encoding="utf-8"
    )
    (caminhos.catalogo / "documentos.jsonl").write_text(
        "\n".join(
            json.dumps({"processo_id": pid, "documento_id": f"{pid}#etp"})
            for pid in ("supported", "controle")
        ),
        encoding="utf-8",
    )
    (caminhos.catalogo / "relacoes.json").write_text(
        json.dumps(
            {
                "cadeia": [
                    {"processo_id": "supported"},
                    {"processo_id": "controle"},
                ]
            }
        ),
        encoding="utf-8",
    )

    processos, documentos, relacoes = collect_module._controles_catalogados(
        caminhos
    )

    assert [p["processo_id"] for p in processos] == ["controle"]
    assert [d["processo_id"] for d in documentos] == ["controle"]
    assert [r["processo_id"] for r in relacoes] == ["controle"]


def test_revalidacao_descarta_ocr_historico_sem_derivado_auditavel(monkeypatch, tmp_path):
    """OCR sem SHA-256 do derivado, idioma e versão do pipeline não é reaproveitado.

    A policy ``4-municipal-historical-ocr`` exige artefato derivado auditável;
    aceitar na coleta o que o gate rejeita faz o corpus divergir do lote
    aprovado.
    """
    conteudo = b"%PDF-1.4 original imutavel"
    digesto = hashlib.sha256(conteudo).hexdigest()
    documentos = []
    for papel in ("ETP", "TR"):
        arquivo_local = tmp_path / f"{papel.lower()}.pdf"
        arquivo_local.write_bytes(conteudo)
        documentos.append(
            {
                "documento_id": papel,
                "papel": papel,
                "arquivo": arquivo_local.name,
                "sha256": "hash legado divergente",
                "sha256_original": digesto,
                "verificacao": {
                    "abriu": True,
                    "caracteres": 90,
                    "precisa_ocr": False,
                    "ocr_usado": True,
                },
                "_texto": f"texto OCR histórico {papel}",
            }
        )

    def verificacao_normal_sem_texto(_path, **_kwargs):
        resultado = _verificacao_mock(_path)
        resultado.caracteres = 0
        resultado.precisa_ocr = True
        resultado.texto = ""
        return resultado

    monkeypatch.setattr(collect_module, "verificar", verificacao_normal_sem_texto)
    candidato = {"numero_controle_pncp": NUMERO, "compra": normalizar_compra(compra_flat(), "feed")}

    assert collect_module._revalidar_aceito(candidato, documentos, tmp_path) is None


def test_revalidacao_preserva_ocr_historico_com_hash_original(monkeypatch, tmp_path):
    conteudo = b"%PDF-1.4 original imutavel"
    digesto = hashlib.sha256(conteudo).hexdigest()
    documentos = []
    for papel in ("ETP", "TR"):
        arquivo_local = tmp_path / f"{papel.lower()}.pdf"
        arquivo_local.write_bytes(conteudo)
        documentos.append(
            {
                "documento_id": papel,
                "papel": papel,
                "arquivo": arquivo_local.name,
                "sha256": "hash legado divergente",
                "sha256_original": digesto,
                "verificacao": {
                    "abriu": True,
                    "caracteres": 90,
                    "precisa_ocr": False,
                    "ocr_usado": True,
                    "ocr_cache": {
                        "sha256_original": digesto,
                        "texto_sha256": "b" * 64,
                        "idioma": "por",
                        "pipeline_version": "verify-pymupdf-tesseract-v1",
                    },
                },
                "_texto": f"texto OCR histórico {papel}",
            }
        )

    def verificacao_normal_sem_texto(_path, **_kwargs):
        resultado = _verificacao_mock(_path)
        resultado.caracteres = 0
        resultado.precisa_ocr = True
        resultado.texto = ""
        return resultado

    monkeypatch.setattr(collect_module, "verificar", verificacao_normal_sem_texto)
    candidato = {"numero_controle_pncp": NUMERO, "compra": normalizar_compra(compra_flat(), "feed")}
    revalidado = collect_module._revalidar_aceito(candidato, documentos, tmp_path)
    assert revalidado is not None
    assert [d["_texto"] for d in revalidado[1]] == [
        "texto OCR histórico ETP",
        "texto OCR histórico TR",
    ]
    assert all(d["verificacao"]["ocr_usado"] for d in revalidado[1])
    assert all((tmp_path / d["arquivo"]).read_bytes() == conteudo for d in revalidado[1])

    documentos[0]["sha256_original"] = "0" * 64
    assert collect_module._revalidar_aceito(candidato, documentos, tmp_path) is None


def test_margem_deixa_pagina_pendente_sem_chamar_api(monkeypatch, tmp_path):
    chamadas = []

    class FakePncp:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def pagina_contratos_publicados(self, *_args, **_kwargs):
            chamadas.append(True)
            raise AssertionError("a margem deveria impedir a chamada")

    monkeypatch.setattr(collect_module, "Pncp", FakePncp)
    resumo = collect_module.coletar(
        tmp_path,
        data_inicial="20251101",
        data_final="20251130",
        processos=1,
        fonte="pncp-feed",
        max_paginas_feed=1,
        max_requisicoes_dia=15,
        margem_requisicoes=15,
        intervalo=0,
    )
    assert chamadas == []
    assert resumo["paginas_pendentes"] == 1
    assert resumo["parou_por_limite_requisicoes"] is True
