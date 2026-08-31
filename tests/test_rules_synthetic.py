"""Validação formal completa dos 44 casos de teste sintéticos (D/N) de rules_synthetic_tests.md.

Cobre 100% dos cenários de teste para os 6 controles NORMATIVE e 2 controles ADVISORY.
"""

from __future__ import annotations

import pytest

from licita_core.rules.annex_integrity import AnnexIntegrityRule
from licita_core.rules.attribute_contradiction import AttributeContradictionRule
from licita_core.rules.base import RuleContext
from licita_core.rules.catalog import get_catalog
from licita_core.rules.delivery_deadline import DeliveryDeadlineRule
from licita_core.rules.mandatory_elements import MandatoryElementsRule
from licita_core.rules.quantity_missing import QuantityMissingRule
from licita_core.rules.receipt_rules import ReceiptRulesRule
from licita_core.rules.verifiable_requirement import VerifiableRequirementRule
from licita_core.rules.warranty_contradiction import WarrantyContradictionRule
from licita_core.schema import Severity
from synthetic_builder import build_tr_process

# ---------------------------------------------------------------- Fixture TR-MINIMO

TR_MINIMO_MD = """
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
1.1. Aquisição de cadeiras giratórias ergonômicas para escritório, por pregão eletrônico, com fornecimento único e prazo contratual de 60 dias.
Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios e apoio de braços.
Unidade de fornecimento: unidade.
Quantidade estimada: 50.

## 2. FUNDAMENTAÇÃO DA CONTRATAÇÃO
2.1. A contratação atende à necessidade descrita no ETP municipal nº 12/2024.

## 3. DESCRIÇÃO DA SOLUÇÃO COMO UM TODO
3.1. Fornecimento, entrega, montagem e garantia on-site do Item 1, considerados transporte, uso e descarte ao fim da vida útil.

## 4. REQUISITOS DA CONTRATAÇÃO
4.1. Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios, apoio de braços e capacidade mínima de 110 kg.
4.2. Garantia técnica on-site prestada pela contratada por 12 (doze) meses contados do recebimento definitivo.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Prazo de entrega: 15 (quinze) dias corridos, contados do recebimento da Nota de Empenho.
5.2. Local: Almoxarifado Municipal, na sede do Município/UF.

## 6. MODELO DE GESTÃO DO CONTRATO
6.1. Fiscalização por servidor municipal designado.

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
7.1. Recebimento:
a) provisório, de forma sumária, no ato da entrega, pelo fiscal, para posterior verificação de conformidade;
b) definitivo, em até 10 (dez) dias úteis após o provisório, por servidor designado, mediante termo detalhado.
7.2. Pagamento em até 10 dias úteis após a liquidação.

## 8. FORMA E CRITÉRIOS DE SELEÇÃO DO FORNECEDOR
8.1. Pregão eletrônico, menor preço por item.

## 9. ESTIMATIVAS DO VALOR DA CONTRATAÇÃO
9.1. Valor total estimado: R$ 35.000,00, conforme memória de cálculo juntada ao processo.

## 10. ADEQUAÇÃO ORÇAMENTÁRIA
10.1. Programa de Trabalho 10.122.0001, Fonte 100, Elemento 339030.
"""


def _tr_minimo_process():
    return build_tr_process(
        TR_MINIMO_MD,
        extra_items=[
            {
                "id": "item-1",
                "description": "cadeira giratória",
                "field_values": [
                    {
                        "field_type": "QUANTITY",
                        "value": 50,
                        "unit": "unidade",
                        "item_id": "item-1",
                        "evidence": [
                            {
                                "document_id": "tr-synthetic-1",
                                "page": 1,
                                "block_id": "b-002",
                                "quote": "Quantidade estimada: 50.",
                            }
                        ],
                    }
                ],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-002",
                        "quote": "cadeira giratória",
                    }
                ],
            }
        ],
    )


def test_tr_minimo_all_rules_silence() -> None:
    proc = _tr_minimo_process()
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    catalog = get_catalog()

    all_findings = []
    for rule in catalog:
        findings = rule.detect(context)
        all_findings.extend(findings)

    assert all_findings == []


