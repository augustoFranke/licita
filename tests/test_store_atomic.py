import hashlib
import io
import multiprocessing
import os
import struct
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from licita_corpus import store
from licita_corpus.pncp import PncpNotFound
from licita_corpus.store import baixar_contrato_documentos, baixar_documento


PDF_ANTIGO = b"%PDF-1.4 antigo"
PDF_NOVO = b"%PDF-1.7 novo"


def _caminho_pdf(tmp_path: Path) -> Path:
    return tmp_path / "tr-03-termo-de-referencia.pdf"


class PncpComPdf:
    def __init__(self, conteudo: bytes = PDF_NOVO, nome_original: str = "origem.pdf") -> None:
        self.conteudo = conteudo
        self.nome_original = nome_original
        self.chamadas = 0

    def baixar(self, url: str):
        self.chamadas += 1
        return self.conteudo, "application/pdf", self.nome_original


class PncpComPdfBarreira(PncpComPdf):
    def __init__(self, conteudo: bytes, barreira) -> None:
        super().__init__(conteudo)
        self.barreira = barreira

    def baixar(self, url: str):
        self.chamadas += 1
        self.barreira.wait(timeout=10)
        return self.conteudo, "application/pdf", self.nome_original


def _baixar_em_processo(destino: str, conteudo: bytes, barreira, fila) -> None:
    try:
        resultado = baixar_documento(
            PncpComPdfBarreira(conteudo, barreira),
            "http://exemplo/documento",
            Path(destino),
            "TR",
            3,
            "Termo de Referência",
            reaproveitar=False,
        )
        fila.put(("ok", resultado.sha256 if resultado else None))
    except BaseException as erro:  # devolve a falha ao processo-pai
        fila.put(("erro", repr(erro)))


def _docx_bytes(documento: bytes | str = "<w:document/>", *, deflated: bool = False) -> bytes:
    buffer = io.BytesIO()
    compressao = zipfile.ZIP_DEFLATED if deflated else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", compression=compressao) as arquivo:
        arquivo.writestr("word/document.xml", documento)
    return buffer.getvalue()


