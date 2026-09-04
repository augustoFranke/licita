# Gate do Golden Dataset (R4)

**Resultado: PARCIAL — amostra, volume, schema e evidências passaram; segunda
leitura independente pendente.**

Estado medido em 2026-09-04 sobre o split congelado de `r4/manifest.json`.

| Critério | Exigido | Obtido | Status |
|---|---:|---:|:---:|
| Processos reais e elegíveis | 10–15 | 10 | ✅ |
| Split por processo | disjunto e congelado | 5 `dev` + 5 `eval` | ✅ |
| Valores/requisitos | ≥300 | 392 | ✅ |
| Payloads no schema vigente | 100% | 10/10 | ✅ |
| Evidências navegáveis | 100% | 100% | ✅ |
| Hashes dos originais | 100% | 20/20 documentos | ✅ |
| Anotações `engine_generated` no split | 0 | 0 | ✅ |
| Leitura A diretamente da fonte | 10 processos | 10/10 | ✅ |
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

R5 não pode começar enquanto um revisor B distinto não receber somente as
fontes e o guia, produzir uma auditoria cega de cada processo e adjudicar as
diferenças. As instruções e o formato do registro ficam em `r4/review/README.md`.

Reprodução da parcela automatizada:

```bash
uv run pytest -q tests/test_r4_golden.py tests/test_r4_review_gate.py -s
```

O resultado esperado antes da revisão humana é: validações estruturais verdes
e um teste explicitamente ignorado com a contagem dos processos ainda não
adjudicados. Esse `skip` é a representação intencional da porta humana, não um
aceite da fase.
