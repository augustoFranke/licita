"""Comportamento público da coleta pela cadeia contrato → compra → quatro anexos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

import licita_corpus.collect as collect_module
from licita_corpus.collect import POLICY_VERSION, _normalizar_contrato, coletar
from licita_corpus.state import EstadoColeta, LimiteRequisicoes


COMPRA = "12345678000199-1-000001/2025"
CONTRATO = "12345678000199-2-000001/2025"


def _pdf_bytes(texto: str) -> bytes:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def _compra(*, modalidade: int = 6, objeto: str = "Aquisição de material de limpeza") -> dict[str, object]:
    return {
        "numeroControlePNCP": COMPRA,
        "anoCompraPncp": 2025,
        "sequencialCompraPncp": 1,
        "orgaoEntidadeCnpj": "12345678000199",
        "orgaoEntidadeRazaoSocial": "ÓRGÃO TESTE",
        "orgaoEntidadeEsferaId": "M",
        "orgaoEntidadePoderId": "E",
        "unidadeOrgaoNomeUnidade": "UNIDADE TESTE",
        "unidadeOrgaoUfSigla": "DF",
        "unidadeOrgaoMunicipioNome": "Brasília",
        "numeroCompra": "1/2025",
        "modalidadeIdPncp": modalidade,
        "modalidadeNome": "Pregão - Eletrônico",
        "tipoInstrumentoConvocatorioCodigoPncp": 1,
        "tipoInstrumentoConvocatorioNome": "Edital",
        "amparoLegalCodigoPncp": 1,
        "amparoLegalNome": "Lei 14.133/2021, Art. 28, I",
        "objetoCompra": objeto,
        "dataPublicacaoPncp": "2025-11-13T22:32:58",
    }


def _contrato_feed() -> dict[str, object]:
    return {
        "numeroControlePNCP": CONTRATO,
        "numeroControlePNCPCompra": COMPRA,
        "tipoContrato": {"id": 1, "nome": "Contrato (termo inicial)"},
        "orgaoEntidadeCnpj": "12345678000199",
        "numeroContratoEmpenho": "1/2025",
        "fornecedorNomeRazaoSocial": "FORNECEDOR TESTE",
        "dataAssinatura": "2025-12-01T00:00:00",
    }


def _anexo(seq: int, titulo: str, tipo: int | None, papel: str) -> dict[str, object]:
    return {
        "sequencialDocumento": seq,
        "titulo": titulo,
        "tipoDocumentoId": tipo,
        "tipoDocumentoNome": titulo,
        "url": f"https://arquivos.test/{papel.lower()}",
        "statusAtivo": True,
    }


def _arquivos_compra(*, sem: set[str] | None = None) -> list[dict[str, object]]:
    sem = sem or set()
    dados = {
        "ETP": _anexo(1, "Estudo Técnico Preliminar", 7, "ETP"),
        "TR": _anexo(2, "Termo de Referência", 4, "TR"),
        "EDITAL": _anexo(3, "Edital do Pregão", 2, "EDITAL"),
    }
    return [anexo for papel, anexo in dados.items() if papel not in sem]


def _arquivos_contrato() -> list[dict[str, object]]:
    return [_anexo(1, "Instrumento contratual", None, "CONTRATO") | {
        "tipoDocumentoNome": "Contrato (termo inicial)"
    }]


class FakePncp:
    """Fake do cliente usado para provar a ordem e a cardinalidade das consultas."""

    eventos: list[str] = []
    compra: dict[str, object] = _compra()
    arquivos_compra_resposta: list[dict[str, object]] = _arquivos_compra()
    arquivos_contrato_resposta: list[dict[str, object]] = _arquivos_contrato()
    feed: list[dict[str, object]] = [_contrato_feed()]

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> "FakePncp":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def pagina_contratos_publicados(self, *_args: object, **_kwargs: object):
        self.eventos.append("feed_contratos")
        return self.feed, 1

    def detalhe_compra(self, *_args: object, **_kwargs: object):
        self.eventos.append("detalhe_compra")
        return self.compra

    def arquivos_compra(self, *_args: object, **_kwargs: object):
        self.eventos.append("arquivos_compra")
        return self.arquivos_compra_resposta

    def arquivos_contrato(self, *_args: object, **_kwargs: object):
        self.eventos.append("arquivos_contrato")
        return self.arquivos_contrato_resposta


def _instalar_download(monkeypatch, *, inutilizavel: set[str] | None = None) -> list[str]:
    chamadas: list[str] = []
    inutilizavel = inutilizavel or set()
    conteudo = _pdf_bytes("conteúdo documental suficiente para a cadeia completa")

    def baixar(_pncp, url, destino, papel, sequencial, titulo):
        chamadas.append(papel)
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{papel.lower()}-{sequencial or 0}.pdf"
        caminho.write_bytes(conteudo)
        return SimpleNamespace(
            caminho=caminho,
            nome_original=f"{papel.lower()}.pdf",
            sha256=hashlib.sha256(conteudo).hexdigest(),
            bytes=len(conteudo),
            extensao="pdf",
            content_type="application/pdf",
        )

    real_verificar = collect_module.verificar

    def verificar(path: Path, **kwargs):
        if any(path.name.startswith(f"{papel.lower()}-") for papel in inutilizavel):
            return SimpleNamespace(
                abriu=True,
                paginas=1,
                caracteres=0,
                precisa_ocr=True,
                erro=None,
                texto="",
                ocr={},
            )
        return real_verificar(path, **kwargs)

    monkeypatch.setattr(collect_module, "baixar_documento", baixar)
    monkeypatch.setattr(collect_module, "verificar", verificar)
    return chamadas


def _executar(monkeypatch, tmp_path, *, fake: type[FakePncp] = FakePncp, **kwargs):
    fake.eventos = []
    monkeypatch.setattr(collect_module, "Pncp", fake)
    return coletar(
        tmp_path,
        data_inicial="20251101",
        data_final="20251130",
        processos=1,
        max_paginas_feed=1,
        max_requisicoes_dia=100,
        margem_requisicoes=0,
        intervalo=0,
        **kwargs,
    )


def test_coleta_nova_consulta_feed_e_anexos_uma_vez_e_publica_quatro(
    monkeypatch, tmp_path
):
    chamadas = _instalar_download(monkeypatch)
    resumo = _executar(monkeypatch, tmp_path)

    assert FakePncp.eventos == [
        "feed_contratos",
        "detalhe_compra",
        "arquivos_compra",
        "arquivos_contrato",
    ]
    assert chamadas == ["ETP", "TR", "EDITAL", "CONTRATO"]
    assert resumo["processos"] == 1
    assert resumo["documentos"] == 4
    assert resumo["processos_cadeia_completa"] == 1
    assert resumo["estrategia"] == "pncp_contratos_para_cadeia_completa"

    processos = json.loads(
        (tmp_path / "catalogo" / "processos.json").read_text(encoding="utf-8")
    )
    processo = processos[0]
    assert processo["collection_policy_version"] == POLICY_VERSION
    assert processo["cadeia"] == {
        "DFD": [],
        "ETP": [f"{COMPRA.replace('/', '-')}#etp-01"],
        "TR": [f"{COMPRA.replace('/', '-')}#tr-02"],
        "EDITAL": [f"{COMPRA.replace('/', '-')}#edital-03"],
        "CONTRATO": [f"{COMPRA.replace('/', '-')}#contrato-01"],
        "PESQUISA_PRECOS": [],
    }
    assert processo["contratos"][0]["numero_controle_pncp_compra"] == COMPRA


def test_publicacao_tipificada_como_edital_nao_substitui_o_edital_real(
    monkeypatch, tmp_path
):
    publicacao = _anexo(9, "Publicação PNCP", 2, "PUBLICACAO") | {
        "dataPublicacaoPncp": "2025-12-10T00:00:00"
    }

    class ComPublicacao(FakePncp):
        arquivos_compra_resposta = [*_arquivos_compra(), publicacao]

    urls: list[str] = []
    conteudo = _pdf_bytes("conteúdo documental suficiente para a cadeia completa")

    def baixar(_pncp, url, destino, papel, sequencial, titulo):
        urls.append(url)
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{papel.lower()}-{sequencial or 0}.pdf"
        caminho.write_bytes(conteudo)
        return SimpleNamespace(
            caminho=caminho,
            nome_original=f"{papel.lower()}.pdf",
            sha256=hashlib.sha256(conteudo).hexdigest(),
            bytes=len(conteudo),
            extensao="pdf",
            content_type="application/pdf",
        )

    monkeypatch.setattr(collect_module, "baixar_documento", baixar)
    resumo = _executar(monkeypatch, tmp_path, fake=ComPublicacao)

    assert resumo["processos"] == 1
    assert "https://arquivos.test/edital" in urls
    assert "https://arquivos.test/publicacao" not in urls


def test_revalidacao_nao_considera_publicacao_como_edital_utilizavel():
    documento = {
        "papel": "EDITAL",
        "titulo": "Publicação PNCP",
        "tipo_documento_id": 2,
        "verificacao": {"abriu": True, "caracteres": 500, "precisa_ocr": False},
    }

    assert collect_module._documento_utilizavel(documento) is False


def test_filtro_de_perfil_ocorre_antes_dos_anexos(monkeypatch, tmp_path):
    _instalar_download(monkeypatch)

    class ForaDoPerfil(FakePncp):
        compra = _compra(modalidade=4)

        def arquivos_compra(self, *_args, **_kwargs):  # pragma: no cover - trava
            raise AssertionError("anexos não podem ser consultados fora do perfil")

        def arquivos_contrato(self, *_args, **_kwargs):  # pragma: no cover - trava
            raise AssertionError("anexos não podem ser consultados fora do perfil")

    resumo = _executar(monkeypatch, tmp_path, fake=ForaDoPerfil)
    assert resumo["processos"] == 0
    assert ForaDoPerfil.eventos == ["feed_contratos", "detalhe_compra"]
    assert json.loads(
        (tmp_path / "catalogo" / "processos_reprovados.json").read_text(
            encoding="utf-8"
        )
    )["processos"][0]["motivo"]


def test_alias_de_fonte_mantem_namespace_do_feed(monkeypatch, tmp_path):
    _instalar_download(monkeypatch)
    resumo = _executar(monkeypatch, tmp_path, fonte="auto")

    assert resumo["fonte_preferencial"] == "pncp-contratos"
    assert resumo["estrategia"] == "pncp_contratos_para_cadeia_completa"


def test_documento_faltante_registra_motivo_sem_aceite_ou_publicacao(
    monkeypatch, tmp_path
):
    chamadas = _instalar_download(monkeypatch)

    class SemEdital(FakePncp):
        arquivos_compra_resposta = _arquivos_compra(sem={"EDITAL"})

    resumo = _executar(monkeypatch, tmp_path, fake=SemEdital)
    assert chamadas == []
    assert resumo["processos"] == 0
    assert not list((tmp_path / "documentos").rglob("*.pdf"))
    reprovados = json.loads(
        (tmp_path / "catalogo" / "processos_reprovados.json").read_text(
            encoding="utf-8"
        )
    )["processos"]
    assert reprovados[0]["numero_controle_pncp"] == COMPRA
    assert "EDITAL" in reprovados[0]["motivo"]


def test_documento_inutilizavel_nao_entra_no_corpus(monkeypatch, tmp_path):
    chamadas = _instalar_download(monkeypatch, inutilizavel={"TR"})
    resumo = _executar(monkeypatch, tmp_path)

    assert chamadas == ["ETP", "TR"]
    assert resumo["processos"] == 0
    assert not (tmp_path / "catalogo" / "processos.json").read_text(
        encoding="utf-8"
    ).strip() or json.loads(
        (tmp_path / "catalogo" / "processos.json").read_text(encoding="utf-8")
    ) == []
    reprovados = json.loads(
        (tmp_path / "catalogo" / "processos_reprovados.json").read_text(
            encoding="utf-8"
        )
    )["processos"]
    assert "TR sem texto utilizável" in reprovados[0]["motivo"]


def test_feed_duplicado_da_mesma_contratacao_nao_repete_anexos(monkeypatch, tmp_path):
    chamadas = _instalar_download(monkeypatch)

    class Duplicado(FakePncp):
        feed = [_contrato_feed(), _contrato_feed()]

    resumo = _executar(monkeypatch, tmp_path, fake=Duplicado)
    assert resumo["processos"] == 1
    assert resumo["contratos_consultados_nesta_execucao"] == 2
    assert chamadas == ["ETP", "TR", "EDITAL", "CONTRATO"]
    assert Duplicado.eventos.count("detalhe_compra") == 1
    assert Duplicado.eventos.count("arquivos_compra") == 1
    assert Duplicado.eventos.count("arquivos_contrato") == 1


def test_tenta_outro_contrato_inicial_sem_repetir_anexos_da_compra(
    monkeypatch, tmp_path
):
    chamadas = _instalar_download(monkeypatch)
    segundo = CONTRATO.replace("000001", "000002")

    class DuasOpcoes(FakePncp):
        feed = [
            _contrato_feed(),
            _contrato_feed() | {"numeroControlePNCP": segundo},
        ]

        def arquivos_contrato(self, _cnpj, _ano, sequencial, **_kwargs):
            self.eventos.append("arquivos_contrato")
            return [] if sequencial == 1 else self.arquivos_contrato_resposta

    resumo = _executar(monkeypatch, tmp_path, fake=DuasOpcoes)

    assert resumo["processos"] == 1
    assert chamadas == ["ETP", "TR", "EDITAL", "CONTRATO"]
    assert DuasOpcoes.eventos.count("detalhe_compra") == 1
    assert DuasOpcoes.eventos.count("arquivos_compra") == 1
    assert DuasOpcoes.eventos.count("arquivos_contrato") == 2


def test_limite_no_detalhe_mantem_pagina_pendente_sem_falso_erro_api(
    monkeypatch, tmp_path
):
    class LimiteNoDetalhe(FakePncp):
        def detalhe_compra(self, *_args, **_kwargs):
            self.eventos.append("detalhe_compra")
            raise LimiteRequisicoes("limite no detalhe")

    resumo = _executar(monkeypatch, tmp_path, fake=LimiteNoDetalhe)

    assert resumo["parou_por_limite_requisicoes"] is True
    assert resumo["paginas_concluidas"] == 0
    assert resumo["paginas_retry"] == 1
    assert resumo["processos"] == 0
    reprovados = json.loads(
        (tmp_path / "catalogo" / "processos_reprovados.json").read_text(
            encoding="utf-8"
        )
    )["processos"]
    assert reprovados == []


def test_limite_no_download_mantem_pagina_pendente_sem_falso_erro_api(
    monkeypatch, tmp_path
):
    _instalar_download(monkeypatch)

    def parar_no_download(*_args, **_kwargs):
        raise LimiteRequisicoes("limite no download")

    monkeypatch.setattr(collect_module, "baixar_documento", parar_no_download)
    resumo = _executar(monkeypatch, tmp_path)

    assert resumo["parou_por_limite_requisicoes"] is True
    assert resumo["paginas_concluidas"] == 0
    assert resumo["paginas_retry"] == 1
    assert resumo["processos"] == 0
    reprovados = json.loads(
        (tmp_path / "catalogo" / "processos_reprovados.json").read_text(
            encoding="utf-8"
        )
    )["processos"]
    assert reprovados == []


def test_estatisticas_da_coleta_nao_misturam_fila_historica(tmp_path):
    with EstadoColeta(tmp_path / "estado.sqlite3", margem_requisicoes=0) as estado:
        estado.criar_tarefa_paginacao(
            "pncp-busca", {"termo": "ETP"}, pagina=1, tamanho_pagina=50
        )
        estado.criar_tarefa_paginacao(
            "pncp-contratos", {"inicio": "2025-01-01"}, pagina=1, tamanho_pagina=500
        )
        resumo = collect_module._estatisticas_tarefas(
            estado, fonte="pncp-contratos"
        )

    assert resumo["tarefas_paginacao"] == 1
    assert resumo["paginas_pendentes"] == 1
    assert resumo["cobertura_incompleta"] is True


def test_vinculo_de_contrato_exige_numero_da_compra_exato():
    with pytest.raises(ValueError, match="vínculo exato"):
        _normalizar_contrato(
            {
                "numeroControlePNCP": CONTRATO,
                "numeroControlePNCPCompra": COMPRA,
            },
            {"numero_controle_pncp": "12345678000199-1-000002/2025"},
        )

    with pytest.raises(ValueError, match="numeroControlePncpCompra"):
        _normalizar_contrato(
            {"numeroControlePNCP": CONTRATO},
            {"numero_controle_pncp": COMPRA},
        )
