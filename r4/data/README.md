# Dados do golden R4

O conjunto provisório fica em `dev/` e `eval/`, com cinco processos em cada pasta.
Os dez payloads ativos validam como `ProcurementProcess` e somam 392
valores/requisitos. Nenhum payload ativo tem procedência `engine_generated`.

`candidates/` é histórico e não participa dos gates. Em particular, a cópia
de `76017474000108-1-000118-2025` foi preservada ali depois de ser retirada de
`eval`, pois seus 182 registros haviam sido produzidos pelo mesmo motor que o
golden deveria avaliar.

O processo substituto `90836693000140-1-000431-2026` pertence ao lote policy
8 e foi materializado a partir de uma leitura direta dos ETP e TR originais.
Apesar disso, uma execução prematura do benchmark R5 abriu todos os cinco
processos de `eval`. Eles devem migrar para `dev` e ser substituídos antes do
congelamento definitivo do holdout.

Validação estrutural:

```bash
uv run pytest -q tests/test_r4_golden.py
```

O resultado estrutural não fecha sozinho a R4. A leitura B cega e a
adjudicação estão descritas em `../review/README.md` e medidas por
`tests/test_r4_review_gate.py`.
