# Gate da Ingestão Documental (R3)

**Resultado: PARCIAL — a prova independente cobre 54 âncoras, não 710.**

Verificação de reabertura de âncoras (`arquivo → blocos`) sobre os 10 processos
de `r4/data/candidates/` (20 documentos: 10 ETPs e 10 TRs). Cada original foi
reaberto do disco e teve o SHA-256 conferido contra `corpus/catalogo/documentos.jsonl`.

## Por que o número total não prova a fase

Das 710 evidências dos candidatos, **656 pertencem a três processos cuja
anotação é `engine_generated`** (`r4/manifest.json`): as quotes foram
produzidas pelo mesmo extrator que o teste usa para reabri-las. Verificar
`quote in block.text` nesse subconjunto confirma que a função concorda consigo
mesma; não prova que um trecho escolhido por pessoa reabre.

A prova válida é o subconjunto de anotação `manual`, em que a quote foi
escolhida lendo o documento.

| Critério | Exigido | Obtido | Status |
|---|---|---|---|
| Processos avaliados | 10 | 10 | ✅ |
| Documentos avaliados (ETP + TR) | 20 | 20 | ✅ |
| Imutabilidade dos originais (SHA-256) | 100% | 100% (20/20) | ✅ |
| Âncoras de anotação **manual** | ≥50 | 54 | ✅ |
| Reabertura das âncoras manuais | ≥95% | **100,00%** (54/54) | ✅ |
| Falhas silenciosas de parsing/OCR (NFR-002) | 0 | 0 | ✅ |
| Página ≥1 e citação literal | 100% | 100% | ✅ |
| Âncoras `engine_generated` (não contam) | — | 656 | ⚠️ |
| Cobertura dos trechos que a R4 precisará | ≥95% | **não medido** | ❌ |

O último critério é o que mantém a fase em PARCIAL: o denominador do
`Plano.md` são os trechos que a R4 **vai precisar** para quantidade,
especificação, prazo e garantia. Com 29 valores de anotação manual em todo o
golden, esse denominador ainda não existe. As 54 âncoras provam que o
mecanismo de ancoragem funciona; não provam cobertura.

## Detalhamento por processo

| # | Processo | Procedência | Evidências | Reabertas | Taxa |
|---|---|---|---|---|---|
| 1 | `01612698000169-1-000047-2024` | manual | 5 | 5 | 100,00% |
| 2 | `13988308000139-1-000095-2024` | manual | 9 | 9 | 100,00% |
| 3 | `17749896000290-1-000055-2024` | manual | 9 | 9 | 100,00% |
| 4 | `25105255000140-1-000041-2024` | manual | 9 | 9 | 100,00% |
| 5 | `87613022000105-1-000106-2024` | manual | 6 | 6 | 100,00% |
| 6 | `87613022000105-1-000285-2025` | manual | 8 | 8 | 100,00% |
| 7 | `88814181000130-1-000215-2024` | manual | 8 | 8 | 100,00% |
| 8 | `52061181000160-1-000080-2024` | engine_generated | 139 | 139 | não conta |
| 9 | `76017474000108-1-000118-2025` | engine_generated | 229 | 229 | não conta |
| 10 | `83026138000197-1-000126-2024` | engine_generated | 288 | 288 | não conta |

## Verificação das âncoras navegáveis

Cada evidência aprovada cumpre cumulativamente:

1. `document_id` compatível com o documento extraído;
2. `page` física ou lógica ≥1;
3. `block_id` existe na lista de blocos estruturados;
4. `quote` é substring verificável do texto bruto do bloco.

Reprodução: `uv run pytest tests/test_r3_benchmark.py -q -s`.
