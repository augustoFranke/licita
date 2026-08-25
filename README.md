# Licita

Ferramenta para estruturar e verificar a consistência documental de processos de
compras públicas. A R1 constrói um corpus real do PNCP; o core contém o schema
estruturado e as primeiras regras determinísticas.

## Coletor R1: PNCP contract-first

A coleta usa somente APIs públicas do PNCP e começa pelos contratos publicados:

```text
/api/consulta/v1/contratos
  → numeroControlePncpCompra
  → detalhe da contratação
  → arquivos ETP/TR/edital
  → contratos associados à contratação
  → arquivos do contrato
```

Não há busca textual, cruzamento por UASG, similaridade de objeto,
Contratos.gov.br ou coleta manual. O vínculo é exclusivamente o identificador
oficial `numeroControlePncpCompra`.

```bash
uv sync
uv run licita-corpus \
  --raiz corpus \
  --data-inicial 20240101 \
  --candidatos 100 \
  --processos 30

uv run licita-gate --raiz corpus --processos 30
```

Cada processo aceito precisa ser do Poder Executivo federal, aquisição de bens
por Pregão Eletrônico sob a Lei 14.133/2021, art. 28, I, e possuir exatamente um documento selecionado
para cada elo `ETP → TR → edital → contrato`. Os arquivos são reabertos e seus
SHA-256 são conferidos pelo gate independente.

## Testes

```bash
uv run pytest -q
python3 -m compileall -q src tests
```
