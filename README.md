# Licita

Ferramenta para estruturar e verificar a consistência documental de processos de
compras públicas. A R1 constrói um corpus real do PNCP; o core contém o schema
estruturado e as primeiras regras determinísticas.

## Coletor R1: PNCP rarest-first

A coleta usa somente APIs públicas documentadas do PNCP e testa primeiro o elo
mais raro:

```text
/consulta/v1/contratacoes/publicacao (Pregão Eletrônico)
  → filtro federal + Lei 14.133 + aquisição de bens
  → arquivos ETP/TR/edital
  → contratos oficialmente associados
  → arquivo do contrato
```

Compras sem ETP, TR e edital são descartadas antes da consulta contratual.
Quando um órgão publica o trio, suas outras compras são priorizadas por CNPJ.
Não há busca textual, UASG, similaridade, Contratos.gov.br ou scraping.

A fila, a página de cada consulta e as falhas pendentes ficam em SQLite. Uma
falha de API nunca vira resultado vazio nem consulta concluída.

```bash
uv sync
uv run licita-corpus \
  --raiz corpus \
  --data-inicial 20240101 \
  --data-final 20251231 \
  --processos 30 \
  --reserva 5 \
  --workers 6

uv run licita-gate --raiz corpus --processos 30
```

Cada processo aceito precisa ser do Poder Executivo federal, aquisição de bens
por Pregão Eletrônico sob a Lei 14.133/2021, art. 28, I, e possuir exatamente um
documento selecionado para cada elo `ETP → TR → edital → contrato`. Os arquivos
são reabertos e seus SHA-256 são conferidos pelo gate independente.

## Testes

```bash
uv run pytest -q
python3 -m compileall -q src tests
```
