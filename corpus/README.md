# Corpus de cadeias completas do PNCP

Este diretório é o corpus da R1 para o perfil
`PUBLICO_14133_PREGAO_ELETRONICO_BENS`. Novas coletas partem exclusivamente do
feed de contratos e só publicam uma cadeia completa:
`Contrato → contratação vinculada → Edital + ETP + TR`. O contrato, o edital, o
ETP e o TR precisam ser exatamente um documento utilizável de cada papel.

O filtro de perfil é aplicado antes de consultar anexos ou baixar arquivos:
Lei nº 14.133/2021, Pregão Eletrônico (`PE`), aquisição de bens comuns e ente
das esferas federal, estadual, distrital ou municipal (`F`/`E`/`D`/`M`).

Os processos históricos já existentes permanecem fisicamente no corpus, mesmo
quando foram coletados apenas com ETP/TR. Eles continuam disponíveis para as
fases posteriores e podem ser promovidos a completos quando os elos faltantes
forem encontrados. A exigência de quatro documentos vale para novos aceites.
Registros fora do perfil continuam auditáveis, mas não entram nos denominadores
de processos, CNPJs ou categorias.

`catalogo/estatisticas.json` é um snapshot do catálogo histórico preservado,
não uma execução nova da policy
`8-cadeia-completa-documentos-utilizaveis`. Ele explicita essa condição e
separa as tarefas legadas da fila `pncp-contratos`; a próxima coleta substituirá
os campos operacionais por medições da execução.

## Gate, schema e diversidade

Cada registro de `catalogo/processos.json` segue o schema externo
[`corpus_process.v0.1.0.json`](../schemas/corpus_process.v0.1.0.json). Exemplos
`SUPPORTED` e `OUT_OF_SCOPE` ficam em [`schemas/examples/`](../schemas/examples/).
Esse manifesto não altera o payload fechado `ProcurementProcess` usado pela R2.

O gate é calculado somente sobre os elegíveis e exige:

- pelo menos 15 processos (alvo 20) no conjunto elegível;
- pelo menos 5 CNPJs distintos;
- pelo menos 3 categorias de objeto;
- no máximo 5 processos por CNPJ;
- Lei nº 14.133/2021, PE, bens e esfera `F`/`E`/`D`/`M`;
- em cada processo novo, exatamente ETP, TR, Edital e instrumento contratual,
  todos reabertos localmente com texto utilizável e relacionados na cadeia.

Processos históricos sem edital ou contrato são mantidos como exceção de
compatibilidade e identificados pela sua `collection_policy_version` anterior.

## Estratégia

```text
PNCP /api/consulta/v1/contratos (feed de contratos)
  → numeroControlePNCPCompra (contratação vinculada)
  → detalhe da contratação e filtro de perfil
  → uma consulta de anexos da contratação (ETP, TR e Edital)
  → uma consulta de anexos do contrato (instrumento contratual)
  → escolha/classificação das revisões
  → download atômico e verificação local dos quatro documentos
  → publicação do processo somente se a cadeia estiver completa
```

O detalhe e as duas listas de anexos vêm do PNCP. PNCP é canal de publicação e
obtenção de dados, não fonte normativa. A busca textual e o Compras.gov.br
continuam disponíveis para consumidores históricos, mas não são estratégias de
descoberta da coleta vigente.

## Originais e OCR

Todo original é imutável e conferido pelo SHA-256 dos bytes baixados. OCR pode
ser usado para qualquer arquivo que necessite de extração adicional. O cache é
indexado por:

```text
SHA-256 do original + idioma + versão/configuração do OCR
```

A saída é artefato derivado auditável e deve registrar vínculo com o original,
idioma, ferramenta, versão/configuração, hash próprio e data. Ela nunca
substitui o arquivo original. A policy vigente da coleta é
`8-cadeia-completa-documentos-utilizaveis`. Aceites históricos preservam suas versões
anteriores em `collection_policy_version` e `policy_version`.

## Limites e retomada

- Feed de contratos do PNCP: no máximo 500 contratos por página e janelas de
  31 dias.
- Para cada contratação elegível, a lista de anexos da contratação e a lista de
  anexos do contrato são consultadas uma única vez (cacheadas no estado).
- Intervalo mínimo 0,75 s; respeita `Retry-After`; retry em timeout, 429 e 5xx.
- Sem teto diário local por padrão (`--max-requisicoes-dia 0`); o intervalo,
  `Retry-After` e os retries controlam a pressão sobre o PNCP.
- Estado em `corpus/estado/etp_tr.sqlite3`; falha de API não vira lista vazia.
- Cada arquivo é gravado com lock, temporário e `replace` atômico. O processo e
  o catálogo só são publicados depois da verificação dos quatro documentos.

```bash
uv run licita-corpus \
  --raiz corpus \
  --data-inicial 20240101 \
  --data-final 20251231 \
  --processos 20 \
  --fonte contratos \
  --esferas F,E,D,M \
  --max-por-orgao 5

uv run licita-gate --raiz corpus \
  --processos 15 \
  --orgaos 5 \
  --categorias 3 \
  --max-por-orgao 5 \
  --esferas F,E,D,M
```

`--fonte` aceita nomes históricos por compatibilidade, mas todos apontam para o
feed de contratos. Não há uma segunda estratégia de descoberta.

## Layout

```text
corpus/
├── documentos/<processo_id>/
│   ├── metadata.json
│   ├── etp-....pdf|docx
│   ├── tr-....pdf|docx
│   ├── edital-....pdf|docx
│   └── contrato-....pdf|docx
├── estado/etp_tr.sqlite3
├── catalogo/
│   ├── processos.json
│   ├── documentos.jsonl
│   ├── relacoes.json
│   ├── estatisticas.json
│   ├── processos_reprovados.json
│   └── gate.json
└── GATE_R1.md
```

Originais e estado de retomada ficam fora do Git; catálogos, metadados dos
artefatos derivados e o gate podem ser versionados.