# ---------------------------------------------------------------- RULE-001 Tests

def test_001_d1_detects_multiple_missing_elements() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DO OBJETO
Aquisição de 100 caixas de papel-toalha interfolhado, com 1.000 folhas por caixa e prazo contratual de 60 dias.

## 2. DA FUNDAMENTAÇÃO
Conforme ETP municipal nº 05/2024.

## 3. DO VALOR ESTIMADO
Custo total estimado: R$ 5.400,00, conforme memória de cálculo do processo.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = MandatoryElementsRule().detect(context)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "RULE-001"
    assert finding.severity == Severity.HIGH
    assert finding.attrs["missing"] == [
        "solucao",
        "requisitos",
        "execucao",
        "gestao",
        "medicao_pagamento",
        "selecao",
        "adequacao_orcamentaria",
        "local_entrega",
        "recebimento",
    ]


def test_001_d2_detects_placeholder_body() -> None:
    md = TR_MINIMO_MD.replace(
        """## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Prazo de entrega: 15 (quinze) dias corridos, contados do recebimento da Nota de Empenho.
5.2. Local: Almoxarifado Municipal, na sede do Município/UF.""",
        """## 5. MODELO DE EXECUÇÃO DO OBJETO
....""",
    )
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = MandatoryElementsRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["missing"] == ["execucao", "local_entrega"]


def test_001_n1_silence_canonical_tr() -> None:
    proc = _tr_minimo_process()
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = MandatoryElementsRule().detect(context)
    assert findings == []


def test_001_n2_silence_alias_titles() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DO OBJETO
Aquisição de 50 cadeiras giratórias, com prazo contratual de 60 dias. Unidade: unidade. Quantidade: 50.

## 2. DA JUSTIFICATIVA
Conforme ETP municipal nº 12/2024.

## 3. DA SOLUÇÃO
Fornecimento único de mobiliário, incluindo entrega e montagem.

## 4. DOS REQUISITOS
Cadeira giratória, tecido preto, cinco rodízios e apoio de braços. Garantia não exigida, consideradas a padronização e a baixa complexidade do bem.

## 5. DA EXECUÇÃO
Entrega em 15 dias corridos no Almoxarifado Municipal.

## 6. DA GESTÃO
Fiscalização por servidor municipal designado.

## 7. DO PAGAMENTO
Recebimento provisório sumário pelo fiscal no ato da entrega e definitivo por servidor designado, mediante termo detalhado, em 10 dias úteis; pagamento após ateste.

## 8. DA SELEÇÃO
Pregão eletrônico, menor preço.

## 9. DA ESTIMATIVA DE PREÇOS
R$ 35.000,00, conforme memória de cálculo juntada ao processo.

## 10. DA DOTAÇÃO
Programa de Trabalho 10.122.0001, Fonte 100.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = MandatoryElementsRule().detect(context)
    assert findings == []


def test_001_n3_detects_srp_without_budget_adequacy() -> None:
    md = TR_MINIMO_MD.replace(
        "## 1. DEFINIÇÃO DO OBJETO\n1.1. Aquisição de cadeiras",
        "## 1. DEFINIÇÃO DO OBJETO\nContratação por sistema de registro de preços. 1.1. Aquisição de cadeiras",
    )
    md = md.replace(
        """## 10. ADEQUAÇÃO ORÇAMENTÁRIA
10.1. Programa de Trabalho 10.122.0001, Fonte 100, Elemento 339030.""",
        "",
    )
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = MandatoryElementsRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["missing"] == ["adequacao_orcamentaria"]


# ---------------------------------------------------------------- RULE-002 Tests

def test_002_d1_detects_prose_without_quantity() -> None:
    md = """
## 1. OBJETO
Item 1: Papel sulfite A4, alcalino, branco, 75 g/m², embalagem com 500 folhas (resma), certificado FSC ou Cerflor.
Valor unitário de referência: R$ 26,00.
"""
    proc = build_tr_process(
        md,
        extra_items=[
            {
                "id": "item-1",
                "description": "Papel sulfite A4",
                "field_values": [],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Papel sulfite A4",
                    }
                ],
            }
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = QuantityMissingRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["falta"] == "quantidade"


