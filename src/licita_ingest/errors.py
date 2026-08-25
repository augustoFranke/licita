"""Exceções específicas da ingestão documental da R3."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class IngestError(Exception):
    """Erro de leitura ou de representação documental."""


class UnsupportedFormatError(IngestError, ValueError):
    """A extensão do arquivo não pertence ao escopo do primeiro extrator."""


class OCRNotImplementedError(IngestError, NotImplementedError):
    """O documento exige OCR, que é apenas fallback futuro na R3."""

    def __init__(self, path: str | Path, pages: Iterable[int]) -> None:
        self.path = Path(path)
        self.pages = tuple(pages)
        page_text = ", ".join(str(page) for page in self.pages) or "desconhecida"
        super().__init__(
            f"OCR não implementado para {self.path}; "
            f"não foi possível extrair texto nas páginas: {page_text}"
        )


__all__ = ["IngestError", "OCRNotImplementedError", "UnsupportedFormatError"]
