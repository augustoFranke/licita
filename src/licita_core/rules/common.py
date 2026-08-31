"""Utilitários comuns para regras determinísticas do TR Linter."""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from licita_core.schema import Document, Evidence


def normalize_text(text: str) -> str:
    """Normaliza texto: casefold, remove acentos e colapsa whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_accents)
    return collapsed.lower().strip()


def is_placeholder(text: str) -> bool:
    """Verifica se o texto é apenas um placeholder ou vazio."""
    if not text:
        return True
    cleaned = text.strip()
    if not cleaned:
        return True

    # Se restar nada após remover pontuação de preenchimento, é placeholder
    stripped = re.sub(r"[\s\.\-_–—\[\]\(\)\<\>Xx#\*]+", "", cleaned)
    if not stripped:
        return True

    norm = normalize_text(cleaned)
    placeholder_phrases = {
        "a definir",
        "preencher",
        "a preencher",
        "responsavel",
        "responsavel a indicar",
        "servidor a indicar",
        "comissao a indicar",
        "servidor/comissao a indicar",
        "definir",
        "xx",
        "xxxx",
        "xx dias",
        "xxxx dias",
    }
    if norm in placeholder_phrases:
        return True
    if re.fullmatch(r"<\s*respons[aá]vel\s*>", cleaned, re.IGNORECASE):
        return True
    if re.fullmatch(r"\[\s*servidor/comiss[aã]o\s+a\s+indicar\s*\]", cleaned, re.IGNORECASE):
        return True
    if re.fullmatch(r"\[\s*preencher\s*\]", cleaned, re.IGNORECASE):
        return True
    return False


_ROMAN_MAP = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
}

_INT_TO_ROMAN = {v: k.upper() for k, v in _ROMAN_MAP.items()}


def roman_to_int(roman: str) -> int | None:
    """Converte numeral romano para int, ou None se inválido."""
    norm = roman.strip().lower()
    return _ROMAN_MAP.get(norm)


def int_to_roman(number: int) -> str | None:
    """Converte inteiro para numeral romano."""
    return _INT_TO_ROMAN.get(number)


def normalize_anchor(anchor: str) -> str:
    """Normaliza âncora de anexo (e.g. 'III' -> '3', '3' -> '3', 'A' -> 'A')."""
    clean = anchor.strip().upper()
    val = roman_to_int(clean)
    if val is not None:
        return str(val)
    return clean


def extract_first_evidence(doc: Document) -> Evidence:
    """Retorna a primeira evidência disponível no documento."""
    for section in doc.sections:
        return section.evidence
    for item in doc.items:
        if item.evidence:
            return item.evidence[0]
    for fv in doc.field_values:
        if fv.evidence:
            return fv.evidence[0]
    return Evidence(
        document_id=doc.id,
        page=1,
        block_id="b-doc-head",
        quote=doc.title or "TERMO DE REFERÊNCIA",
    )