def test_002_d2_detects_empty_quantity_cell() -> None:
    proc = build_tr_process(
        "## 1. OBJETO\nItem 1",
        extra_items=[
            {
                "id": "item-1",
                "description": "Notebook",
                "field_values": [],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Item 1",
                    }
                ],
            }
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = QuantityMissingRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["falta"] == "quantidade"


def test_002_d3_detects_quantity_without_unit() -> None:
    proc = build_tr_process(
        "## 1. OBJETO\nItem 1",
        extra_items=[
            {
                "id": "item-1",
                "description": "Papel sulfite A4",
                "field_values": [
                    {
                        "field_type": "QUANTITY",
                        "value": 1200,
                        "unit": None,
                        "item_id": "item-1",
                        "evidence": [
                            {
                                "document_id": "tr-synthetic-1",
                                "page": 1,
                                "block_id": "b-001",
                                "quote": "Item 1",
                            }
                        ],
                    }
                ],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Item 1",
                    }
                ],
            }
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = QuantityMissingRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["falta"] == "unidade"


def test_002_n1_silence_complete_table() -> None:
    proc = build_tr_process(
        "## 1. OBJETO\nItem 1",
        extra_items=[
            {
                "id": "item-1",
                "description": "Notebook",
                "field_values": [
                    {
                        "field_type": "QUANTITY",
                        "value": 30,
                        "unit": "Unidade",
                        "item_id": "item-1",
                        "evidence": [
                            {
                                "document_id": "tr-synthetic-1",
                                "page": 1,
                                "block_id": "b-001",
                                "quote": "Item 1",
                            }
                        ],
                    }
                ],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Item 1",
                    }
                ],
            }
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert QuantityMissingRule().detect(context) == []


def test_002_n2_silence_prose_quantity() -> None:
    proc = build_tr_process(
        "## 1. OBJETO\nAquisição de 50 cadeiras",
        extra_items=[
            {
                "id": "item-1",
                "description": "Cadeiras",
                "field_values": [
                    {
                        "field_type": "QUANTITY",
                        "value": 50,
                        "unit": "unidade",
                        "item_id": "item-1",
                        "evidence": [
                            {
                                "document_id": "tr-synthetic-1",
                                "page": 1,
                                "block_id": "b-001",
                                "quote": "Aquisição de 50 cadeiras",
                            }
                        ],
                    }
                ],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Aquisição de 50 cadeiras",
                    }
                ],
            }
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert QuantityMissingRule().detect(context) == []


# ---------------------------------------------------------------- RULE-003 Tests

def test_003_d1_detects_event_without_duration() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 5. MODELO DE EXECUÇÃO DO OBJETO
A contratada entregará os materiais no Almoxarifado Municipal após notificação e recebimento da Nota de Empenho.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = DeliveryDeadlineRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-003"
    assert findings[0].severity == Severity.HIGH


def test_003_d2_detects_contract_term_only() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
Aquisição de 50 cadeiras. Vigência da contratação: 12 meses.

## 5. MODELO DE EXECUÇÃO DO OBJETO
A contratada entregará os bens mediante ordem de fornecimento.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = DeliveryDeadlineRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-003"


def test_003_n1_silence_calendar_days() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 5. MODELO DE EXECUÇÃO DO OBJETO
Entrega no Almoxarifado Municipal em até 15 dias corridos da confirmação do recebimento da Nota de Empenho.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert DeliveryDeadlineRule().detect(context) == []


def test_003_n2_silence_business_days_or_immediate() -> None:
    md1 = """
# TERMO DE REFERÊNCIA

## 5. MODELO DE EXECUÇÃO
Prazo de entrega: 10 dias úteis, contados da ordem de fornecimento.
"""
    proc1 = build_tr_process(md1)
    context1 = RuleContext(process=proc1, target_document_id="tr-synthetic-1")
    assert DeliveryDeadlineRule().detect(context1) == []

    md2 = """
# TERMO DE REFERÊNCIA

## 5. MODELO DE EXECUÇÃO
Entrega imediata, no ato da retirada, mediante Nota de Empenho.
"""
    proc2 = build_tr_process(md2)
    context2 = RuleContext(process=proc2, target_document_id="tr-synthetic-1")
    assert DeliveryDeadlineRule().detect(context2) == []


