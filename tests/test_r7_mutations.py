"""Suíte de mutações do Consistency Engine (R7) sobre o golden real da R4.

O ``Plano.md`` exige a suíte **sobre o golden**: detecção ≥95% das
inconsistências injetadas, ≤5% de falsos positivos e 100% dos findings com
evidência bilateral.

Regra desta suíte: uma mutação só é injetável quando o golden anota o **mesmo
fato nos dois documentos do par** (ETP e TR). Sem anotação bilateral não há
divergência a injetar nem evidência bilateral a exigir — o processo é
registrado como não injetável, nunca ignorado em silêncio.

Substituir o dado anotado por um par sintético antes de mutar mede o
comparador contra uma fixture, não contra o corpus, e por isso não fecha esta
fase. Os comparadores isolados continuam cobertos por ``test_r7_consistency``.

Os pares TR↔EDITAL, TR↔CONTRATO e DFD↔ETP (FR-030–036) ficam **em aberto**: o
lote R1 é, por decisão de escopo, só ETP+TR. O motor os implementa, esta suíte
relata que não foram exercitados, e a prova depende de uma expansão futura do
corpus. Ausência de documento não é inconsistência.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from licita_core.consistency import ConsistencyEngine
from licita_core.schema import (
    Document,
    DocumentType,
    FieldType,
    ProcurementProcess,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
GOLDEN_DIRS = [ROOT_DIR / "r4" / "data" / "dev", ROOT_DIR / "r4" / "data" / "eval"]

# Detecção mínima exigida pela saída da R7.
MIN_DETECTION_RATE = 95.0
# Falso positivo máximo tolerado no baseline não mutado.
MAX_FALSE_POSITIVE_RATE = 5.0
# Piso de mutações para a suíte ter poder estatístico.
MIN_INJECTED_MUTATIONS = 30

# Pares que a saída da R7 lista e que o lote atual não contém.
SECONDARY_PAIRS = (
    (DocumentType.TR, DocumentType.EDITAL),
    (DocumentType.TR, DocumentType.CONTRATO),
    (DocumentType.DFD, DocumentType.ETP),
)


@dataclass(frozen=True)
class BilateralFact:
    """Fato anotado nos dois documentos do par, portanto mutável."""

    item_number: int | None
    field_type: FieldType


def _item_number(item_id: str) -> int | None:
    match = re.search(r"\d+", item_id or "")
    return int(match.group()) if match else None


def _load_golden_pairs() -> list[tuple[str, ProcurementProcess]]:
    """Carrega os processos do golden que possuem ETP e TR."""
    pairs: list[tuple[str, ProcurementProcess]] = []
    for golden_dir in GOLDEN_DIRS:
        if not golden_dir.exists():
            continue
        for path in sorted(golden_dir.glob("*.json")):
            process = ProcurementProcess.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            types = {d.type for d in process.documents}
            if DocumentType.ETP in types and DocumentType.TR in types:
                pairs.append((f"{golden_dir.name}/{path.name}", process))
    return pairs


def _document(process: ProcurementProcess, doc_type: DocumentType) -> Document:
    return next(d for d in process.documents if d.type == doc_type)


def _bilateral_facts(etp: Document, tr: Document) -> list[BilateralFact]:
    """Fatos anotados nos dois documentos — o único material mutável honesto."""
    facts: list[BilateralFact] = []

    etp_doc_fields = {fv.field_type for fv in etp.field_values}
    tr_doc_fields = {fv.field_type for fv in tr.field_values}
    for field_type in sorted(etp_doc_fields & tr_doc_fields, key=lambda f: f.value):
        facts.append(BilateralFact(item_number=None, field_type=field_type))

    etp_items = {_item_number(i.id): i for i in etp.items}
    tr_items = {_item_number(i.id): i for i in tr.items}
    shared_items = {n for n in etp_items.keys() & tr_items.keys() if n is not None}
    for number in sorted(shared_items):
        etp_fields = {fv.field_type for fv in etp_items[number].field_values}
        tr_fields = {fv.field_type for fv in tr_items[number].field_values}
        for field_type in sorted(etp_fields & tr_fields, key=lambda f: f.value):
            facts.append(BilateralFact(item_number=number, field_type=field_type))

    return facts


def _divergent_value(value: object) -> object:
    """Produz um valor comprovadamente diferente, preservando o tipo."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float, Decimal)):
        return type(value)(value) * 3 + 7 if not isinstance(value, Decimal) else value * 3 + 7
    if isinstance(value, str):
        try:
            return str(Decimal(value.replace(",", ".")) * 3 + 7)
        except (InvalidOperation, ValueError):
            return f"{value}-DIVERGENTE"
    return "DIVERGENTE"


