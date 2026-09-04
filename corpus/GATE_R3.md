# Gate da Ingestão Documental (R3)

**Resultado: PASSOU — 40 de 40 trechos necessários foram reabertos.**

O gate usa dez processos do lote recolhido sob a policy
`8-cadeia-completa-documentos-utilizaveis`. Para cada processo, uma leitura
manual identificou um trecho de cada categoria que as fases seguintes exigem:
quantidade, especificação, prazo de entrega e garantia. Esse inventário
explícito de 40 trechos é o denominador da medição.

Cada documento original foi reaberto do disco, teve o SHA-256 conferido contra
`corpus/catalogo/documentos.jsonl` e foi processado novamente. O teste então
confirmou o `block_id`, a página e a citação literal de cada âncora.

| Critério | Exigido | Obtido | Status |
|---|---:|---:|---|
| Processos elegíveis do lote policy 8 | 10 | 10 | ✅ |
| Cadeia completa por processo | ETP + TR + Edital + Contrato | 10/10 | ✅ |
| Categorias por processo | 4 | 4/4 | ✅ |
| Trechos necessários inventariados | 40 | 40 | ✅ |
| Reabertura dos trechos | ≥95% | **100% (40/40)** | ✅ |
| Imutabilidade dos originais usados | 100% | 100% | ✅ |
| Página, `block_id` e citação literal | 100% | 100% | ✅ |
| Falhas silenciosas de parsing | 0 | 0 | ✅ |

## Evidência reproduzível

- Inventário manual: `r3/anchors.manual.json`.
- Teste do gate: `tests/test_r3_current_lot.py`.
- Reprodução: `uv run pytest -q tests/test_r3_current_lot.py -s`.
- Resultado observado em 2026-09-04: `1 passed`, com 40/40 âncoras reabertas.

O benchmark histórico de `r4/data/` continua preservado, mas não entra nesta
medição: seus processos não pertencem ao lote policy 8 atual e parte de suas
âncoras foi gerada pelo próprio motor. Assim, ele não substitui a leitura
manual nem infla o numerador deste gate.
