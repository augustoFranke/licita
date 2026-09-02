# Licita

Ferramenta para estruturar e verificar a consistência documental de processos
públicos de compras no perfil exclusivo
`PUBLICO_14133_PREGAO_ELETRONICO_BENS`.

O produto atual inteiro cobre somente aquisições públicas de bens por Pregão
Eletrônico (PE), sob a Lei nº 14.133/2021. PNCP e Compras.gov são canais de
dados, não fontes normativas.

- **Produto e perfil:** [`docs/README.md`](docs/README.md) e `docs/00`–`04`
- **Fatia atual:** M0–M1 (`docs/scope.md`, `docs/Plano.md`)
- **Corpus de cadeias completas:** [`corpus/README.md`](corpus/README.md)

```bash
uv sync
uv run pytest -q
python3 -m compileall -q src tests
```

## Revisão humana (R6)

A UI de revisão persiste processos e trilha de auditoria em PostgreSQL. Sem a
variável, ela sobe em memória e avisa no log que revisão e audit log somem no
restart — nesse modo a R6 não fecha.

```bash
LICITA_REVIEW_DB_URL=postgresql://licita@100.96.253.2:5432/licita \
  uv run uvicorn licita_review.app:app --port 8011
```

A senha fica com o libpq (`~/.pgpass`), nunca na URL nem no repositório. O
schema é criado sozinho na subida. A integração roda com a mesma variável:

```bash
LICITA_REVIEW_DB_URL=postgresql://licita@100.96.253.2:5432/licita \
  uv run pytest tests/test_r6_postgres.py -q
```
