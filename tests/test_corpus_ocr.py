"""Testes determinísticos do fallback OCR do corpus."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pymupdf
import pytest

import licita_corpus.verify as verify_module
from licita_corpus.verify import (
    MAX_BYTES_SAIDA_OCR,
    MAX_MEGAPIXELS_OCR,
    MAX_PAGINAS_OCR,
    MAX_TEMPO_OCR_DOCUMENTO,
    MAX_TEMPO_OCR_PAGINA,
    MIN_CARACTERES_POR_PAGINA,
    MIN_CONFIANCA_OCR,
    MIN_PALAVRAS_POR_PAGINA,
    verificar,
)


TSV_CABECALHO = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    "left\ttop\twidth\theight\tconf\ttext\n"
)
TEXTO_OCR = "Texto reconhecido pelo OCR com qualidade suficiente para validar a página"


def _tsv(texto: str, confianca: object = 90.0) -> str:
    linhas = [TSV_CABECALHO.rstrip("\n")]
    for posicao, palavra in enumerate(texto.split(), start=1):
        conf = "" if confianca is None else str(confianca)
        linhas.append(
            f"5\t1\t1\t1\t1\t{posicao}\t0\t0\t1\t1\t{conf}\t{palavra}"
        )
    return "\n".join(linhas) + "\n"


def _png_branco() -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 80, 50), False)
    pixmap.clear_with(255)
    return pixmap.tobytes("png")


def _pdf_image(caminho: Path, quantidade: int = 1) -> None:
    imagem = _png_branco()
    documento = pymupdf.open()
    for _ in range(quantidade):
        pagina = documento.new_page(width=500, height=300)
        pagina.insert_image(pagina.rect, stream=imagem)
    documento.save(caminho)
    documento.close()


def _pdf_misto(caminho: Path) -> None:
    imagem = _png_branco()
    documento = pymupdf.open()
    pagina = documento.new_page(width=500, height=300)
    pagina.insert_image(pagina.rect, stream=imagem)
    pagina = documento.new_page(width=500, height=300)
    pagina.insert_text((40, 60), "Texto digital suficiente para esta página do documento.", fontsize=11)
    documento.save(caminho)
    documento.close()


def _pdf_texto(caminho: Path, texto: str) -> None:
    documento = pymupdf.open()
    pagina = documento.new_page(width=600, height=300)
    pagina.insert_text((40, 60), texto, fontsize=11)
    documento.save(caminho)
    documento.close()


class _FakeProcess:
    def __init__(self, fake: "_TesseractFake", argumentos: list[str], codigo: int) -> None:
        self.fake = fake
        self.argumentos = argumentos
        self.codigo = codigo
        self.vivo = (
            argumentos[-1] == "tsv"
            and (fake.timeout or fake.mantem_vivo)
        )
        self.morto = False
        self.kill_count = 0
        self.wait_count = 0

    def poll(self) -> int | None:
        if self.vivo and not self.morto:
            if self.fake.escrever_durante_execucao and self.argumentos[-1] == "tsv":
                Path(f"{self.argumentos[2]}.tsv").write_bytes(
                    b"x" * (MAX_BYTES_SAIDA_OCR + 1)
                )
            return None
        return self.codigo

    def kill(self) -> None:
        self.kill_count += 1
        self.morto = True
        self.vivo = False
        self.fake.processos_mortos += 1

    def wait(self) -> int:
        self.wait_count += 1
        self.vivo = False
        return self.codigo


class _TesseractFake:
    def __init__(
        self,
        *,
        saida_tsv: str | None = None,
        codigo: int = 0,
        erro: str = "",
        timeout: bool = False,
        saida_grande: bool = False,
        mantem_vivo: bool = False,
        escrever_durante_execucao: bool = False,
        saidas_tsv_por_pagina: list[str] | None = None,
        saida_especial: str | None = None,
        erro_grande: bool = False,
    ) -> None:
        self.saida_tsv = saida_tsv if saida_tsv is not None else _tsv(TEXTO_OCR)
        self.codigo = codigo
        self.erro = erro
        self.timeout = timeout
        self.saida_grande = saida_grande
        self.mantem_vivo = mantem_vivo
        self.escrever_durante_execucao = escrever_durante_execucao
        self.saidas_tsv_por_pagina = saidas_tsv_por_pagina
        self.saida_especial = saida_especial
        self.erro_grande = erro_grande
        self.chamadas: list[tuple[list[str], dict[str, object]]] = []
        self.diretorios_temporarios: list[Path] = []
        self.processos: list[_FakeProcess] = []
        self.processos_mortos = 0

    def __call__(self, argumentos: list[str], **opcoes: object) -> _FakeProcess:
        self.chamadas.append((argumentos, opcoes))
        stdout = opcoes["stdout"]
        stderr = opcoes["stderr"]
        assert hasattr(stdout, "write")
        assert hasattr(stderr, "write")
        if argumentos == ["tesseract", "--list-langs"]:
            stdout.write(b'List of available languages in "tessdata":\npor\n')
            processo = _FakeProcess(self, argumentos, 0)
            self.processos.append(processo)
            return processo

        self.diretorios_temporarios.append(Path(argumentos[2]).parent)
        if self.timeout:
            processo = _FakeProcess(self, argumentos, 0)
            self.processos.append(processo)
            return processo
        if self.codigo:
            stderr.write(self.erro.encode("utf-8"))
            processo = _FakeProcess(self, argumentos, self.codigo)
            self.processos.append(processo)
            return processo

        caminho_tsv = Path(f"{argumentos[2]}.tsv")
        pagina = len(self.diretorios_temporarios)
        if self.saida_especial is not None:
            caminho_tsv.unlink(missing_ok=True)
            if self.saida_especial == "fifo":
                os.mkfifo(caminho_tsv)
            elif self.saida_especial == "symlink":
                alvo = caminho_tsv.with_name("alvo.tsv")
                alvo.write_text(self.saida_tsv, encoding="utf-8")
                caminho_tsv.symlink_to(alvo)
            elif self.saida_especial == "diretorio":
                caminho_tsv.mkdir()
            else:  # pragma: no cover
                raise AssertionError(self.saida_especial)
        elif self.erro_grande:
            stderr.write(b"e" * (MAX_BYTES_SAIDA_OCR // 2 + 1))
            caminho_tsv.write_bytes(b"x" * (MAX_BYTES_SAIDA_OCR // 2 + 1))
        elif self.saida_grande or self.escrever_durante_execucao:
            caminho_tsv.write_bytes(b"x" * (MAX_BYTES_SAIDA_OCR + 1))
        else:
            saida = (
                self.saidas_tsv_por_pagina[pagina - 1]
                if self.saidas_tsv_por_pagina is not None
                else self.saida_tsv
            )
            caminho_tsv.write_text(saida, encoding="utf-8")
        processo = _FakeProcess(self, argumentos, 0)
        self.processos.append(processo)
        return processo


def _instalar_fake(monkeypatch, fake: _TesseractFake) -> None:
    monkeypatch.setattr(verify_module.shutil, "which", lambda _executavel: "/fake/tesseract")
    monkeypatch.setattr(verify_module.subprocess, "Popen", fake)


def test_verificar_path_e_pdf_image_only_sao_compativeis_e_nao_mutam_original(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "image-only.pdf"
    _pdf_image(caminho)
    antes = caminho.read_bytes()
    hash_antes = hashlib.sha256(antes).hexdigest()

    def nao_deveria_ser_chamado(_executavel: str) -> str:
        raise AssertionError("verificar(path) não deve procurar Tesseract")

    monkeypatch.setattr(verify_module.shutil, "which", nao_deveria_ser_chamado)
    resultado = verificar(caminho)

    assert resultado.abriu is True
    assert resultado.paginas == 1
    assert resultado.caracteres == 0
    assert resultado.precisa_ocr is True
    assert resultado.texto == ""
    assert resultado.paginas_avaliadas[0].precisa_ocr is True
    assert caminho.read_bytes() == antes
    assert hashlib.sha256(caminho.read_bytes()).hexdigest() == hash_antes
    assert resultado.ocr["paginas"] == []
    assert resultado.ocr["confianca_media"] is None
    assert resultado.ocr["erros"] == []


def test_extracao_longa_com_caracteres_de_controle_exige_ocr() -> None:
    texto_corrompido = ("\x08\x0e\x0fABC " * 80).strip()
    assert len(texto_corrompido) > MIN_CARACTERES_POR_PAGINA
    assert verify_module._texto_insuficiente(texto_corrompido) is True
    assert verify_module._texto_insuficiente(
        "Texto digital suficiente e perfeitamente legível para esta página."
    ) is False


def test_ocr_usa_tsv_em_disco_so_nas_paginas_necessarias_e_limpa_temporario(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "misto.pdf"
    _pdf_misto(caminho)
    antes = caminho.read_bytes()
    fake = _TesseractFake()
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True, idioma="por")

    assert resultado.abriu is True
    assert resultado.erro is None
    assert resultado.precisa_ocr is False
    assert resultado.utilizavel is True
    assert resultado.ocr_usado is True
    assert resultado.ocr_motor == "tesseract"
    assert resultado.ocr_idioma == "por"
    assert resultado.paginas_ocr == (1,)
    assert resultado.paginas_ocr_tentadas == (1,)
    assert resultado.ocr_confianca_media == pytest.approx(90.0)
    assert resultado.paginas_avaliadas[0].confianca_media == pytest.approx(90.0)
    assert resultado.texto_por_pagina == (TEXTO_OCR, "Texto digital suficiente para esta página do documento.\n")
    assert resultado.texto_original_por_pagina == ("", "Texto digital suficiente para esta página do documento.\n")
    assert resultado.paginas_avaliadas[0].caracteres >= MIN_CARACTERES_POR_PAGINA
    assert resultado.paginas_avaliadas[0].palavras >= MIN_PALAVRAS_POR_PAGINA
    assert resultado.paginas_avaliadas[0].ocr_usado is True
    assert resultado.paginas_avaliadas[1].ocr_usado is False
    assert caminho.read_bytes() == antes

    assert len(fake.chamadas) == 2
    assert fake.chamadas[0][0] == ["tesseract", "--list-langs"]
    ocr_args, ocr_options = fake.chamadas[1]
    assert ocr_args[-1] == "tsv"
    assert Path(ocr_args[1]).suffix == ".png"
    assert Path(f"{ocr_args[2]}.tsv").suffix == ".tsv"
    assert "capture_output" not in ocr_options
    assert "timeout" not in ocr_options
    assert fake.diretorios_temporarios
    assert not fake.diretorios_temporarios[0].exists()


def test_ocr_rejeita_baixa_confianca_e_preserva_pagina_original(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "baixa-confianca.pdf"
    _pdf_image(caminho)
    antes = caminho.read_bytes()
    fake = _TesseractFake(saida_tsv=_tsv(TEXTO_OCR, 20.0))
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.ocr_usado is False
    assert resultado.paginas_ocr == ()
    assert resultado.paginas_ocr_tentadas == (1,)
    assert resultado.texto == ""
    assert resultado.texto_original == ""
    assert resultado.precisa_ocr is True
    assert resultado.ocr_confianca_media == pytest.approx(20.0)
    assert resultado.paginas_avaliadas[0].confianca_media == pytest.approx(20.0)
    assert resultado.paginas_avaliadas[0].erro_ocr is not None
    assert "confiança" in (resultado.erro or "")
    assert resultado.ocr["erros"]
    assert caminho.read_bytes() == antes


def test_ocr_rejeita_saida_com_menos_de_oito_palavras(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "poucas-palavras.pdf"
    _pdf_image(caminho)
    fake = _TesseractFake(
        saida_tsv=_tsv("primeira segunda terceira quarta quinta sexta sétima", 90.0)
    )
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.texto == ""
    assert resultado.ocr_usado is False
    assert resultado.paginas_ocr_tentadas == (1,)
    assert "palavras" in (resultado.erro or "")
    assert resultado.paginas_avaliadas[0].palavras == 0


def test_timeout_expired_e_retorno_nao_zero_nao_invalidam_pdf(
    tmp_path: Path, monkeypatch
) -> None:
    caminho_timeout = tmp_path / "timeout.pdf"
    _pdf_image(caminho_timeout)
    fake_timeout = _TesseractFake(timeout=True)
    _instalar_fake(monkeypatch, fake_timeout)
    timeout_resultado = verificar(
        caminho_timeout,
        ocr=True,
        tempo_total_ocr=1.0,
        tempo_pagina_ocr=0.1,
    )
    assert timeout_resultado.abriu is True
    assert timeout_resultado.texto == ""
    assert timeout_resultado.precisa_ocr is True
    assert "TimeoutExpired" in (timeout_resultado.erro or "")
    assert fake_timeout.processos[1].kill_count == 1
    assert fake_timeout.processos[1].wait_count == 1

    caminho_codigo = tmp_path / "codigo.pdf"
    _pdf_image(caminho_codigo)
    fake_codigo = _TesseractFake(codigo=7, erro="falha determinística")
    _instalar_fake(monkeypatch, fake_codigo)
    codigo_resultado = verificar(caminho_codigo, ocr=True)
    assert codigo_resultado.abriu is True
    assert codigo_resultado.texto == ""
    assert "não-zero" in (codigo_resultado.erro or "")
    assert "falha determinística" in (codigo_resultado.erro or "")


def test_timeout_total_monotonic_interrompe_antes_de_executar_tesseract(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "total-timeout.pdf"
    _pdf_image(caminho)
    chamadas: list[list[str]] = []

    def nao_deveria_executar(argumentos, **_opcoes):
        chamadas.append(argumentos)
        raise AssertionError("o orçamento total já expirou")

    monkeypatch.setattr(verify_module.subprocess, "Popen", nao_deveria_executar)
    valores = iter((0.0, 301.0))
    monkeypatch.setattr(verify_module, "monotonic", lambda: next(valores))

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.texto == ""
    assert resultado.precisa_ocr is True
    assert "tempo total" in (resultado.erro or "")
    assert chamadas == []


def test_saida_tsv_acima_de_2mb_e_rejeitada_sem_residuo(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "saida-grande.pdf"
    _pdf_image(caminho)
    fake = _TesseractFake(saida_grande=True)
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.texto == ""
    assert resultado.precisa_ocr is True
    assert "limite" in (resultado.erro or "")
    assert resultado.paginas_ocr == ()
    assert fake.diretorios_temporarios
    assert not fake.diretorios_temporarios[0].exists()


def test_tsv_malformado_csv_error_na_iteracao_nao_interrompe_paginas_seguintes(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "tsv-malformado.pdf"
    _pdf_image(caminho, quantidade=2)
    malformado = (
        TSV_CABECALHO
        + "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\t\"sem fechamento\n"
    )
    fake = _TesseractFake(saidas_tsv_por_pagina=[malformado, _tsv(TEXTO_OCR)])
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.paginas_ocr_tentadas == (1, 2)
    assert resultado.paginas_ocr == (2,)
    assert resultado.texto_por_pagina[0] == ""
    assert resultado.texto_por_pagina[1] == TEXTO_OCR
    assert "TSV inválido" in (resultado.erro or "")
    assert all(not diretorio.exists() for diretorio in fake.diretorios_temporarios)


def test_parsear_tsv_captura_csv_error_durante_iteracao() -> None:
    malformado = (
        TSV_CABECALHO
        + "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\t\"sem fechamento\n"
    )

    with pytest.raises(verify_module._OcrErro, match="TSV inválido"):
        verify_module._parsear_tsv(malformado, 1)


@pytest.mark.parametrize(
    "confianca", [None, "", "inválida", "-1", "101", "nan", "inf"]
)
def test_confianca_ausente_ou_invalida_nao_aceita_ocr(
    tmp_path: Path, monkeypatch, confianca: object
) -> None:
    caminho = tmp_path / "confianca-invalida.pdf"
    _pdf_image(caminho)
    fake = _TesseractFake(saida_tsv=_tsv(TEXTO_OCR, confianca))
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.paginas_ocr == ()
    assert resultado.paginas_ocr_tentadas == (1,)
    assert resultado.ocr_confianca_media is None
    assert resultado.paginas_avaliadas[0].confianca_media is None
    assert "confiança" in (resultado.erro or "")


@pytest.mark.parametrize("especial", ["fifo", "symlink", "diretorio"])
def test_saida_tsv_especial_ou_symlink_e_rejeitada_sem_leitura_bloqueante(
    tmp_path: Path, monkeypatch, especial: str
) -> None:
    if especial == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo não disponível neste sistema")
    caminho = tmp_path / f"saida-{especial}.pdf"
    _pdf_image(caminho)
    fake = _TesseractFake(saida_especial=especial)
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.texto == ""
    assert resultado.paginas_ocr == ()
    assert "regular" in (resultado.erro or "")
    assert fake.processos[1].wait_count == 1
    assert all(not diretorio.exists() for diretorio in fake.diretorios_temporarios)


def test_limite_combinado_tsv_stderr_e_mata_processo_em_execucao(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "saida-combinada-grande.pdf"
    _pdf_image(caminho)
    fake = _TesseractFake(
        mantem_vivo=True,
        escrever_durante_execucao=True,
    )
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(
        caminho,
        ocr=True,
        tempo_total_ocr=1.0,
        tempo_pagina_ocr=1.0,
    )

    processo_pagina = fake.processos[1]
    assert resultado.abriu is True
    assert resultado.paginas_ocr == ()
    assert "limite" in (resultado.erro or "")
    assert processo_pagina.kill_count == 1
    assert processo_pagina.wait_count == 1
    assert fake.processos_mortos == 1
    assert not fake.diretorios_temporarios[0].exists()


def test_limite_fisico_combinado_de_tsv_e_stderr_e_rejeitado(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "saida-combinada.pdf"
    _pdf_image(caminho)
    fake = _TesseractFake(erro_grande=True)
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    assert resultado.abriu is True
    assert resultado.paginas_ocr == ()
    assert "limite" in (resultado.erro or "")
    assert all(not diretorio.exists() for diretorio in fake.diretorios_temporarios)


def test_deadline_e_verificado_durante_leitura_em_chunks(tmp_path: Path, monkeypatch) -> None:
    caminho = tmp_path / "leitura-grande.tsv"
    caminho.write_bytes(b"x" * (64 * 1024 + 1))
    valores = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(verify_module, "monotonic", lambda: next(valores))

    with pytest.raises(verify_module._OcrErro, match="prazo"):
        verify_module._ler_arquivo_limitado(
            caminho,
            2 * 64 * 1024,
            "TSV de teste",
            prazo=1.0,
        )


def test_deadline_e_verificado_durante_parser_em_chunks() -> None:
    valores = iter((0.0, 0.0, 2.0))
    original = verify_module.monotonic
    verify_module.monotonic = lambda: next(valores)  # type: ignore[assignment]
    try:
        with pytest.raises(verify_module._OcrErro, match="prazo"):
            verify_module._parsear_tsv(_tsv(TEXTO_OCR), 1, prazo=1.0)
    finally:
        verify_module.monotonic = original


def test_deadline_depois_do_parser_preserva_original(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "deadline-parser.pdf"
    _pdf_image(caminho)
    agora = [0.0]
    monkeypatch.setattr(verify_module, "monotonic", lambda: agora[0])
    parser_original = verify_module._parsear_tsv

    def parser_simulado(conteudo: str, numero: int, **_kwargs: object):
        agora[0] = 31.0
        return parser_original(conteudo, numero)

    monkeypatch.setattr(verify_module, "_parsear_tsv", parser_simulado)
    fake = _TesseractFake()
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(
        caminho,
        ocr=True,
        tempo_total_ocr=100.0,
        tempo_pagina_ocr=30.0,
    )

    assert resultado.abriu is True
    assert resultado.texto == ""
    assert resultado.paginas_ocr == ()
    assert "esgotado" in (resultado.erro or "")


def test_ocr_nao_piora_palavras_do_original_normalizado(
    tmp_path: Path, monkeypatch
) -> None:
    original = "a b c d e f g h i j k l m n o p q r s t"
    assert len(original) == 39
    assert len(original.split()) == 20
    caminho = tmp_path / "nao-piora.pdf"
    _pdf_texto(caminho, original)
    fake = _TesseractFake(
        saida_tsv=_tsv("texto OCR com oito palavras bem legíveis agora", 90.0)
    )
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True)

    avaliacao = resultado.paginas_avaliadas[0]
    assert avaliacao.caracteres_originais == 39
    assert avaliacao.palavras_originais == 20
    assert avaliacao.texto.strip() == original
    assert resultado.paginas_ocr == ()
    assert "palavras" in (resultado.erro or "")


def test_limite_de_paginas_ocr_e_100_e_remove_todos_temporarios(
    tmp_path: Path, monkeypatch
) -> None:
    caminho = tmp_path / "cem-paginas.pdf"
    _pdf_image(caminho, quantidade=101)
    fake = _TesseractFake()
    _instalar_fake(monkeypatch, fake)

    resultado = verificar(caminho, ocr=True, max_paginas_ocr=100)

    assert resultado.abriu is True
    assert resultado.paginas == 101
    assert resultado.paginas_ocr == tuple(range(1, 101))
    assert resultado.paginas_ocr_tentadas == tuple(range(1, 101))
    assert len(fake.diretorios_temporarios) == 100
    assert len(fake.processos) == 101  # uma consulta de idiomas + 100 páginas
    assert all(not diretorio.exists() for diretorio in fake.diretorios_temporarios)
    assert "limite de 100" in (resultado.erro or "")


def test_limites_padrao_e_limites_configuraveis() -> None:
    assert MAX_PAGINAS_OCR == 100
    assert MAX_TEMPO_OCR_DOCUMENTO == 300.0
    assert MAX_TEMPO_OCR_PAGINA == 30.0
    assert verify_module.DPI_OCR == 200
    assert MAX_MEGAPIXELS_OCR == 20.0
    assert MAX_BYTES_SAIDA_OCR == 2 * 1024 * 1024
    assert MIN_CONFIANCA_OCR == 40.0
