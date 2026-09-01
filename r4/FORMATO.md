# R4 — Formato da anotação

Este documento define o formato do *golden dataset* da R4. O payload de uma
anotação é **exatamente** um `ProcurementProcess` do schema atual
`0.1.0`; não é um novo schema e não acrescenta propriedades à raiz. Em
particular, perfil, esfera, hashes e OCR nunca são campos do payload: ficam no
manifesto/catálogo externo.

O arquivo `exemplo_processo_sintetico.json` é apenas um exemplo executável. Ele
é totalmente fictício, não é parte do corpus e não conta para a meta da R4.

## Unidade e armazenamento

- Uma anotação corresponde a um processo e é um objeto JSON UTF-8 por arquivo.
- O nome recomendado é `<process_id>.json`; `id` deve ser estável e único.
- JSON é o formato canônico porque o validador existente lê um objeto por
  arquivo. Uma exportação JSONL pode ter um objeto completo por linha, mas cada
  linha deve ser validada separadamente antes de ser usada.
- YAML só é aceitável depois de convertido para o mesmo objeto JSON; não se
  deve inventar uma segunda representação semântica.
- O conjunto pode ser organizado, sem alterar o payload, como:

  ```text
  r4/data/dev/<process_id>.json
  r4/data/eval/<process_id>.json
  r4/review/<process_id>.json       # registro externo de revisão, se usado
  ```

  Esses diretórios são uma convenção de organização. `dev`, `eval`, estado da
  revisão, perfil, esfera, hashes e OCR **não** entram no objeto
  `ProcurementProcess`, pois o modelo fechado rejeita propriedades
  desconhecidas.

## Forma da raiz

```json
{
  "id": "processo-estavel",
  "schema_version": "0.1.0",
  "documents": [],
  "findings": []
}
```

`schema_version` pode ser omitido para usar o default, mas é recomendado
escrevê-lo. Os únicos campos válidos na raiz são `id`, `schema_version`,
`documents` e `findings`.

### Identificadores e referências

- `Document.id` identifica um documento da cadeia e deve ser único no processo.
  `Document.type` segue `01_REQUIREMENTS.md`: `DFD`, `ETP`, `TR`, `EDITAL`,
  `CONTRATO`, `PESQUISA_PRECOS`, `OUTROS`. `format` só pode ser `PDF` ou `DOCX`.
  A R4 atual anota somente os ETP/TR elegíveis do lote exclusivo municipal; os
  demais enums continuam no schema sem ampliar este recorte.
- `Section.id` é estável. Cada seção deve manter `title_original` e pode ter
  `section_type_normalized` (por exemplo, `ITEMS`, `EXECUTION`, `RECEIPT`,
  `MEASUREMENT` ou `PAYMENT`). Esse valor é uma convenção, não um enum do
  schema.
- Cada bloco ingerido que possa ser citado recebe `DocumentBlock.id`,
  `type` e `text`. IDs de blocos são únicos no processo, não apenas dentro da
  seção.
- `Item.id` é único dentro do documento. Um item equivalente em outro
  documento recebe outro ID, mas a evidência deve deixar clara a equivalência.
- IDs não devem ser regenerados a cada revisão; mudar um ID quebra evidências.

## Evidência e texto original

Toda anotação estruturada (`Item`, `FieldValue`, `Requirement` e `Finding`) tem
pelo menos uma `Evidence`. Cada evidência contém:

```json
{
  "document_id": "doc-tr",
  "page": 3,
  "block_id": "blk-tr-12",
  "quote": "trecho copiado literalmente",
  "attr": "technical.accuracy"
}
```

A política de evidência é:

1. `page` começa em 1; nunca usar 0, número estimado ou página inexistente.
2. `document_id` deve apontar para um documento do mesmo processo.
3. `block_id` deve existir em uma seção daquele documento.
4. `quote` é texto original, não paráfrase, e precisa ser uma substring de
   `DocumentBlock.text`. O trecho deve ser o menor trecho suficiente para
   sustentar o valor; use várias evidências quando a afirmação depende de
   blocos distintos.
5. `attr` é opcional. Quando usado, recebe o nome do campo/requisito ao qual o
   trecho se refere e ajuda a auditar tabelas com vários valores.
