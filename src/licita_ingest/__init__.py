"""Primeiro extrator documental da R3.

A camada é limitada a PDF textual (PyMuPDF) e DOCX (python-docx). OCR é
somente um fallback planejado: PDFs que dependem dele produzem
``OCRNotImplementedError`` em vez de perder texto silenciosamente.
"""

from .errors import IngestError, OCRNotImplementedError, UnsupportedFormatError
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

OCR_FALLBACK_IMPLEMENTED = False

__all__ = [
    "BlockKind",
    "BlockType",
    "DocumentBlock",
    "DocumentExtractor",
    "DocumentFormat",
    "IngestError",
    "OCRNotImplementedError",
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
