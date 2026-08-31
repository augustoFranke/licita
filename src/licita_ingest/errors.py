"""Exceções específicas da ingestão documental da R3."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class IngestError(Exception):
    """Erro de leitura ou de representação documental."""


class UnsupportedFormatError(IngestError, ValueError):
    """A extensão do arquivo não pertence ao escopo do primeiro extrator."""


class OCRRequiredError(IngestError):
    """O PDF exige OCR e o fallback não produziu texto utilizável."""

    def __init__(self, path: str | Path, pages: Iterable[int]) -> None:
        self.path = Path(path)
        self.pages = tuple(pages)
        page_text = ", ".join(str(page) for page in self.pages) or "desconhecida"
        super().__init__(
            f"OCR não produziu texto utilizável para {self.path}; "
            f"páginas sem camada textual: {page_text}"
        )


# Alias: o fallback existe (mesmo motor da coleta); a falha agora é qualidade.
OCRNotImplementedError = OCRRequiredError

__all__ = [
    "IngestError",
    "OCRNotImplementedError",
    "OCRRequiredError",
    "UnsupportedFormatError",
]
