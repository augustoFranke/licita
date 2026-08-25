# Corpus real — R1

Corpus de processos federais de aquisição de bens comuns sob a Lei 14.133/2021,
coletado exclusivamente pelas APIs públicas do PNCP.

## Estratégia única: contract-first

```text
contratos publicados no período
  → numeroControlePncpCompra
  → metadados da contratação de origem
  → ETP + TR + edital nos arquivos da contratação
  → contratos oficialmente associados
  → instrumento contratual nos arquivos do contrato
  → download e verificação local
```

Não são usados busca textual, UASG, similaridade, Contratos.gov.br, portais de
órgãos ou cliques manuais. Falha de API interrompe a coleta e não é registrada
como resultado vazio.

## Como gerar

```bash
uv run licita-corpus \
  --raiz corpus \
  --data-inicial 20240101 \
  --candidatos 100 \
  --processos 30
uv run licita-gate --raiz corpus --processos 30
```

A inspeção é retomável em `harvest/contract_first.jsonl`. Só inspeções concluídas
são gravadas; requisições interrompidas serão refeitas.

## Critérios de entrada

Cada processo deve:

1. pertencer ao Poder Executivo federal;
2. ser Pregão Eletrônico com Edital;
3. declarar amparo na Lei 14.133/2021, art. 28, I;
4. ser aquisição de bens, não serviço, obra, engenharia ou locação;
5. ter ETP, TR e edital publicados nos arquivos da mesma contratação;
6. ter contrato inicial ligado pelo `numeroControlePncpCompra` exato;
7. ter o instrumento contratual publicado nos arquivos desse contrato;
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
├── harvest/contract_first.jsonl
├── catalogo/
│   ├── processos.json
│   ├── documentos.jsonl
│   ├── relacoes.json
│   ├── estatisticas.json
│   ├── processos_reprovados.json
│   └── gate.json
└── GATE_R1.md
```

O catálogo conserva URLs oficiais, identificadores PNCP, hashes, resultado de
abertura e relações `ETP → TR → edital → contrato`.