def test_003_n3_silence_on_demand_with_deadline() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 5. MODELO DE EXECUÇÃO DO OBJETO
O fornecimento será parcelado, sob demanda, durante a vigência. Cada parcela deverá ser entregue no Almoxarifado Municipal em até 5 (cinco) dias úteis do recebimento da respectiva ordem de fornecimento.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert DeliveryDeadlineRule().detect(context) == []


# ---------------------------------------------------------------- RULE-004 Tests

def test_004_d1_detects_12_vs_36_months() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS DA CONTRATAÇÃO
A garantia técnica integral do Item 1 (ar-condicionado split 18.000 BTUs), prestada pela contratada, será de 12 meses.

## 5. MODELO DE EXECUÇÃO DO OBJETO
Para o mesmo Item 1, a garantia técnica integral prestada pela contratada contra defeitos será de 36 meses a partir do recebimento definitivo.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = WarrantyContradictionRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-004"
    assert "item-1/contratada/garantia-tecnica-integral" in findings[0].attrs["guarantee_key"]


def test_004_d2_detects_1_year_vs_24_months() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS DA CONTRATAÇÃO
Garantia técnica integral do Item 1 pela contratada: 1 ano.

## 5. MODELO DE EXECUÇÃO DO OBJETO
Garantia técnica integral do Item 1 pela contratada: 24 meses do recebimento definitivo.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = WarrantyContradictionRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-004"


def test_004_n1_silence_same_duration() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS DA CONTRATAÇÃO
Garantia técnica integral mínima de 12 meses pela contratada.
A mesma garantia terá 12 meses, contados do recebimento definitivo.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert WarrantyContradictionRule().detect(context) == []


def test_004_n2_silence_1_year_equals_12_months() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS DA CONTRATAÇÃO
Garantia técnica do Item 1 pela contratada: 1 ano.
Garantia técnica do Item 1 pela contratada: 12 meses do recebimento definitivo.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert WarrantyContradictionRule().detect(context) == []


def test_004_n3_silence_single_mention() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS DA CONTRATAÇÃO
Garantia técnica on-site de 12 meses. Entrega em 15 dias corridos.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert WarrantyContradictionRule().detect(context) == []


def test_004_n4_silence_not_applicable() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS DA CONTRATAÇÃO
Não se exige garantia técnica adicional para os gêneros perecíveis, considerada a validade indicada em cada embalagem e o consumo imediato após a entrega.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert WarrantyContradictionRule().detect(context) == []


# ---------------------------------------------------------------- RULE-005 Tests

def test_005_d1_detects_fiscal_and_payment_only() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 6. GESTÃO E MEDIÇÃO
O contrato será fiscalizado pelo Setor de Patrimônio. Os bens serão entregues na sede e o pagamento ocorrerá após o envio da nota fiscal.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = ReceiptRulesRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-005"
    assert set(findings[0].attrs["falta"]) == {"provisorio", "definitivo"}


def test_005_d2_detects_art_140_citation_only() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 7. MEDIÇÃO E PAGAMENTO
O recebimento observará o art. 140 da Lei nº 14.133/2021. Pagamento em até 10 dias úteis após o ateste da nota fiscal.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = ReceiptRulesRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["mode"] == "indefinido"


def test_005_d3_detects_provisorio_only() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 7. MEDIÇÃO E PAGAMENTO
Os bens serão recebidos provisoriamente, de forma sumária, no ato da entrega, pelo fiscal. Pagamento após a nota fiscal.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = ReceiptRulesRule().detect(context)

    assert len(findings) == 1
    assert findings[0].attrs["falta"] == ["definitivo"]