6. A seção também precisa de uma evidência navegável. Ela normalmente aponta
   para o primeiro bloco da seção.

O schema atual mantém texto original em `DocumentBlock.text`,
`Section.title_original` e `Evidence.quote`. Esses textos-fonte são literais e
não devem ser reescritos, inclusive quando contiverem nomes ou termos alheios
ao perfil. O original é imutável; eventual OCR é um artefato derivado
rastreado externamente. `Requirement` não possui campos
`texto_original`, `section_id` ou `document_id`: não os adicione. O texto,
documento e página da exigência são recuperados pela sua `Evidence`; a seção é
determinada pela seção que contém o bloco citado.

A validação JSON Schema verifica a forma. A validação Pydantic do projeto
verifica também IDs, existência dos blocos e inclusão de `quote` no texto do
bloco; as duas camadas são necessárias.

## Itens

Crie um `Item` para cada linha, lote ou produto identificável no documento, e
não para cada menção casual ao produto. `description` é uma descrição curta e
normalizada; nomes, especificações e quantidade originais continuam na
Evidence. Um item precisa de evidência própria, mesmo que seus campos também
tenham evidências.

- Itens diferentes na mesma tabela recebem IDs diferentes.
- Se a tabela não permite separar as linhas, não invente linhas: registre a
  limitação como achado de revisão.
- Coloque fatos específicos do item em `item.field_values` e
  `item.requirements`.
- Fatos que valem para o documento/processo inteiro ficam em
  `document.field_values` ou `document.requirements`.
- Se `item_id` for escrito dentro de um item, ele deve ser exatamente o ID do
  item pai. Em nível de documento, `item_id` deve apontar para item daquele
  documento.

## Valores estruturados (`FieldValue`)

Use um `FieldValue` para um fato nominal ou mensurável. O valor normalizado
fica em `value`; a unidade, quando houver, fica em `unit`; a formulação
original fica na evidência. `review_status` começa em `EXTRACTED` e só vira
`CONFIRMED` após revisão humana com evidência (`FR-013`/`FR-014`). A unidade é uma string livre no schema, mas a
anotação deve usar formas consistentes:

- `kit`, `unidade`, `kg` e `°C` para unidades de medida;
- `dias_corridos`, `dias_uteis` e `meses` para duração;
- `BRL` para valores monetários;
- localizações como texto em `value`, normalmente sem `unit`.

| `field_type` | Política de normalização |
| --- | --- |
| `QUANTITY` | Número positivo. Use `unit` quando a fonte declarar a unidade; se a fonte trouxer o número sem unidade, mantenha `unit: null` e sinalize a lacuna na revisão. |
| `DELIVERY_DEADLINE` | Duração numérica + unidade normalizada, ou data ISO como string quando a fonte der uma data. |
| `CONTRACT_TERM` | Duração do contrato/vigência, normalmente número + `meses` ou `dias_corridos`. |
| `WARRANTY_TERM` | Duração da garantia, preservando no requisito qualquer qualificativo como “mínima” ou “máxima”. |
| `UNIT_PRICE` | Número monetário não negativo, preferencialmente string decimal com ponto (`"125.50"`), `unit: "BRL"`. |
| `TOTAL_PRICE` | Número monetário não negativo, na mesma convenção do preço unitário. |
| `DELIVERY_LOCATION` | Local normalizado como string; não deduza endereço que não aparece na fonte. |
| `RECEIPT_DEADLINE` | Prazo para recebimento, com unidade normalizada. |
| `PAYMENT_DEADLINE` | Prazo para pagamento, com unidade normalizada. |

`QUANTITY` exige número positivo no modelo Pydantic atual; não use string
`"20"`, zero ou número negativo. Valores monetários não podem ser negativos.
Não use `null` em `FieldValue.value`: o campo é obrigatório. Ausência de um
valor é diferente de valor nulo e é tratada na política de ambiguidades da
[GUIA](GUIA.md).

## Requisitos (`Requirement`)

Use `Requirement` para especificações técnicas, limites, condições e
obrigações de execução. Atributos são strings normalizadas em *snake case*
dentro de uma categoria com ponto; essa taxonomia é uma convenção da R4 e não
altera o schema. Exemplos:

- `technical.measurement_range`, `technical.accuracy`;
- `execution.packaging`, `execution.installation_included`;
- `receipt.provisional`, `receipt.acceptance_criteria`;
- `measurement.acceptance_basis`, `measurement.record`;
- `payment.trigger`, `payment.condition`;
- `warranty.coverage`.

Escolha o operador pela linguagem da fonte:

| Linguagem da fonte | Operador e valor |
| --- | --- |
| “igual a”, característica exata | `EQUAL` com escalar |
| “diferente de” | `NOT_EQUAL` |
| “maior/menor que” | `GREATER_THAN`, `GREATER_THAN_OR_EQUAL`, `LESS_THAN` ou `LESS_THAN_OR_EQUAL` |
| “entre X e Y” | `BETWEEN` com lista ordenada de exatamente dois valores |
| “A, B ou C” | `IN` com lista não vazia |
| obrigação textual curta | `CONTAINS` com uma formulação normalizada curta |
| presença ou ausência explicitamente declarada | `EXISTS` com `true` ou `false` |

Valores de comparação devem ser numéricos finitos ou datas; `BETWEEN` deve
manter os limites na ordem apresentada/normalizada. `CONTAINS` não é licença
para copiar um parágrafo inteiro: use-o apenas quando não houver uma forma
numérica, booleana ou enumerada melhor, e preserve o parágrafo em `quote`.

`execution`, `receipt`, `measurement` e `payment` não têm tipos próprios no
schema `0.1.0`. Portanto, seus prazos vão em `FieldValue` (`DELIVERY_DEADLINE`,
`RECEIPT_DEADLINE` ou `PAYMENT_DEADLINE`) e suas condições/procedimentos vão em
`Requirement` com os atributos acima. Não crie `execution`, `receipt`,
`measurement` ou `payment` como novas chaves de `Document`.

## Achados (`Finding`)

`Finding` não é um rótulo “aprovado/reprovado” e não substitui um fato
extraível. Use-o como registro de conflito, ilegibilidade ou limitação que
precisa de revisão humana. Todo achado precisa de evidência e começa com
`status: "OPEN"`. Status de decisão: `UNDER_REVIEW`, `RESOLVED`,
`ACCEPTED_RISK`, `FALSE_POSITIVE` (`FR-081`). Severidade: `HIGH`, `MEDIUM`,
`INFO`. `attrs` pode carregar detalhes auxiliares, mas não deve esconder o
valor estruturado que ainda é observável.

Uma divergência entre documentos deve manter os valores anotados em seus
respectivos documentos e pode receber um `Finding` com as evidências das duas
ocorrências. Nunca escolher silenciosamente a versão “mais provável”.

## Metadados fora do payload

O schema não comporta metadados de avaliação. O recorte de escopo do processo
é validado externamente por
[`corpus_process.v0.1.0.json`](../schemas/corpus_process.v0.1.0.json), com
exemplos em [`schemas/examples/`](../schemas/examples/). Metadados específicos
de anotação podem complementar esse registro em CSV ou JSON sob `r4/` e devem
manter, no mínimo:

- `process_id`, `split` (`dev` ou `eval`), perfil
  `PUBLICO_14133_PREGAO_ELETRONICO_BENS`, esfera `M` e IDs de ETP/TR;
- URL/canal e SHA-256 de cada original imutável;
- policy `4-municipal-historical-ocr` e, quando houver OCR, idioma,
  versão/configuração, hash e proveniência do artefato derivado;
- anotador(es), data da primeira anotação, estado da revisão A/B, decisão de
  adjudicação e IDs das evidências em desacordo.

O cache de OCR para qualquer arquivo usa `SHA-256 do original + idioma +
versão/configuração`; nunca sobrescreve o original. O manifesto deve
referenciar o `id` do payload e não duplicar seus fatos. Assim, adicionar
`split`, `profile`, `esfera`, `hash`, `ocr`, `reviewer`, `annotation_status` ou
`source_url` à raiz do JSON torna o arquivo incompatível com
`additionalProperties: false`.
