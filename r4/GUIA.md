# R4 — Guia de anotação manual

## Estado deste artefato

Este é o guia e o contrato operacional da R4. O repositório ainda não contém
as 10–15 anotações reais nem a meta de 300 valores/requisitos; o exemplo ao
lado é sintético e não conta para nenhuma meta. A existência deste guia também
não declara a R4 concluída.

A R4 cria uma verdade de referência para avaliar a extração da R5. A anotação
não deve corrigir o documento-fonte, completar lacunas com conhecimento
externo ou transformar interpretação jurídica em fato estruturado.

## 1. Escopo e unidade de trabalho

Anotar apenas processos elegíveis no perfil exclusivo
`MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`: esfera `M`, Lei nº 14.133/2021,
Pregão Eletrônico (`PE`) e aquisição de bens comuns. Nesta rodada a unidade é
exatamente o par ETP→TR da mesma contratação. O controle negativo SAEMA de
energia e qualquer processo `FORA_DO_PERFIL` não entram em R2/R4 nem nas
métricas. Serviços, obras, engenharia, outras modalidades, outras esferas e
regimes especiais ficam fora. Cada processo é uma unidade; nunca dividir ETP
e TR do mesmo processo entre `dev` e `eval`.

A unidade mínima do trabalho é uma afirmação sustentada por uma evidência:

- **item**: linha/lote/produto identificável;
- **valor de campo**: quantidade, prazo, garantia, preço ou local;
- **requisito**: característica, limite, condição ou obrigação;
- **evidência**: âncora navegável ao texto original;
- **achado**: conflito ou incerteza que não deve ser resolvido por suposição.

A especificação técnica e as regras de serialização estão em
[`FORMATO.md`](FORMATO.md). O formato normativo é o schema atual
`procurement_process.v0.1.0.json`, não um wrapper de anotação.

## 2. Princípios de anotação

1. **Fonte primeiro.** Ler o bloco original antes de normalizar. Não usar
   catálogo, memória, pesquisa externa ou inferência para preencher o payload.
2. **Uma afirmação, um registro.** Separe fatos com valores, unidades, papéis
   ou condições diferentes. Não esconda duas quantidades em uma string.
3. **Preservar multiplicidade.** A mesma afirmação em TR, edital e contrato é
   uma ocorrência em cada documento, com a sua própria evidência. No mesmo
   documento, evidências que sustentam o mesmo fato podem compartilhar um
   registro.
4. **Normalização sem perda.** `value`, `unit`, `operator` e `attribute` são
   a representação comparável; `Evidence.quote` conserva a redação que
   permite auditá-la.
5. **Não inferir ausência.** Campo vazio significa “não anotado porque não há
   afirmação explícita”, não “falso”. Só registre `EXISTS: false` quando a
   fonte disser expressamente que algo não existe/não se aplica.
6. **Rastreabilidade total.** Nenhum item, valor, requisito ou achado entra
   sem evidência navegável. Se o trecho não puder ser reaberto, a anotação não
   está pronta.
7. **Conflito visível.** Valores incompatíveis permanecem separados e viram
   achado aberto; não aplicar precedência jurídica silenciosamente.
8. **Revisabilidade.** IDs de processo, documento, seção e bloco são estáveis.
   Uma correção deve mudar a anotação, não reescrever a fonte nem quebrar suas
   referências.

## 3. Passo a passo

### 3.1 Preparar o processo

1. Confirmar no catálogo/manifesto da R1 o processo, perfil, esfera `M`,
   elegibilidade, par ETP/TR e hashes SHA-256 dos originais.
2. Confirmar que os blocos da R3 preservam documento, página, tipo de bloco,
   tabela/parágrafo e texto original. Se houve OCR, conferir no manifesto o
   hash original, idioma, versão/configuração, hash e proveniência do artefato
   derivado.
3. Escolher um ID estável e separar o processo no split previamente definido.
4. Não começar a anotar se um documento ou página necessária estiver ilegível;
   registrar a pendência para não converter erro de ingestão em rótulo negativo.

### 3.2 Anotar documentos e seções