def _docx_deflate_corrompido() -> bytes:
    dados = bytearray(_docx_bytes("<w:document>conteudo</w:document>", deflated=True))
    with zipfile.ZipFile(io.BytesIO(dados)) as arquivo:
        informacao = arquivo.getinfo("word/document.xml")
    nome_len, extra_len = struct.unpack_from("<HH", dados, informacao.header_offset + 26)
    inicio = informacao.header_offset + 30 + nome_len + extra_len
    dados[inicio + max(0, informacao.compress_size // 2)] ^= 0xFF
    return bytes(dados)


def test_escrita_falha_remove_part_e_preserva_arquivo_final(tmp_path, monkeypatch):
    caminho = _caminho_pdf(tmp_path)
    caminho.write_bytes(PDF_ANTIGO)
    pncp = PncpComPdf()

    def fsync_falha(descritor: int) -> None:
        raise OSError("falha simulada ao sincronizar o arquivo")

    monkeypatch.setattr(store.os, "fsync", fsync_falha)

    with pytest.raises(OSError, match="sincronizar"):
        baixar_documento(
            pncp,
            "http://exemplo/documento",
            tmp_path,
            "TR",
            3,
            "Termo de Referência",
            reaproveitar=False,
        )

    assert caminho.read_bytes() == PDF_ANTIGO
    assert list(tmp_path.glob("*.part")) == []


def test_escrita_faz_replace_atomico_e_nao_deixa_part(tmp_path, monkeypatch):
    chamadas_fsync: list[int] = []
    chamadas_replace: list[tuple[Path, Path]] = []
    replace_real = store.os.replace
    fsync_real = store.os.fsync

    def fsync(descritor: int) -> None:
        chamadas_fsync.append(descritor)
        fsync_real(descritor)

    def replace(origem: str | bytes | Path, destino: str | bytes | Path) -> None:
        origem_path = Path(origem)
        destino_path = Path(destino)
        assert origem_path.parent == tmp_path
        assert origem_path.name.endswith(".part")
        assert origem_path.exists()
        chamadas_replace.append((origem_path, destino_path))
        replace_real(origem, destino)

    monkeypatch.setattr(store.os, "fsync", fsync)
    monkeypatch.setattr(store.os, "replace", replace)

    resultado = baixar_documento(
        PncpComPdf(),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is not None
    assert resultado.caminho.read_bytes() == PDF_NOVO
    assert len(chamadas_fsync) >= 2  # arquivo e diretório
    assert len(chamadas_replace) == 1
    origem, destino = chamadas_replace[0]
    assert origem.parent == tmp_path
    assert origem.name.startswith(f".{destino.name}.")
    assert origem.name.endswith(".part")
    assert origem != destino.with_name(f"{destino.name}.part")
    assert destino == _caminho_pdf(tmp_path)
    assert list(tmp_path.glob("*.part")) == []


def test_replace_falhando_remove_temp_e_preserva_arquivo_final(tmp_path, monkeypatch):
    caminho = _caminho_pdf(tmp_path)
    caminho.write_bytes(PDF_ANTIGO)

    def replace_falha(origem: str | bytes | Path, destino: str | bytes | Path) -> None:
        assert Path(origem).exists()
        raise OSError("falha simulada no replace")

    monkeypatch.setattr(store.os, "replace", replace_falha)

    with pytest.raises(OSError, match="replace"):
        baixar_documento(
            PncpComPdf(),
            "http://exemplo/documento",
            tmp_path,
            "TR",
            3,
            "Termo de Referência",
            reaproveitar=False,
        )

    assert caminho.read_bytes() == PDF_ANTIGO
    assert list(tmp_path.glob("*.part")) == []


def test_arquivo_part_nao_e_reutilizado(tmp_path):
    parcial = _caminho_pdf(tmp_path).with_name("tr-03-termo-de-referencia.pdf.part")
    parcial.write_bytes(PDF_ANTIGO)
    pncp = PncpComPdf()

    resultado = baixar_documento(
        pncp,
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert pncp.chamadas == 1
    assert resultado is not None
    assert resultado.caminho == _caminho_pdf(tmp_path)
    assert resultado.caminho.read_bytes() == PDF_NOVO
    assert not parcial.exists()


def test_reuso_valido_nao_consulta_a_rede(tmp_path):
    caminho = _caminho_pdf(tmp_path)
    caminho.write_bytes(PDF_ANTIGO)
    parcial = caminho.with_name(f"{caminho.name}.part")
    parcial.write_bytes(PDF_NOVO)

    class PncpQueNaoPodeSerChamado:
        def baixar(self, url: str):
            raise AssertionError("arquivo válido deveria ser reutilizado")

    resultado = baixar_documento(
        PncpQueNaoPodeSerChamado(),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is not None
    assert resultado.ja_existia is True
    assert resultado.caminho == caminho
    assert resultado.sha256 == hashlib.sha256(PDF_ANTIGO).hexdigest()
    assert not parcial.exists()


@pytest.mark.parametrize(
    "conteudo_existente", [b"", b"PK\x03\x04" + "não é um PDF".encode()]
)
def test_reuso_rejeita_vazio_e_assinatura_incompativel(tmp_path, conteudo_existente):
    caminho = _caminho_pdf(tmp_path)
    caminho.write_bytes(conteudo_existente)
    pncp = PncpComPdf()

    resultado = baixar_documento(
        pncp,
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert pncp.chamadas == 1
    assert resultado is not None
    assert resultado.ja_existia is False
    assert caminho.read_bytes() == PDF_NOVO


def test_zip_falso_com_nome_de_docx_nao_e_baixado(tmp_path):
    falso = b"PK\x03\x04word/document.xml"
    pncp = PncpComPdf(falso, "origem.docx")

    assert store.identificar_extensao(falso, "origem.docx") == "zip"
    resultado = baixar_documento(
        pncp, "http://exemplo/documento", tmp_path, "TR", 3, "Termo de Referência"
    )

    assert resultado is None
    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("tr-03-termo-de-referencia.*")) == []


def test_docx_so_e_baixado_com_zip_valido_e_corpo_word(tmp_path):
    conteudo = _docx_bytes()
    resultado = baixar_documento(
        PncpComPdf(conteudo, "origem.pdf"),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is not None
    assert resultado.extensao == "docx"
    assert resultado.caminho.suffix == ".docx"
    assert resultado.caminho.read_bytes() == conteudo
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize(
    "documento", [b"", b"lixo", b"<w:document>"]
)
def test_docx_rejeita_xml_vazio_ou_malformado(tmp_path, documento):
    conteudo = _docx_bytes(documento)

    assert store.identificar_extensao(conteudo, "origem.docx") == "zip"
    resultado = baixar_documento(
        PncpComPdf(conteudo, "origem.docx"),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is None
    assert not list(tmp_path.glob("tr-03-termo-de-referencia.*"))
    assert list(tmp_path.glob("*.part")) == []


def test_docx_rejeita_deflate_corrompido(tmp_path):
    conteudo = _docx_deflate_corrompido()

    assert store.identificar_extensao(conteudo, "origem.docx") == "zip"
    resultado = baixar_documento(
        PncpComPdf(conteudo, "origem.docx"),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is None
    assert list(tmp_path.glob("*.part")) == []


def test_extensao_enganosa_nao_faz_conteudo_textual_entrar_no_escopo(tmp_path):
    resultado = baixar_documento(
        PncpComPdf(b"texto que nao e PDF", "origem.pdf"),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is None
    assert not list(tmp_path.glob("tr-03-termo-de-referencia.*"))


def test_fallback_de_nome_publico_e_sanitizado():
    extensao = store.identificar_extensao(b"conteudo sem assinatura", "../../arquivo.PDF?download")

    assert extensao.isascii()
    assert extensao.isalnum()
    assert 1 <= len(extensao) <= 8
    assert "/" not in extensao


@pytest.mark.parametrize(
    ("papel", "prefixo"),
    [("ETP", "etp"), ("TR", "tr"), ("CONTRATO", "contrato")],
)
def test_papeis_normais_continuam_no_nome_do_arquivo(tmp_path, papel, prefixo):
    resultado = baixar_documento(
        PncpComPdf(),
        "http://exemplo/documento",
        tmp_path,
        papel,
        3,
        "Documento",
    )

    assert resultado is not None
    assert resultado.caminho.name.startswith(f"{prefixo}-03-")
    assert resultado.caminho.parent == tmp_path.resolve()


@pytest.mark.parametrize("papel", ["../../fora*", "TR?[glob]", "../ETP"])
def test_papel_e_componente_seguro_contra_traversal_e_glob(tmp_path, papel):
    resultado = baixar_documento(
        PncpComPdf(),
        "http://exemplo/documento",
        tmp_path,
        papel,
        3,
        "Documento",
    )

    assert resultado is not None
    assert resultado.caminho.parent == tmp_path.resolve()
    assert resultado.caminho.name == resultado.caminho.name.strip(".")
    assert not any(caractere in resultado.caminho.name for caractere in "/\\*?[]")
    assert resultado.caminho.read_bytes() == PDF_NOVO


@pytest.mark.parametrize("modo", ["vazio", "not_found"])
def test_retorno_vazio_ou_not_found_limpa_residuos(tmp_path, modo):
    parcial = _caminho_pdf(tmp_path).with_name(".download-antigo.part")
    parcial.write_bytes(PDF_ANTIGO)

    class PncpSemArquivo:
        def baixar(self, url: str):
            if modo == "not_found":
                raise PncpNotFound("arquivo ausente")
            return b"", None, "origem.pdf"

    resultado = baixar_documento(
        PncpSemArquivo(),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
    )

    assert resultado is None
    assert list(tmp_path.glob("*.part")) == []


def test_concorrencia_no_mesmo_destino_nao_expoe_escrita_parcial(tmp_path):
    caminho = _caminho_pdf(tmp_path)
    caminho.write_bytes(PDF_ANTIGO)
    conteudos = (
        b"%PDF-1.4 " + b"A" * 256_000,
        b"%PDF-1.7 " + b"B" * 256_000,
    )
    barreira_download = threading.Barrier(2)

    class PncpConcorrente(PncpComPdf):
        def baixar(self, url: str):
            self.chamadas += 1
            barreira_download.wait(timeout=5)
            return self.conteudo, "application/pdf", "origem.pdf"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuros = [
            executor.submit(
                baixar_documento,
                PncpConcorrente(conteudo),
                "http://exemplo/documento",
                tmp_path,
                "TR",
                3,
                "Termo de Referência",
                False,
            )
            for conteudo in conteudos
        ]
        resultados = [futuro.result(timeout=10) for futuro in futuros]

    final = caminho.read_bytes()
    sha_final = hashlib.sha256(final).hexdigest()
    assert all(resultado is not None for resultado in resultados)
    assert all(resultado.sha256 == sha_final for resultado in resultados if resultado)
    assert final in conteudos
    assert list(tmp_path.glob("*.part")) == []


def test_duas_instancias_usam_lock_canonico_e_sha_do_final(tmp_path):
    if os.name != "posix" or store.fcntl is None or not hasattr(os, "fork"):
        pytest.skip("lock cross-process disponível apenas em Unix")

    alias = tmp_path.parent / f"{tmp_path.name}-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    conteudos = (
        b"%PDF-1.4 " + b"A" * 128_000,
        b"%PDF-1.7 " + b"B" * 128_000,
    )
    contexto = multiprocessing.get_context("fork")
    barreira = contexto.Barrier(2)
    fila = contexto.Queue()
    processos = [
        contexto.Process(
            target=_baixar_em_processo,
            args=(str(destino), conteudo, barreira, fila),
        )
        for destino, conteudo in zip((tmp_path, alias), conteudos)
    ]
    for processo in processos:
        processo.start()
    for processo in processos:
        processo.join(timeout=15)

    assert all(processo.exitcode == 0 for processo in processos)
    mensagens = [fila.get(timeout=2) for _ in processos]
    assert all(tipo == "ok" and valor for tipo, valor in mensagens), mensagens

    caminho = _caminho_pdf(tmp_path)
    sha_final = hashlib.sha256(caminho.read_bytes()).hexdigest()
    assert [valor for _tipo, valor in mensagens] == [sha_final, sha_final]
    assert len(list(tmp_path.glob(".licita-*.lock"))) == 1
    assert list(tmp_path.glob("*.part")) == []


def test_baixar_contrato_sem_documentos_faz_limpeza(tmp_path):
    (tmp_path / "residuo.part").write_bytes(PDF_ANTIGO)

    class PncpSemDocumentos:
        def arquivos_contrato(self, cnpj, ano, sequencial):
            return []

    resultado = baixar_contrato_documentos(
        PncpSemDocumentos(),
        {"cnpj_orgao": "1", "ano_contrato": 2025, "sequencial_contrato": 3},
        tmp_path,
    )

    assert resultado == []
    assert list(tmp_path.glob("*.part")) == []


def test_limpeza_de_contrato_preserva_temporario_ativo(tmp_path, monkeypatch):
    criado = threading.Event()
    liberar = threading.Event()
    parciais: list[Path] = []
    mkstemp_real = store.tempfile.mkstemp

    def mkstemp_pausado(*args, **kwargs):
        descritor, nome = mkstemp_real(*args, **kwargs)
        parciais.append(Path(nome))
        criado.set()
        assert liberar.wait(timeout=10)
        return descritor, nome

    monkeypatch.setattr(store.tempfile, "mkstemp", mkstemp_pausado)
    with ThreadPoolExecutor(max_workers=1) as executor:
        futuro = executor.submit(
            baixar_documento,
            PncpComPdf(),
            "http://exemplo/documento",
            tmp_path,
            "TR",
            3,
            "Termo de Referência",
            False,
        )
        assert criado.wait(timeout=5)
        assert parciais and parciais[0].exists()

        class PncpSemDocumentos:
            def arquivos_contrato(self, cnpj, ano, sequencial):
                return []

        assert (
            baixar_contrato_documentos(
                PncpSemDocumentos(),
                {"cnpj_orgao": "1", "ano_contrato": 2025, "sequencial_contrato": 3},
                tmp_path,
            )
            == []
        )
        assert parciais[0].exists()
        liberar.set()
        resultado = futuro.result(timeout=10)

    assert resultado is not None
    assert list(tmp_path.glob("*.part")) == []


def test_fsync_de_diretorio_falha_apos_replace_sem_invalidar_final(tmp_path, monkeypatch):
    caminho = _caminho_pdf(tmp_path)
    caminho.write_bytes(PDF_ANTIGO)

    def fsync_diretorio_falha(diretorio: Path) -> None:
        assert caminho.read_bytes() == PDF_NOVO
        raise OSError("falha simulada no diretório")

    monkeypatch.setattr(store, "_fsync_diretorio", fsync_diretorio_falha)
    resultado = baixar_documento(
        PncpComPdf(),
        "http://exemplo/documento",
        tmp_path,
        "TR",
        3,
        "Termo de Referência",
        reaproveitar=False,
    )

    assert resultado is not None
    assert resultado.sha256 == hashlib.sha256(caminho.read_bytes()).hexdigest()
    assert caminho.read_bytes() == PDF_NOVO
    assert list(tmp_path.glob("*.part")) == []
