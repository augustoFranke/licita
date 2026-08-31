"""Primeiro extrator documental da R3.

A camada lê PDF (PyMuPDF) e DOCX (python-docx). OCR é fallback da ingestão
(mesmo motor de ``licita_corpus.verify``). Se o OCR não produzir texto
utilizável, a extração falha de forma explícita.
"""

from .errors import (
    IngestError,
    OCRNotImplementedError,
    OCRRequiredError,
    UnsupportedFormatError,
)
from .extractor import (
    DocumentExtractor,
    extract,
    extract_docx,
    extract_document,
    extract_pdf,
    extrair_documento,
    sha256_file,
)
from .models import (
    BlockKind,
    BlockType,
    DocumentBlock,
    DocumentFormat,
    PageKind,
    StructuredBlock,
    StructuredDocument,
    StructuredPage,
)

OCR_FALLBACK_IMPLEMENTED = True

__all__ = [
    "BlockKind",
    "BlockType",
    "DocumentBlock",
    "DocumentExtractor",
    "DocumentFormat",
    "IngestError",
    "OCRNotImplementedError",
    "OCRRequiredError",
    "OCR_FALLBACK_IMPLEMENTED",
    "PageKind",
    "StructuredBlock",
    "StructuredDocument",
    "StructuredPage",
    "UnsupportedFormatError",
    "extract",
    "extract_docx",
    "extract_document",
    "extract_pdf",
    "extrair_documento",
    "sha256_file",
]
