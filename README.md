# Licita

Ferramenta para estruturar e verificar a consistência documental de processos
municipais de compras públicas no perfil exclusivo
`MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`.

O produto atual inteiro cobre somente aquisições municipais de bens por Pregão
Eletrônico (PE), sob a Lei nº 14.133/2021. PNCP e Compras.gov são canais de
dados, não fontes normativas.

- **Produto e perfil:** [`docs/README.md`](docs/README.md) e `docs/00`–`04`
- **Fatia atual:** M0–M1 (`docs/scope.md`, `docs/Plano.md`)
- **Corpus ETP→TR:** [`corpus/README.md`](corpus/README.md)

```bash
uv sync
uv run pytest -q
python3 -m compileall -q src tests
```
