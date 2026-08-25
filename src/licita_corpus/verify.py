"""Verificação local dos documentos baixados.

O gate do R1 é "os 30 processos podem ser abertos localmente". Aqui isso é
testado do jeito literal: cada arquivo é aberto com a biblioteca que a R3 vai
usar (PyMuPDF para PDF, python-docx para DOCX) e o texto é extraído.

Um PDF que abre mas não devolve texto é um PDF escaneado. Ele não falha a
verificação — é marcado como ``precisa_ocr``, porque o ``scope.md`` admite scan
com OCR de boa qualidade e a decisão de OCR pertence à R3.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

#: Abaixo disto, um PDF com páginas é tratado como digitalização sem texto.
MIN_CARACTERES_POR_PAGINA = 40


@dataclass(slots=True)
class Verificacao:
    caminho: Path
    abriu: bool
    paginas: int | None = None
    caracteres: int = 0
    precisa_ocr: bool = False
    erro: str | None = None
    texto: str = field(default="", repr=False)

    @property
    def utilizavel(self) -> bool:
        """Abre e entrega texto direto — pronto para a R3 sem OCR."""
        return self.abriu and not self.precisa_ocr and self.caracteres > 0


def _verificar_pdf(caminho: Path) -> Verificacao:
    import pymupdf

    try:
        with pymupdf.open(caminho) as documento:
            paginas = documento.page_count
            partes = [pagina.get_text() for pagina in documento]
    except Exception as exc:
        return Verificacao(caminho, abriu=False, erro=f"{type(exc).__name__}: {exc}")
    texto = "\n".join(partes)
    densidade = len(texto.strip()) / max(paginas, 1)
    return Verificacao(
        caminho,
        abriu=True,
        paginas=paginas,
        caracteres=len(texto.strip()),
        precisa_ocr=densidade < MIN_CARACTERES_POR_PAGINA,
        texto=texto,
    )


def _verificar_docx(caminho: Path) -> Verificacao:
    import docx

    try:
        documento = docx.Document(str(caminho))
        partes = [p.text for p in documento.paragraphs]
        for tabela in documento.tables:
            for linha in tabela.rows:
                partes.extend(celula.text for celula in linha.cells)
    except Exception as exc:
        return Verificacao(caminho, abriu=False, erro=f"{type(exc).__name__}: {exc}")
    texto = "\n".join(partes)
    return Verificacao(caminho, abriu=True, paginas=None, caracteres=len(texto.strip()), texto=texto)


def verificar(caminho: Path) -> Verificacao:
    """Abre o documento com a biblioteca correspondente à sua extensão."""
    extensao = caminho.suffix.lower().lstrip(".")
    if extensao == "pdf":
        return _verificar_pdf(caminho)
    if extensao == "docx":
        return _verificar_docx(caminho)
    return Verificacao(
        caminho, abriu=False, erro=f"extensao fora do escopo da v1: .{extensao}"
    )


def sha256_arquivo(caminho: Path) -> str:
    digesto = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            digesto.update(bloco)
    return digesto.hexdigest()
