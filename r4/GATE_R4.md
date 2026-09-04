# Gate do Golden Dataset (R4)

**Resultado: PARCIAL — amostra, volume, schema e evidências passaram; novo
holdout e segunda leitura independente pendentes.**

Estado medido em 2026-09-04 sobre o split congelado de `r4/manifest.json`.

| Critério | Exigido | Obtido | Status |
|---|---:|---:|:---:|
| Processos reais e elegíveis | 10–15 | 10 | ✅ |
| Split por processo | disjunto e congelado | 5 `dev` + 5 `eval` provisórios | ❌ |
| Valores/requisitos | ≥300 | 392 | ✅ |
| Payloads no schema vigente | 100% | 10/10 | ✅ |
| Evidências navegáveis | 100% | 100% | ✅ |
| Hashes dos originais | 100% | 20/20 documentos | ✅ |
| Anotações `engine_generated` no split | 0 | 0 | ✅ |
| Leitura A diretamente da fonte | 10 processos | 10/10 | ✅ |
| `eval` nunca executado pela R5 | 5 processos | 0/5 | ❌ |
| Leitura B cega por revisor distinto | 10 processos | 0/10 | ❌ |
| Adjudicação sem ambiguidade de política | 10 processos | 0/10 | ❌ |

## Correção da contaminação

O processo `76017474000108-1-000118-2025`, cuja anotação ativa tinha sido
gerada pelo próprio extrator, foi removido de `eval`. Sua cópia histórica foi
preservada em `r4/data/candidates/` para auditoria, mas não conta para R4, R5
ou R7.

O substituto `90836693000140-1-000431-2026` foi lido diretamente nos ETP e TR
originais, sem consultar o payload excluído nem uma saída da R5. Sua leitura A
tem 80 registros: dez campos e setenta requisitos. O split ativo passou a
somar 318 campos e 74 requisitos.

## Porta ainda fechada

Uma execução de regressão da R5 abriu os cinco processos de `eval` antes do
fechamento da R4. As métricas observadas não podem ser usadas para ajustar o
motor, e esses cinco processos deixam de ser um holdout válido. Eles devem
migrar para `dev` e ser substituídos por cinco processos elegíveis nunca
medidos antes do congelamento definitivo.

Os substitutos reservados, cujas fontes ETP/TR já foram reabertas, são:

- `87613048000153-1-000119-2024`;
- `83024240000153-1-000099-2024`;
- `52061181000160-1-000057-2024`;
- `88814181000130-1-000180-2024`;
- `88814181000130-1-000098-2024`.

O estado `SOURCE_REOPENED_READING_A_PENDING` no manifesto registra que a
reserva não equivale a anotação nem ao congelamento do holdout.

Depois disso, R5 ainda não pode começar enquanto um revisor B distinto não
receber somente as fontes e o guia, produzir uma auditoria cega de cada
processo e adjudicar as diferenças. As instruções e o formato do registro
ficam em `r4/review/README.md`.

Reprodução da parcela automatizada:

```bash
uv run pytest -q tests/test_r4_golden.py tests/test_r4_review_gate.py -s
```

O resultado esperado enquanto o gate está parcial é: validações estruturais
verdes, um `skip` para o holdout contaminado e outro para a contagem dos
processos ainda não adjudicados. Esses `skip`s representam portas abertas, não
aceite da fase.