def test_005_d4_detects_template_placeholders() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
Os bens serão recebidos provisoriamente por <responsável>, no ato da entrega, para verificação posterior.
O recebimento definitivo ocorrerá em XXXX dias por [servidor/comissão a indicar], mediante termo detalhado.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = ReceiptRulesRule().detect(context)

    assert len(findings) == 1
    assert set(findings[0].attrs["falta"]) == {
        "responsavel_provisorio",
        "prazo_definitivo",
        "responsavel_definitivo",
    }


def test_005_n1_silence_both_rites() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
Os bens serão recebidos provisoriamente, de forma sumária, pelo fiscal no ato da entrega, para posterior verificação; e definitivamente por servidor ou comissão designada, em até 10 dias úteis após o provisório, mediante termo detalhado.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert ReceiptRulesRule().detect(context) == []


def test_005_n2_silence_simultaneous_receipt() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
Para estes bens padronizados de pronta entrega, os recebimentos provisório e definitivo ocorrerão simultaneamente no ato da entrega. O servidor municipal designado fará a conferência integral das quantidades, embalagens, validade e especificações e registrará o aceite em termo detalhado, sem prejuízo da rejeição de item desconforme.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert ReceiptRulesRule().detect(context) == []


def test_005_n3_silence_not_applicable_stage_justified() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
Em razão da conferência integral e imediata de cada unidade no balcão de retirada, não se aplica etapa provisória separada. O recebimento definitivo será realizado no mesmo ato por servidor municipal designado, após conferência de quantidade, integridade e especificação, e será registrado em termo detalhado.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert ReceiptRulesRule().detect(context) == []


# ---------------------------------------------------------------- RULE-006 Tests

def test_006_d1_emits_advisory_for_unresolved_annex() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. OBJETO
A distribuição das 500 carteiras seguirá os quantitativos e endereços das escolas relacionados no Anexo III deste Termo de Referência.
"""
    proc = build_tr_process(md)
    context = RuleContext(
        process=proc,
        target_document_id="tr-synthetic-1",
        package_files=("termo-referencia.md",),
    )
    findings = AnnexIntegrityRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-006"
    assert findings[0].severity == Severity.MEDIUM
    assert findings[0].attrs["anchor"] == "III"
    assert findings[0].attrs["rule_class"] == "ADVISORY"


def test_006_n1_silence_embedded_annex() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. OBJETO
A distribuição seguirá o Anexo I deste TR.

# ANEXO I — CRONOGRAMA E LOCAIS
1. Escola Norte — 250 carteiras.
2. Escola Sul — 250 carteiras.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert AnnexIntegrityRule().detect(context) == []


def test_006_n2_silence_roman_equals_arabic() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. OBJETO
Locais conforme Anexo III deste TR.

# ANEXO 3 — LOCAIS DE ENTREGA
Almoxarifado Municipal.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert AnnexIntegrityRule().detect(context) == []


def test_006_n3_silence_other_instrument_annex() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 2. FUNDAMENTAÇÃO
A demanda está detalhada no Anexo I do ETP municipal nº 12/2024, que não integra este TR.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert AnnexIntegrityRule().detect(context) == []


def test_006_n4_silence_annex_in_package_file() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. OBJETO
Os endereços e quantitativos constam do Anexo III deste Termo de Referência, juntado em arquivo separado.
"""
    proc = build_tr_process(md)
    context = RuleContext(
        process=proc,
        target_document_id="tr-synthetic-1",
        package_files=("termo-referencia.md", "anexo-iii-locais.pdf"),
        package_anchors={"anexo-iii-locais.pdf": ["ANEXO III"]},
    )
    assert AnnexIntegrityRule().detect(context) == []


# ---------------------------------------------------------------- RULE-007 Tests

def test_007_d1_detects_material_and_type_incompatibility() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
Item 1: 20 bebedouros industriais de coluna em aço inox, capacidade de 50 litros, 220 V.

## 4. REQUISITOS
Item 1: bebedouro de mesa, gabinete em plástico ABS, capacidade de 10 litros, 110 V.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = AttributeContradictionRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "RULE-007"
    assert findings[0].severity == Severity.HIGH


