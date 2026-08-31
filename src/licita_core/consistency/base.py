"""Base para comparadores de consistência cruzada entre documentos (R7)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Sequence
from uuid import uuid4

from licita_core.schema import (
    Document,
    Evidence,
    Finding,
    FindingCategory,
    FindingStatus,
    Item,
    ProcurementProcess,
    Severity,
)


def norm_item_num(item_id: str) -> int | None:
    match = re.search(r"\d+", item_id)
    return int(match.group()) if match else None


def match_items_between_docs(doc_a: Document, doc_b: Document) -> list[tuple[Item, Item]]:
    """Emparelha itens correspondentes entre dois documentos por ID normalizado ou ordem."""
    items_a = doc_a.items
    items_b = doc_b.items

    map_a: dict[int, Item] = {}
    for it in items_a:
        n = norm_item_num(it.id)
        if n is not None and n not in map_a:
            map_a[n] = it

    map_b: dict[int, Item] = {}
    for it in items_b:
        n = norm_item_num(it.id)
        if n is not None and n not in map_b:
            map_b[n] = it

    matched: list[tuple[Item, Item]] = []
    matched_a: set[str] = set()
    matched_b: set[str] = set()

    for n in sorted(set(map_a.keys()).intersection(set(map_b.keys()))):
        it_a = map_a[n]
        it_b = map_b[n]
        matched.append((it_a, it_b))
        matched_a.add(it_a.id)
        matched_b.add(it_b.id)

    # Fallback 1: se ambos possuem apenas 1 item
    if len(items_a) == 1 and len(items_b) == 1:
        if items_a[0].id not in matched_a and items_b[0].id not in matched_b:
            matched.append((items_a[0], items_b[0]))
            matched_a.add(items_a[0].id)
            matched_b.add(items_b[0].id)

    # Fallback 2: emparelhamento posicional para itens restantes com mesma quantidade de itens
    unmatched_a = [it for it in items_a if it.id not in matched_a]
    unmatched_b = [it for it in items_b if it.id not in matched_b]
    if len(unmatched_a) == len(unmatched_b) and len(unmatched_a) > 0:
        for it_a, it_b in zip(unmatched_a, unmatched_b):
            matched.append((it_a, it_b))

    return matched


def build_bilateral_finding(
    *,
    rule_id: str,
    title: str,
    description: str,
    severity: Severity,
    evidence_a: Evidence | Sequence[Evidence],
    evidence_b: Evidence | Sequence[Evidence],
    process_id: str | None = None,
    legal_basis: str | None = None,
) -> Finding:
    """Cria um Finding garantindo evidência bilateral obrigatória (FR-030–036)."""
    ev_list_a = [evidence_a] if isinstance(evidence_a, Evidence) else list(evidence_a)
    ev_list_b = [evidence_b] if isinstance(evidence_b, Evidence) else list(evidence_b)

    if not ev_list_a or not ev_list_b:
        raise ValueError(
            f"Regra {rule_id}: Finding de consistência exige evidência bilateral (doc_a e doc_b)"
        )

    all_evidence = ev_list_a + ev_list_b

    # Valida que há ao menos dois documentos distintos nas evidências
    doc_ids = {ev.document_id for ev in all_evidence}
    if len(doc_ids) < 2:
        raise ValueError(
            f"Regra {rule_id}: Evidência bilateral exige âncoras em documentos distintos (encontrado: {doc_ids})"
        )

    finding_id = f"finding-const-{rule_id.lower()}-{uuid4().hex[:8]}"
    attrs = {}
    if legal_basis:
        attrs["legal_basis"] = legal_basis
    else:
        attrs["legal_basis"] = "Lei nº 14.133/2021, art. 18 e art. 40 (compatibilidade entre ETP e TR)"

    return Finding(
        id=finding_id,
        rule_id=rule_id,
        category=FindingCategory.CONSISTENCY,
        severity=severity,
        status=FindingStatus.OPEN,
        title=title,
        message=description,
        attrs=attrs,
        evidence=all_evidence,
    )


class ConsistencyComparator(ABC):
    """Classe base abstrata para comparadores de consistência."""

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Identificador da regra de consistência (ex: CONST-001)."""
        pass

    @abstractmethod
    def compare(
        self,
        doc_a: Document,
        doc_b: Document,
        process: ProcurementProcess,
    ) -> list[Finding]:
        """Executa a comparação cruzada entre dois documentos da mesma contratação."""
        pass
