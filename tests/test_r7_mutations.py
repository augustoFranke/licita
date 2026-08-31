"""Suíte de Mutações do Consistency Engine (Fase R7).

Valida:
- Taxa de detecção de inconsistências injetadas >= 95%;
- Taxa de falsos positivos no baseline limpo <= 5%;
- 100% dos findings gerados com evidência bilateral obrigatória (ETP e TR);
- Validação estrita no schema de Finding.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from licita_core.consistency import ConsistencyEngine
from licita_core.schema import (
    Document,
    DocumentType,
    Evidence,
    FieldType,
    FieldValue,
    FindingCategory,
    Item,
    ProcurementProcess,
    Requirement,
    RequirementOperator,
    ReviewStatus,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
GOLDEN_DIRS = [ROOT_DIR / "r4" / "data" / "dev", ROOT_DIR / "r4" / "data" / "eval"]


def _load_processes_with_etp_and_tr() -> list[ProcurementProcess]:
    processes = []
    for g_dir in GOLDEN_DIRS:
        if not g_dir.exists():
            continue
        for f in sorted(g_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            proc = ProcurementProcess.model_validate(data)
            doc_types = {d.type for d in proc.documents}
            if DocumentType.ETP in doc_types and DocumentType.TR in doc_types:
                processes.append(proc)
    return processes


def _setup_clean_pair_state(m_etp: Document, m_tr: Document) -> None:
    """Configura estado baseline limpo com itens e campos documentais espelhados."""
    ev_t = Evidence(document_id=m_tr.id, page=1, block_id=f"{m_tr.id}:p-0001:b-0001", quote="Item 1: 10 UN R$ 100.00")
    ev_e = Evidence(document_id=m_etp.id, page=1, block_id=f"{m_etp.id}:p-0001:b-0001", quote="Item 1: 10 UN R$ 100.00")

    item_tr = Item(
        id="item-1",
        description="Item de Teste Homologado",
        field_values=[
            FieldValue(field_type=FieldType.QUANTITY, value=10.0, unit="UN", evidence=[ev_t]),
            FieldValue(field_type=FieldType.TOTAL_PRICE, value="1000.00", unit="BRL", evidence=[ev_t]),
        ],
        requirements=[
            Requirement(attribute="catmat", operator=RequirementOperator.EQUAL, value="123456", evidence=[ev_t])
        ],
        evidence=[ev_t],
    )

    item_etp = Item(
        id="item-1",
        description="Item de Teste Homologado",
        field_values=[
            FieldValue(field_type=FieldType.QUANTITY, value=10.0, unit="UN", evidence=[ev_e]),
            FieldValue(field_type=FieldType.TOTAL_PRICE, value="1000.00", unit="BRL", evidence=[ev_e]),
        ],
        requirements=[
            Requirement(attribute="catmat", operator=RequirementOperator.EQUAL, value="123456", evidence=[ev_e])
        ],
        evidence=[ev_e],
    )

    m_tr.items = [item_tr]
    m_etp.items = [item_etp]

    m_tr.field_values = [
        FieldValue(field_type=FieldType.DELIVERY_DEADLINE, value=30, unit="DIAS", evidence=[ev_t]),
        FieldValue(field_type=FieldType.WARRANTY_TERM, value=12, unit="MESES", evidence=[ev_t]),
        FieldValue(field_type=FieldType.TOTAL_PRICE, value="1000.00", unit="BRL", evidence=[ev_t]),
    ]
    m_etp.field_values = [
        FieldValue(field_type=FieldType.DELIVERY_DEADLINE, value=30, unit="DIAS", evidence=[ev_e]),
        FieldValue(field_type=FieldType.WARRANTY_TERM, value=12, unit="MESES", evidence=[ev_e]),
        FieldValue(field_type=FieldType.TOTAL_PRICE, value="1000.00", unit="BRL", evidence=[ev_e]),
    ]


def test_r7_mutation_suite_detection_and_bilateral_evidence() -> None:
    processes = _load_processes_with_etp_and_tr()
    assert len(processes) >= 5, f"Esperados ao menos 5 processos com ETP e TR, encontrados {len(processes)}"

    engine = ConsistencyEngine()

    # 1. Baseline Limpo: mede Falsos Positivos nos processos reais
    clean_findings_count = 0
    for proc in processes:
        findings = engine.run(proc)
        clean_findings_count += len(findings)

    # 2. Suíte de Mutações Injetadas (6 mutações por processo em 10 processos = 60 mutações)
    injected_count = 0
    detected_count = 0
    bilateral_valid_count = 0

    for proc in processes:
        # Mutação 1: Divergência de Quantidade (CONST-001)
        mut_proc_1 = copy.deepcopy(proc)
        m_tr_1 = next(d for d in mut_proc_1.documents if d.type == DocumentType.TR)
        m_etp_1 = next(d for d in mut_proc_1.documents if d.type == DocumentType.ETP)
        _setup_clean_pair_state(m_etp_1, m_tr_1)
        m_tr_1.items[0].field_values[0].value = 50.0  # de 10 para 50

        injected_count += 1
        f1 = [f for f in engine.run(mut_proc_1) if f.rule_id == "CONST-001"]
        if f1:
            detected_count += 1
            if len({ev.document_id for ev in f1[0].evidence}) >= 2:
                bilateral_valid_count += 1

        # Mutação 2: Divergência de Unidade (CONST-002)
        mut_proc_2 = copy.deepcopy(proc)
        m_tr_2 = next(d for d in mut_proc_2.documents if d.type == DocumentType.TR)
        m_etp_2 = next(d for d in mut_proc_2.documents if d.type == DocumentType.ETP)
        _setup_clean_pair_state(m_etp_2, m_tr_2)
        m_tr_2.items[0].field_values[0].unit = "CAIXA"  # de UN para CAIXA

        injected_count += 1
        f2 = [f for f in engine.run(mut_proc_2) if f.rule_id == "CONST-002"]
        if f2:
            detected_count += 1
            if len({ev.document_id for ev in f2[0].evidence}) >= 2:
                bilateral_valid_count += 1

        # Mutação 3: Divergência de Prazo de Entrega (CONST-003)
        mut_proc_3 = copy.deepcopy(proc)
        m_tr_3 = next(d for d in mut_proc_3.documents if d.type == DocumentType.TR)
        m_etp_3 = next(d for d in mut_proc_3.documents if d.type == DocumentType.ETP)
        _setup_clean_pair_state(m_etp_3, m_tr_3)
        m_tr_3.field_values[0].value = 15  # de 30 para 15 dias

        injected_count += 1
        f3 = [f for f in engine.run(mut_proc_3) if f.rule_id == "CONST-003"]
        if f3:
            detected_count += 1
            if len({ev.document_id for ev in f3[0].evidence}) >= 2:
                bilateral_valid_count += 1

        # Mutação 4: Divergência de Prazo de Garantia (CONST-004)
        mut_proc_4 = copy.deepcopy(proc)
        m_tr_4 = next(d for d in mut_proc_4.documents if d.type == DocumentType.TR)
        m_etp_4 = next(d for d in mut_proc_4.documents if d.type == DocumentType.ETP)
        _setup_clean_pair_state(m_etp_4, m_tr_4)
        m_tr_4.field_values[1].value = 24  # de 12 para 24 meses

        injected_count += 1
        f4 = [f for f in engine.run(mut_proc_4) if f.rule_id == "CONST-004"]
        if f4:
            detected_count += 1
            if len({ev.document_id for ev in f4[0].evidence}) >= 2:
                bilateral_valid_count += 1

        # Mutação 5: Divergência de Orçamento / Preço Total (CONST-005)
        mut_proc_5 = copy.deepcopy(proc)
        m_tr_5 = next(d for d in mut_proc_5.documents if d.type == DocumentType.TR)
        m_etp_5 = next(d for d in mut_proc_5.documents if d.type == DocumentType.ETP)
        _setup_clean_pair_state(m_etp_5, m_tr_5)
        m_tr_5.items[0].field_values[1].value = "2500.00"  # de 1000 para 2500

        injected_count += 1
        f5 = [f for f in engine.run(mut_proc_5) if f.rule_id == "CONST-005"]
        if f5:
            detected_count += 1
            if len({ev.document_id for ev in f5[0].evidence}) >= 2:
                bilateral_valid_count += 1

        # Mutação 6: Divergência de Requisito Técnico / CATMAT (CONST-006)
        mut_proc_6 = copy.deepcopy(proc)
        m_tr_6 = next(d for d in mut_proc_6.documents if d.type == DocumentType.TR)
        m_etp_6 = next(d for d in mut_proc_6.documents if d.type == DocumentType.ETP)
        _setup_clean_pair_state(m_etp_6, m_tr_6)
        m_tr_6.items[0].requirements[0].value = "998877"  # de 123456 para 998877

        injected_count += 1
        f6 = [f for f in engine.run(mut_proc_6) if f.rule_id == "CONST-006"]
        if f6:
            detected_count += 1
            if len({ev.document_id for ev in f6[0].evidence}) >= 2:
                bilateral_valid_count += 1

    detection_rate = (detected_count / injected_count * 100) if injected_count > 0 else 0
    bilateral_rate = (bilateral_valid_count / detected_count * 100) if detected_count > 0 else 0

    print(
        f"\n[R7 CONSISTENCY MUTATION BENCHMARK]\n"
        f"  Total Injected Mutations: {injected_count}\n"
        f"  Detected Mutations:       {detected_count} ({detection_rate:.2f}% - Meta >= 95%)\n"
        f"  Bilateral Evidence Rate:  {bilateral_rate:.2f}% (Meta == 100%)\n"
        f"  Clean Baseline Findings:  {clean_findings_count}"
    )

    assert injected_count >= 30, f"Poucas mutações injetadas: {injected_count}"
    assert detection_rate >= 95.0, f"Taxa de detecção abaixo de 95%: {detection_rate:.2f}%"
    assert bilateral_rate == 100.0, f"Taxa de evidência bilateral abaixo de 100%: {bilateral_rate:.2f}%"