def _inject(process: ProcurementProcess, fact: BilateralFact) -> ProcurementProcess:
    """Aplica a divergência no lado TR do fato anotado, sem tocar no resto."""
    mutated = copy.deepcopy(process)
    tr = _document(mutated, DocumentType.TR)

    if fact.item_number is None:
        target = next(fv for fv in tr.field_values if fv.field_type == fact.field_type)
    else:
        item = next(i for i in tr.items if _item_number(i.id) == fact.item_number)
        target = next(fv for fv in item.field_values if fv.field_type == fact.field_type)

    target.value = _divergent_value(target.value)
    return mutated


def test_r7_mutation_suite_detection_and_bilateral_evidence() -> None:
    pairs = _load_golden_pairs()
    assert pairs, "Nenhum processo do golden possui ETP e TR"

    engine = ConsistencyEngine()

    injectable: list[tuple[str, ProcurementProcess, list[BilateralFact]]] = []
    not_injectable: list[str] = []
    for name, process in pairs:
        facts = _bilateral_facts(
            _document(process, DocumentType.ETP), _document(process, DocumentType.TR)
        )
        if facts:
            injectable.append((name, process, facts))
        else:
            not_injectable.append(name)

    total_facts = sum(len(facts) for _, _, facts in injectable)

    # 1. Baseline: findings no golden não mutado são falsos positivos.
    baseline_findings = 0
    for _, process, _ in injectable:
        baseline_findings += len(engine.run(process))

    # 2. Injeção: uma divergência por fato bilateral anotado.
    injected = 0
    detected = 0
    bilateral = 0
    undetected: list[str] = []
    for name, process, facts in injectable:
        for fact in facts:
            mutated = _inject(process, fact)
            injected += 1
            findings = engine.run(mutated)
            if findings:
                detected += 1
                if any(len({ev.document_id for ev in f.evidence}) >= 2 for f in findings):
                    bilateral += 1
            else:
                undetected.append(f"{name} {fact.field_type.value} item={fact.item_number}")

    detection_rate = (detected / injected * 100) if injected else 0.0
    false_positive_rate = (baseline_findings / total_facts * 100) if total_facts else 0.0
    bilateral_rate = (bilateral / detected * 100) if detected else 0.0

    available_types = {d.type for _, process in pairs for d in process.documents}
    unexercised = [
        f"{a.value}↔{b.value}"
        for a, b in SECONDARY_PAIRS
        if not {a, b} <= available_types
    ]

    print(
        f"\n[R7 CONSISTENCY MUTATION BENCHMARK]\n"
        f"  Processos com par ETP+TR:       {len(pairs)}\n"
        f"  Processos sem anotação bilateral: {len(not_injectable)} "
        f"({', '.join(not_injectable) if not_injectable else '-'})\n"
        f"  Fatos bilaterais mutáveis:      {total_facts}\n"
        f"  Mutações injetadas:             {injected}\n"
        f"  Detectadas:                     {detected} ({detection_rate:.2f}% "
        f"- Meta >= {MIN_DETECTION_RATE}%)\n"
        f"  Evidência bilateral:            {bilateral_rate:.2f}% (Meta == 100%)\n"
        f"  Falsos positivos no baseline:   {baseline_findings} "
        f"({false_positive_rate:.2f}% - Meta <= {MAX_FALSE_POSITIVE_RATE}%)\n"
        f"  Pares não exercitados (em aberto): "
        f"{', '.join(unexercised) if unexercised else '-'} "
        f"— o lote R1 só tem ETP e TR"
    )

    assert injected >= MIN_INJECTED_MUTATIONS, (
        f"Suíte sem material real: {injected} mutações injetáveis "
        f"(mínimo {MIN_INJECTED_MUTATIONS}). "
        f"{len(not_injectable)} de {len(pairs)} processos do golden não anotam "
        f"nenhum fato nos dois documentos do par, então não há divergência a "
        f"injetar nem evidência bilateral a exigir. A R7 não pode ser medida "
        f"antes de a R4 anotar ETP e TR do mesmo fato."
    )
    assert detection_rate >= MIN_DETECTION_RATE, (
        f"Taxa de detecção abaixo de {MIN_DETECTION_RATE}%: {detection_rate:.2f}%. "
        f"Não detectadas: {undetected[:10]}"
    )
    assert bilateral_rate == 100.0, (
        f"Taxa de evidência bilateral abaixo de 100%: {bilateral_rate:.2f}%"
    )
    assert false_positive_rate <= MAX_FALSE_POSITIVE_RATE, (
        f"Falsos positivos acima de {MAX_FALSE_POSITIVE_RATE}%: "
        f"{false_positive_rate:.2f}% ({baseline_findings} findings no golden não mutado)"
    )
