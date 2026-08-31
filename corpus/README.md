# Lote real ETP→TR municipal

Este diretório é o corpus da R1 para o perfil exclusivo
`MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`. O alvo inicial de 20 processos
**elegíveis** foi superado; o gate normativo aprova a partir de 15. Cada elegível deve ser municipal (`M`), regido
pela Lei nº 14.133/2021, modalidade Pregão Eletrônico (`PE`), aquisição de bens
e conter exatamente um ETP e um TR da mesma contratação, ambos reabertos
localmente com texto utilizável.

Os 28 processos atuais permanecem fisicamente no lote: 27 são elegíveis e o
processo SAEMA de energia é controle negativo municipal `OUT_OF_SCOPE` /
`FORA_DO_PERFIL` por objeto. O controle não entra em R2 nem no denominador de
processos, CNPJs, categorias ou limite por CNPJ. Editais, contratos e outros
tipos não compõem este lote.

## Gate, schema e diversidade

Cada registro de `catalogo/processos.json` segue o schema externo
[`corpus_process.v0.1.0.json`](../schemas/corpus_process.v0.1.0.json). Exemplos
`SUPPORTED` e `OUT_OF_SCOPE` ficam em [`schemas/examples/`](../schemas/examples/).
Esse manifesto não altera o payload fechado `ProcurementProcess` usado pela R2.

O gate é calculado somente sobre os elegíveis e exige:

- pelo menos 15 processos (alvo 20);
- pelo menos 5 CNPJs distintos;
- pelo menos 3 categorias de objeto;
- no máximo 5 processos por CNPJ;
- esfera `M`, Lei nº 14.133/2021, PE, bens e exatamente ETP/TR em cada processo.

## Estratégia

```text
Compras.gov.br /modulo-contratacoes/..._PNCP_14133
  → Pregão Eletrônico (codigoModalidade=5; modalidadeIdPncp=6)
  → esfera municipal e Lei nº 14.133/2021
  → filtro conservador de aquisição de bens
  → PNCP /api/.../compras/{ano}/{sequencial}/arquivos
  → identificação de ETP/TR
  → download e validação local de exatamente 1 ETP + 1 TR
```

PNCP e Compras.gov são canais de descoberta e download, não fontes normativas.
A busca textual pública do PNCP (`Estudo Tecnico Preliminar` / `ETP`) é apenas
acelerador. O detalhe e a lista de arquivos vêm do PNCP; se a busca estiver
indisponível, o feed do Compras.gov continua.

## Originais e OCR

Todo original é imutável e conferido pelo SHA-256 dos bytes baixados. OCR pode
ser usado para qualquer arquivo que necessite de extração adicional. O cache é
indexado por:

```text
SHA-256 do original + idioma + versão/configuração do OCR
```

A saída é artefato derivado auditável e deve registrar vínculo com o original,
idioma, ferramenta, versão/configuração, hash próprio e data. Ela nunca
substitui o arquivo original. A política oficial é
`4-municipal-historical-ocr`. O lote físico foi originalmente obtido sob
`2-historical-ocr` e revalidado sob a política municipal; o catálogo conserva
ambos em `collection_policy_version` e `policy_version`.

## Limites e retomada

- Compras.gov: páginas de 10 a 500; a coleta usa 500 e janelas de 31 dias.
- PNCP: no máximo 500 registros por página onde o endpoint aceita.
- Intervalo mínimo 0,75 s; respeita `Retry-After`; retry em timeout, 429 e 5xx.
- Orçamento local: 900 chamadas por dia UTC (`--max-requisicoes-dia`).
- Estado em `corpus/estado/etp_tr.sqlite3`. Falha de API não vira lista vazia.

```bash
uv run licita-corpus \
  --raiz corpus \
  --data-inicial 20240101 \
  --data-final 20251231 \
  --processos 20 \
  --fonte auto \
  --esferas M \
  --max-por-orgao 5

uv run licita-gate --raiz corpus \
  --processos 15 \
  --orgaos 5 \
  --categorias 3 \
  --max-por-orgao 5 \
  --esferas M
```

`auto` tenta a busca pública por `ETP` e depois o feed oficial do Compras.gov.
Fonte única: `pncp-busca`, `compras` ou `pncp-feed`.

## Layout

```text
corpus/
├── documentos/<processo_id>/
│   ├── metadata.json
│   ├── etp-....pdf|docx
│   └── tr-....pdf|docx
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