Para cada um dos dois documentos elegíveis do lote, ETP e TR:

1. Criar `Document` com tipo e formato corretos.
2. Reproduzir as seções relevantes, mantendo `title_original` literal.
3. Incluir os blocos necessários para a navegação das evidências. O bloco não
   é um resumo: `text` é o texto original ingerido.
4. Usar `section_type_normalized` apenas para facilitar agrupamento (`ITEMS`,
   `TECHNICAL`, `EXECUTION`, `RECEIPT`, `MEASUREMENT`, `PAYMENT`, `WARRANTY`,
   `PRICE` etc.).
5. Dar a cada seção uma evidência própria. Essa evidência pode apontar para
   um bloco de cabeçalho ou para o primeiro bloco da seção.

Não duplicar blocos para fazer uma citação caber. Se uma citação depende de
uma célula de tabela e de seu cabeçalho, preserve os dois blocos e use duas
Evidence no mesmo registro.

### 3.3 Anotar itens e campos

1. Identificar cada linha/lote e criar o `Item` com descrição curta.
2. Marcar a ocorrência da quantidade com `QUANTITY`, sempre como número
   positivo; registrar unidade somente quando declarada ou normalizada segundo
   a política do formato.
3. Marcar prazos como números + unidade quando forem durações (`30` +
   `dias_corridos`, por exemplo). Datas explícitas devem permanecer datas ISO.
4. Marcar garantia separadamente de prazo de entrega e vigência contratual.
5. Marcar preço unitário e total separadamente; normalizar decimal e usar
   `BRL`, sem símbolo ou separador de milhar em `value`.
6. Marcar local de entrega como `DELIVERY_LOCATION`; não derivar o local de um
   endereço de outro documento.
7. Se a fonte repete um valor, conservar cada ocorrência relevante por
   documento. Se há dois papéis para o mesmo número (por exemplo, quantidade
   estimada e quantidade máxima), criar registros distintos e registrar a
   qualificação como requisito/achado quando o schema não tiver um papel
   próprio.

### 3.4 Anotar requisitos técnicos

Para toda especificação verificável, registrar `attribute`, `operator`, `value`
e `unit` quando aplicável. Exemplos de decisões:

- “faixa de 0 a 50 °C” → `BETWEEN`, `[0, 50]`, `°C`;
- “precisão máxima de 0,5 °C” → `LESS_THAN_OR_EQUAL`, `0.5`, `°C`;
- “LoRaWAN ou Wi-Fi” → `IN`, `["LoRaWAN", "Wi-Fi"]`;
- “não inclui instalação” → `execution.installation_included`, `EQUAL`,
  `false`, somente porque a negação está explícita;
- “possuir manual” → `execution.documentation`, `EXISTS`, `true`, quando a
  obrigação estiver explícita.

Não transformar adjetivo comercial (“alta qualidade”) em requisito mensurável
sem critério na fonte. Uma especificação sem forma comparável pode ser um
`CONTAINS` curto, desde que o trecho completo fique na evidência; se ainda
assim a semântica se perder, registrar a limitação como achado.

### 3.5 Anotar execução, recebimento, medição e pagamento

Esses quatro temas são obrigatórios na leitura da R4, inclusive quando só
aparecem em cláusulas corridas. O schema `0.1.0` não possui objetos próprios
para eles:

- **Execução:** procedimentos de entrega, embalagem, instalação, manuais,
  fiscalização e obrigações vão em `Requirement` com prefixo `execution.`;
  prazo e local continuam em `FieldValue`.
- **Recebimento:** marcar existência e modalidade provisória/definitiva,
  critérios de aceite, rejeição e correção com `receipt.*`; prazo de
  recebimento vai em `RECEIPT_DEADLINE`.
- **Medição:** registrar a unidade/base de medição, critério de conformidade e
  documento de aceite com `measurement.*`. Não inventar uma medição apenas
  porque o contrato usa a palavra “atesto”.
- **Pagamento:** registrar gatilho, condição, documento exigido e sequência
  com `payment.*`; prazo vai em `PAYMENT_DEADLINE`.

