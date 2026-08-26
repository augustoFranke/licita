# Corpus real — R1

Corpus de processos do Poder Executivo federal para aquisição de bens comuns
sob a Lei 14.133/2021, coletado exclusivamente pelas APIs públicas do PNCP.

## Estratégia única: rarest-first

```text
contratações publicadas de Pregão Eletrônico
  → filtro normativo e material nos metadados
  → ETP + TR + edital nos arquivos da contratação
  → contratos oficialmente associados
  → instrumento contratual
  → download e verificação local
```

O contrato só é consultado depois que o trio documental raro existe. Órgãos que
publicam o trio são priorizados por CNPJ, limitados a seis processos no corpus.
Não são usados busca textual, UASG, similaridade, Contratos.gov.br, scraping ou
portais externos.

## Como gerar

```bash
uv run licita-corpus \
  --raiz corpus \
  --data-inicial 20240101 \
  --data-final 20251231 \
  --processos 30 \
  --reserva 5 \
  --workers 6
uv run licita-gate --raiz corpus --processos 30
```

A coleta é retomável por `harvest/rarest_first.sqlite3`. O banco conserva
inspeções e a próxima página de cada consulta. Timeouts e respostas 5xx deixam a
consulta como `PENDENTE`; nunca são convertidos em ausência documental.

## Critérios de entrada

Cada processo deve:

1. pertencer ao Poder Executivo federal;
2. ser Pregão Eletrônico com Edital;
3. declarar Lei 14.133/2021, art. 28, I;
4. ser aquisição de bens, não serviço, obra, engenharia ou locação;
5. ter ETP, TR e edital publicados na mesma contratação;
6. ter contrato inicial ligado pelo `numeroControlePncpCompra` exato;
7. ter o instrumento contratual publicado nos arquivos do contrato;
8. possuir os quatro arquivos legíveis e com texto utilizável.

## Layout

```text
corpus/
├── documentos/<processo_id>/
│   ├── metadata.json
│   ├── etp-....pdf
│   ├── tr-....pdf
│   ├── edital-....pdf
│   ├── contrato-....pdf
│   └── itens.json
├── harvest/rarest_first.sqlite3
├── catalogo/
│   ├── processos.json
│   ├── documentos.jsonl
│   ├── relacoes.json
│   ├── estatisticas.json
│   ├── processos_reprovados.json
│   └── gate.json
└── GATE_R1.md
```
