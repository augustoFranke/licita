"""Motor de Decomposição Atômica de Especificações Técnicas (Fase R9).

Converte descrições técnicas textuais em tuplas estruturadas de Requirement:
- Combustível, Lugares, Câmbio, Motor/Potência, Tração, Cor, Ano/Modelo, Voltagem, etc.
- Garante 100% de conformidade com o schema Pydantic e vinculação de evidências.
"""

from __future__ import annotations

import re
from typing import Sequence

from licita_core.schema import (
    Evidence,
    Item,
    Requirement,
    RequirementOperator,
    ReviewStatus,
)

# Catálogo de padrões de extração semântica com grupos de captura
_PATTERNS: list[tuple[str, RequirementOperator, str, str | None]] = [
    # (Regex pattern, RequirementOperator, attribute_name, default_unit)
    (r"(?:motor|pot[êe]ncia)\s*(?:de)?\s*(\d+(?:[.,]\d+)?)\s*(?:cv|hp|cilindros|cc)?", RequirementOperator.GREATER_THAN_OR_EQUAL, "potencia_motor", None),
    (r"(\d+(?:[.,]\d+)?)\s*(?:cv|hp)\b", RequirementOperator.GREATER_THAN_OR_EQUAL, "potencia_cv", "CV"),
    (r"(?:tipo\s*de\s*)?combust[íi]vel\s*:\s*([a-zA-Z\+]+)", RequirementOperator.EQUAL, "combustivel", None),
    (r"\b(flex|gasolina|diesel|etanol|el[ée]trico|h[íi]brido)\b", RequirementOperator.EQUAL, "combustivel", None),
    (r"(?:com\s*)?(\d{1,2})\s*(?:\([a-zA-Z]+\)\s*)?lugares\b", RequirementOperator.GREATER_THAN_OR_EQUAL, "lugares", "LUGARES"),
    (r"c[âa]mbio\s*:\s*([a-zA-Z]+)", RequirementOperator.EQUAL, "cambio", None),
    (r"\bc[âa]mbio\s*(manual|autom[áa]tico|automatizado|cvt)\b", RequirementOperator.EQUAL, "cambio", None),
    (r"\btra[çc][ãa]o\s*(4x4|4x2|integral|dianteira|traseira)\b", RequirementOperator.EQUAL, "tracao", None),
    (r"(?:ano(?:/modelo)?|modelo)\s*:\s*(\d{4}(?:/\d{4})?)", RequirementOperator.EQUAL, "ano_modelo", None),
    (r"\bano\s*(\d{4})\b", RequirementOperator.GREATER_THAN_OR_EQUAL, "ano_fabricacao", None),
    (r"\bcor\s*:\s*([a-zA-Z]+)", RequirementOperator.EQUAL, "cor", None),
    (r"\bcor\s*(branca|preta|prata|cinza|vermelha|azul)\b", RequirementOperator.EQUAL, "cor", None),
    (r"\b(\d{3})\s*v(?:olts)?\b", RequirementOperator.EQUAL, "tensao_voltagem", "V"),
    (r"\b(110|127|220)\s*v\b", RequirementOperator.EQUAL, "tensao_voltagem", "V"),
    (r"\b(bivolt)\b", RequirementOperator.EQUAL, "tensao_voltagem", None),
    (r"capacidade\s*(?:de)?\s*(\d+(?:[.,]\d+)?)\s*(m[³3]|litros?|kg|l|ml)\b", RequirementOperator.GREATER_THAN_OR_EQUAL, "capacidade", None),
    (r"(\d+)\s*(?:folhas|fls)\b", RequirementOperator.EQUAL, "quantidade_folhas", "FOLHAS"),
    (r"largura\s*(?:m[íi]nima\s*de\s*)?(\d+(?:[.,]\d+)?)\s*(m|cm|mm)\b", RequirementOperator.GREATER_THAN_OR_EQUAL, "largura", None),
    (r"(\d+)\s*rotores\b", RequirementOperator.EQUAL, "quantidade_rotores", "ROTORES"),
    (r"(\d+)\s*facas\b", RequirementOperator.EQUAL, "quantidade_facas", "FACAS"),
    (r"\b(airbags?|ar\s*condicionado|dire[çc][ãa]o\s*hidr[áa]ulica|dire[çc][ãa]o\s*el[ée]trica|trava\s*el[ée]trica|vidros?\s*el[ée]tricos?)\b", RequirementOperator.EXISTS, "item_opcional", None),
]


class AtomicRequirementEngine:
    """Extrai requisitos atômicos estruturados a partir da especificação em linguagem natural."""

    def extract_from_item(self, item: Item, document_id: str | None = None) -> list[Requirement]:
        requirements: list[Requirement] = []
        text = item.description or ""
        if not text:
            return requirements

        ev_base = item.evidence[0] if item.evidence else None
        seen_attrs: set[str] = {r.attribute.lower() for r in item.requirements}

        for pattern, op, attr_name, default_unit in _PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # Pega o primeiro grupo relevante ou todo o match se op for EXISTS
                if op == RequirementOperator.EXISTS:
                    raw_val = match.group(0).strip().lower()
                    attr_key = f"opcional_{re.sub(r'[^\w]', '_', raw_val)}"
                    val: bool | int | float | str = True
                    unit = None
                else:
                    groups = match.groups()
                    raw_val = groups[0].strip() if groups else match.group(0).strip()
                    val = raw_val

                    # Converte números inteiros ou float se aplicável
                    if re.match(r"^\d+$", val):
                        val = int(val)
                    elif re.match(r"^\d+[.,]\d+$", val):
                        try:
                            val = float(val.replace(",", "."))
                        except ValueError:
                            pass

                    unit = groups[1].upper() if len(groups) > 1 and groups[1] else default_unit
                    attr_key = attr_name

                if attr_key in seen_attrs:
                    continue
                seen_attrs.add(attr_key)

                # Cria evidência com o trecho exato do match
                matched_quote = match.group(0)
                if ev_base:
                    ev = Evidence(
                        document_id=ev_base.document_id,
                        page=ev_base.page,
                        block_id=ev_base.block_id,
                        quote=matched_quote,
                    )
                elif document_id:
                    ev = Evidence(
                        document_id=document_id,
                        page=1,
                        block_id=f"{document_id}:p-0001:b-0001",
                        quote=matched_quote,
                    )
                else:
                    ev = Evidence(
                        document_id="doc:tr",
                        page=1,
                        block_id="doc:tr:p-0001:b-0001",
                        quote=matched_quote,
                    )

                req = Requirement(
                    attribute=attr_key,
                    operator=op,
                    value=val,
                    unit=unit,
                    item_id=item.id,
                    evidence=[ev],
                    review_status=ReviewStatus.EXTRACTED,
                )
                requirements.append(req)

        return requirements