def test_007_d2_detects_discrete_attributes_incompatibility() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
Item 1: 100 gaveteiros com 4 gavetas, chapa de aço nº 24.

## 4. REQUISITOS
Item 1 — especificação: MDF 18 mm, 3 gavetas.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = AttributeContradictionRule().detect(context)

    assert len(findings) == 1
    assert set(findings[0].attrs["atributo"]) == {"numero_gavetas", "material"}


def test_007_n1_silence_compatible_refinement() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
Item 1: bebedouro de coluna em aço inox, reservatório de 50 litros, 220 V.

## 4. REQUISITOS
Item 1: tipo coluna, chapa de aço inox escovado, reservatório de 50 litros, 220 V.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert AttributeContradictionRule().detect(context) == []


def test_007_n2_silence_distinct_items() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
Item 1: bebedouro de coluna, aço inox, 50 litros, 220 V.

## 4. REQUISITOS
Item 2: bebedouro de mesa, plástico ABS, 10 litros, 110 V.
"""
    proc = build_tr_process(
        md,
        extra_items=[
            {
                "id": "item-1",
                "description": "Item 1",
                "field_values": [],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Item 1",
                    }
                ],
            },
            {
                "id": "item-2",
                "description": "Item 2",
                "field_values": [],
                "requirements": [],
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "Item 2",
                    }
                ],
            },
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert AttributeContradictionRule().detect(context) == []


def test_007_n3_silence_different_catmat_same_concept() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 1. OBJETO
Item 1: cadeira giratória de escritório, CATMAT 150123.

## 4. REQUISITOS
Item 1: cadeira giratória para escritório, CATMAT 478901, com apoio de braços.
"""
    proc = build_tr_process(
        md,
        extra_requirements=[
            {
                "attribute": "CATMAT",
                "operator": "EQUAL",
                "value": "150123",
                "item_id": "item-1",
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "CATMAT 150123",
                    }
                ],
            },
            {
                "attribute": "CATMAT",
                "operator": "EQUAL",
                "value": "478901",
                "item_id": "item-1",
                "evidence": [
                    {
                        "document_id": "tr-synthetic-1",
                        "page": 1,
                        "block_id": "b-001",
                        "quote": "CATMAT 478901",
                    }
                ],
            },
        ],
    )
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert AttributeContradictionRule().detect(context) == []


# ---------------------------------------------------------------- ADVISORY-008 Tests

def test_008_d1_emits_advisory_for_mechanical_test_without_proof() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS
O calçado de segurança deverá possuir biqueira de composite com resistência a impactos de 200 Joules e solado com resistência a escorregamento SRC.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = VerifiableRequirementRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "ADVISORY-008"
    assert findings[0].severity == Severity.MEDIUM
    assert findings[0].attrs["rule_class"] == "ADVISORY"


def test_008_d2_emits_advisory_for_performance_without_proof() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS
O tecido dos uniformes deve possuir proteção solar UV fator 50+ e propriedade retardante a chamas classe A.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    findings = VerifiableRequirementRule().detect(context)

    assert len(findings) == 1
    assert findings[0].rule_id == "ADVISORY-008"


def test_008_n1_silence_with_proof_method() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS
O calçado deverá possuir biqueira de composite de 200 Joules e solado SRC. A comprovação ocorrerá por certificado válido e laudo de ensaio de laboratório acreditado, apresentados com a proposta.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert VerifiableRequirementRule().detect(context) == []


def test_008_n2_silence_ordinary_specification() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS
Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios e apoio de braços fixos.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert VerifiableRequirementRule().detect(context) == []


def test_008_n3_silence_vague_expression_is_r9() -> None:
    md = """
# TERMO DE REFERÊNCIA

## 4. REQUISITOS
Os equipamentos deverão ser de alta qualidade e tecnologia moderna, com bom desempenho em uso contínuo.
"""
    proc = build_tr_process(md)
    context = RuleContext(process=proc, target_document_id="tr-synthetic-1")
    assert VerifiableRequirementRule().detect(context) == []