Se um desses temas não aparecer, não criar um valor fictício. Se aparecer uma
negação explícita, use `EXISTS: false` ou a comparação apropriada. Se uma
cláusula contiver várias condições independentes, separe-as para que cada uma
tenha uma evidência auditável.

### 3.6 Fechar e validar

Antes de submeter uma anotação:

- cada documento tem tipo/formato válidos e ID único;
- cada bloco citado existe no documento certo e tem ID globalmente único;
- cada `quote` é substring literal do bloco citado;
- cada item tem evidência;
- cada `FieldValue` e `Requirement` tem ao menos uma evidência;
- `item_id` em nível de documento existe naquele documento e em nível de item
  coincide com o pai;
- quantidades são numéricas, positivas e não estão em string;
- `BETWEEN` tem exatamente dois limites ordenados; `IN` não é vazio;
- nenhuma propriedade de revisão, split ou metadado foi inserida no payload.

Valide tanto o JSON quanto o modelo Pydantic atual, por exemplo:

```bash
uv run python -m json.tool r4/exemplo_processo_sintetico.json >/dev/null
PYTHONPATH=src uv run python -m licita_core.r2_annotations \
  r4/exemplo_processo_sintetico.json
```

O segundo comando deve produzir cobertura e `valid: true` para o exemplo. A
cobertura exibida é diagnóstico de campos representados; ela não é o gate da
R2, não prova que há 300 anotações e não declara a R4 concluída.

## 4. Política de ambiguidades

A anotação deve tornar a dúvida observável, não escondê-la. Aplicar estas
regras em ordem:

| Situação | Decisão obrigatória |
| --- | --- |
| Campo simplesmente não aparece | Não criar `FieldValue`; não converter ausência em `false`. Registrar a ausência no controle externo se ela for necessária para medir recall. |
| Fonte diz “não se aplica”, “não possui” ou equivalente | Criar requisito explícito, normalmente `attribute: <tema>.exists`, `operator: EXISTS`, `value: false`, com evidência. |
| Número sem unidade | Anotar o número se o campo estiver claro, deixar `unit: null` e abrir achado de unidade ausente. Não escolher “unidade” por hábito. |
| “A definir”, “conforme demanda” ou valor ilegível | Não inventar `value`; preservar a citação e abrir achado de valor não resolvido. |
| ETP e TR divergem | Anotar cada ocorrência no documento de origem e abrir `Finding` com todas as evidências. A precedência é uma decisão de revisão, não do anotador. |
| Duas quantidades têm papéis diferentes | Manter um registro por papel/citação. Se `0.1.0` não consegue codificar o papel, registrar a limitação em `Finding.attrs` sem descartar os números. |
| Condição ou exceção complexa não cabe no atributo/operador | Estruturar a parte segura, não afirmar equivalência; abrir achado de representação insuficiente com a citação completa. |
| OCR, tabela quebrada ou página não navegável | Não corrigir pela aparência nem alterar o original. OCR pode ser refeito para qualquer arquivo e cacheado por SHA-256 original + idioma + versão/configuração; o resultado é derivado auditável. Sem âncora válida, solicitar correção da ingestão ou marcar achado. |
| Item ou linha não pode ser separado | Não criar itens imaginários. Manter a evidência conjunta e registrar a ambiguidade para adjudicação. |
| Repetição literal no mesmo documento | Um registro pode conter várias evidências se o valor é a mesma afirmação; não contar cópias como requisitos diferentes. |

`Finding.status` começa em `OPEN`. `UNDER_REVIEW`, `RESOLVED`, `ACCEPTED_RISK`
e `FALSE_POSITIVE` descrevem a decisão de revisão (`FR-081`), não um veredito
sobre o mérito da licitação. Severidade: `HIGH` | `MEDIUM` | `INFO`. O texto
do achado deve dizer qual é a dúvida e apontar para as ocorrências, sem usar
“aprovado” ou “reprovado”.

## 5. Divisão desenvolvimento/avaliação

