# R2 — Modelo estruturado

Esta pasta contém a prova da R2 sobre cinco processos reais do lote de cadeias
completas da policy `8-cadeia-completa-documentos-utilizaveis`.

- `annotations.manual.json`: decisões de leitura e normalização, com documento,
  página e `block_id` explícitos;
- `data/`: payloads `ProcurementProcess` materializados;
- `manifest.json`: proveniência, hashes dos vinte originais e hashes dos cinco
  artefatos.

Regeneração:

```bash
uv run python tools/build_r2_current.py
uv run pytest -q tests/test_r2_current_lot.py
```

O gerador não extrai fatos. Ele somente reabre os quatro documentos de cada
processo e aplica as anotações manuais versionadas. O teste confirma os dois
schemas, a origem dos IDs no lote atual, os hashes e a cobertura dos nove
`FieldType`, além de ao menos um requisito técnico por processo.