A divisão deve ser feita antes da extração da R5 e por **processo**, não por
documento ou por página:

1. Colocar ETP, TR, anexos incorporados e versões copiadas do mesmo processo
   em um único grupo; o payload elegível desta rodada contém exatamente ETP/TR.
2. Agrupar também documentos reutilizados ou duplicados identificados por hash;
   nenhum texto-fonte ou cópia quase idêntica pode atravessar os splits.
3. Usar `dev` para ajustar política, normalização, regras e prompts. `eval` é
   congelado, não é lido durante o desenvolvimento e só é aberto para o
   cálculo final.
4. Reservar uma parcela de avaliação que contenha processos inteiros e
   variedade de órgãos/categorias sem permitir vazamento. A meta do plano é
   10–15 processos reais no total; este repositório ainda não afirma possuir
   essa amostra.
5. Guardar o split em manifesto/catálogo externo com `process_id`, perfil,
   esfera `M`, hashes dos originais, versão da policy
   `4-municipal-historical-ocr`, data do congelamento e, quando aplicável,
   idioma, versão/configuração e hash do artefato OCR; não inserir esses campos
   no JSON do schema.

Relatar separadamente erros de ingestão, falhas de normalização e falhas de
localização da evidência. Um processo do `eval` não pode ser movido para
`dev` depois que uma regra foi ajustada por causa dele.

## 6. Dupla revisão manual

Cada processo real passa por duas leituras independentes e consecutivas:

### Leitura A — anotação

O anotador A percorre todos os documentos, cria os itens/campos/requisitos,
marca todas as evidências e abre achados quando a política não resolve a
situação. Deve verificar a lista de cobertura: itens, quantidade, requisitos
técnicos, prazos, garantia, execução, recebimento, medição e pagamento.

### Leitura B — reprodução independente

O anotador B recebe a mesma fonte e a versão da política, mas não o payload de
A. Reanota ou audita de forma cega: procura valores omitidos, valores
inventados, operadores errados, unidade/papel perdido, conflitos não marcados
e quotes que não são substrings. A conferência não pode ser apenas uma leitura
superficial do JSON de A.

### Comparação e adjudicação

1. Comparar conjuntos de itens, valores, requisitos e evidências por documento.
2. Classificar cada diferença como omissão, inclusão indevida, normalização,
   escopo, evidência, ID ou ambiguidade de política.
3. Resolver por consenso de A/B; se houver desacordo, um terceiro adjudica com
   a fonte aberta. Nunca apagar a ocorrência conflitante sem deixar o motivo
   no registro externo de revisão.
4. Atualizar a política quando a divergência revela um caso não coberto;
   reabrir os casos afetados, inclusive os já revisados.
5. Só marcar o processo como revisado quando a segunda leitura não encontrar
   ambiguidade sem regra, todas as evidências forem navegáveis e o JSON passar
   no schema.

O registro de revisão fica fora do `ProcurementProcess` e deve guardar versão
da política, revisores, data, decisão, diferenças e adjudicação. Perfil,
esfera, hashes e metadados de OCR também ficam no manifesto/catálogo externo.
Isso mantém o payload fechado, sem campos de esfera, e compatível com
`additionalProperties: false`, além de tornar a auditoria repetível.

## 7. Gate específico da R4

O gate não é “o exemplo valida”. Para a amostra real, exigir:

- a quantidade de processos elegíveis definida pelo plano, sem contar o
  exemplo sintético, o controle negativo SAEMA ou qualquer `FORA_DO_PERFIL`;
- cobertura dos temas pedidos pela R4 e pelo menos 300 valores/requisitos
  **somente quando essa contagem tiver sido realmente medida**;
- duas leituras independentes concluídas;
- nenhuma ambiguidade recorrente sem regra documentada;
- 100% das anotações estruturadas com evidência navegável;
- separação `dev`/`eval` congelada e sem vazamento;
- validação do JSON e do modelo atual para cada arquivo.

Este diretório fornece a política, o formato e um caso de teste sintético. Ele
não fornece a amostra real, não mede 300 anotações e não autoriza declarar o
gate atendido.
