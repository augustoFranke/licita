# Catálogo de Regras Determinísticas do TR Linter (v1.1) — Compras de Bens Comuns

Catálogo versionado da R8. Aplica-se **somente** a Termo de Referência de aquisição de bens comuns no perfil `Lei 14.133/2021 + IN SEGES/ME nº 81/2022 + modelo AGU de TR para Compras (dez/2025)`.

Este arquivo é especificação de implementação, não parecer jurídico. Finding é **achado/risco para revisão humana**. Nunca “ilegal”, “reprovado” ou “aprovado”.

Testes: `rules_synthetic_tests.md`.

---

## 1. Como ler este catálogo

Cada regra tem, obrigatoriamente:

| Campo | Função |
|---|---|
| `rule_id` | Identificador estável |
| `descricao` | O que o achado comunica ao revisor |
| `escopo` | Quando a regra roda e quando não roda |
| `fundamento` | Fonte normativa explícita. Nenhuma regra sem fonte. |
| `severidade` | `HIGH` ou `MED` (v1 não usa `LOW`) |
| `entrada` | Sobre o que a função opera |
| `funcao_de_deteccao` | Predicado determinístico |
| `nao_dispara` | Guardas de falso positivo |
| `finding` | Formato do achado |
| `testes` | IDs em `rules_synthetic_tests.md` |

Se o predicado depender de equivalência semântica sem campo extraído, a checagem **não pertence a este catálogo** — vai para a R9.

---

## 2. Política de severidade

| Nível | Uso na v1 |
|---|---|
| `HIGH` | Omissão ou contradição que impede executar, receber ou julgar o objeto de forma objetiva. |
| `MED` | Requisito objetivamente aferível sem método de comprovação. O TR continua executável, mas a verificação fica indefinida. |

A v1 **não** emite veredito sobre o processo. Severidade ordena revisão; não classifica legalidade.

---

## 3. Entrada comum e convenções

### 3.1 Entrada preferencial

A função de detecção opera sobre o TR já estruturado (R2/R5), não sobre o PDF cru:

- `Section` (título normalizado, corpo, evidência)
- `Item` (identificador, descrição)
- `FieldValue` (tipo, valor, unidade, item, evidência)
- `Requirement` (atributo, operador, valor, unidade, item, evidência)

Texto original permanece só como evidência. Se um campo exigido pela regra não puder ser representado sem voltar ao texto livre, a regra ainda não está pronta — isso é gate da R2, não da R8.

### 3.2 Normalização

Antes de comparar:

- casefold; remover acentos; colapsar whitespace
- títulos: remover numeração inicial (`1.`, `1.1`, `Capítulo I`, `Seção 4`, `Item 1 -`)
- anexos: `Anexo III` = `Anexo 3` = `ANEXO III`; `Apêndice A` ≠ `Anexo A`
- duração: `1 ano` = `12 meses`; `15 (quinze) dias corridos` = `15 dias corridos`
- `dias úteis` e `dias corridos` **não** são a mesma unidade
- item: `Item 1`, `item 01`, `lote 1` só são o mesmo se o extrator os tiver ligado ao mesmo `item_id`

### 3.3 Formato do finding

```text
rule_id: RULE-00X
severity: HIGH | MED
message: <achado, uma frase, sem juízo de ilegalidade>
evidence: [<trechos com seção/página>]
item_id: <se aplicável>
attrs: { ... }          # valores comparados, seções ausentes, âncora do anexo, etc.
```

---

## 4. Elementos descritivos (RULE-001)

Checklist da v1 = **IN 81/2022, art. 9º, I a X**, não o art. 40, § 1º, da Lei 14.133 (esse parágrafo é planejamento de compras, não a lista de seções do TR).

| `element_id` | Conteúdo exigido | Títulos aceitos (não exaustivo) |
|---|---|---|
| `objeto` | definição do objeto | definição do objeto; do objeto; objeto; descrição do objeto |
| `fundamentacao` | fundamentação da contratação | fundamentação da contratação; fundamentação; justificativa; da justificativa |
| `solucao` | descrição da solução como um todo | descrição da solução como um todo; da solução; solução como um todo |
| `requisitos` | requisitos da contratação | requisitos da contratação; requisitos; especificações da contratação |
| `execucao` | modelo de execução do objeto | modelo de execução do objeto; da execução; execução do objeto |
| `gestao` | modelo de gestão do contrato | modelo de gestão do contrato; da gestão; gestão do contrato; fiscalização |
| `medicao_pagamento` | critérios de medição e de pagamento | critérios de medição e de pagamento; medição e pagamento; do pagamento |
| `selecao` | forma e critérios de seleção do fornecedor | forma e critérios de seleção do fornecedor; seleção do fornecedor; critério de julgamento |
| `estimativa` | estimativas do valor da contratação | estimativas do valor da contratação; valor da contratação; estimativa de preços; do valor estimado |
| `adequacao_orcamentaria` | adequação orçamentária | adequação orçamentária; da dotação; dotação orçamentária |

Corpo vazio ou só placeholder (`....`, `XXXX`, `a preencher`) conta como elemento **ausente**.

**Exceção normativa:** `adequacao_orcamentaria` **não** é exigida quando o TR é de sistema de registro de preços (IN 81/2022, art. 9º, X). SRP se o documento afirma SRP / ata de registro de preços / sistema de registro de preços.

Garantia, locais de entrega e recebimento **não** são seções autônomas nesta regra. São conteúdo de `objeto` / `execucao` / `gestao` / `medicao_pagamento` e têm regras próprias (003, 004, 005).

---

## 5. Regras

### RULE-001

- **rule_id**: RULE-001
- **descricao**: Seção descritiva obrigatória ausente ou sem conteúdo no TR.
- **escopo**: Todo TR `SUPPORTED`. Não avalia qualidade do texto, só presença do elemento. Não exige a numeração 1–10 do modelo AGU.
- **fundamento**: Lei nº 14.133/2021, art. 6º, XXIII; IN SEGES/ME nº 81/2022, art. 9º, caput e incisos I a X (exceção do inciso X para SRP); modelo AGU de TR para Compras (dez/2025) como referência de estrutura, não como fonte autônoma de obrigatoriedade.
- **severidade**: HIGH
- **entrada**: lista de `Section` do TR; flag `is_srp`.
- **funcao_de_deteccao**:
  1. Normalizar títulos e casar com a tabela da § 4.
  2. Um `element_id` está presente se existe seção casada **e** o corpo tem texto não-placeholder.
  3. Se `is_srp`, ignorar `adequacao_orcamentaria`.
  4. Disparar **um finding por** `element_id` ausente.
- **nao_dispara**: título equivalente na tabela; SRP sem dotação; conteúdo do elemento em seção com título não canônico **já casado por alias**. Não infere elemento só porque uma palavra aparece no objeto (`"pagamento"` no meio da justificativa não preenche `medicao_pagamento`).
- **finding**: `attrs.missing = [element_id, ...]`. Evidência: título mais próximo ou trecho em que o elemento deveria estar.
- **testes**: 001-D1, 001-D2, 001-N1, 001-N2, 001-N3

---

### RULE-002

- **rule_id**: RULE-002
- **descricao**: Item ou lote sem quantidade numérica estimada ou sem unidade de fornecimento.
- **escopo**: Cada `Item` extraído do TR. Não roda se o TR não tiver item identificável (isso é falha de extração ou RULE-001 em `objeto`, não desta regra).
- **fundamento**: Lei nº 14.133/2021, art. 6º, XXIII, a (quantitativos no TR) e art. 40, III (unidades e quantidades a adquirir); IN SEGES/ME nº 81/2022, art. 9º, I, a e b.
- **severidade**: HIGH
- **entrada**: `Item[]` com `FieldValue` de `quantidade` e `unidade`.
- **funcao_de_deteccao**:
  1. Para cada item, ler quantidade e unidade (tabela, prosa ou campo extraído).
  2. Quantidade válida = número finito > 0 (aceitar `1.200`, `1200`, `1.200,5`). Inválida: célula vazia, `—`, `a definir`, `conforme demanda`, `xx`, 0, não numérico.
  3. Unidade válida = token de unidade de fornecimento (`unidade`, `un`, `resma`, `caixa`, `kg`, `l`, etc.) ligado ao item. Embalagem na descrição (`resma com 500 folhas`) **não** substitui a quantidade de unidades demandadas.
  4. Disparar por item, com `attrs.falta = quantidade | unidade | ambas`.
- **nao_dispara**: quantidade só em prosa (`Aquisição de 50 cadeiras`); unidade implícita canônica já extraída (`50 cadeiras` → qtd 50, un `unidade`); valores de referência monetários sem serem quantidade.
- **finding**: evidência da linha/trecho do item.
- **testes**: 002-D1, 002-D2, 002-D3, 002-N1, 002-N2

---

### RULE-003

- **rule_id**: RULE-003
- **descricao**: Prazo determinado de entrega/fornecimento dos bens ausente.
- **escopo**: Todo TR de bens comuns. **Só prazo de entrega.** Prazo de vigência contratual é outro campo (`FieldValue.prazo_vigencia`) e fica para regra futura — misturá-los gera falso negativo (`vigência 12 meses` não é prazo de fornecimento).
- **fundamento**: Lei nº 14.133/2021, art. 6º, XXIII, a e e; IN SEGES/ME nº 81/2022, art. 9º, I, a e V. Modelo AGU de TR para Compras, seção de execução / prazo de entrega.
- **severidade**: HIGH
- **entrada**: `FieldValue` tipo `prazo_entrega`; seções `execucao` e `objeto`.
- **funcao_de_deteccao**:
  1. Há prazo determinado se existe duração numérica (`N dias úteis|corridos`, `N horas`) **ou** data certa **ou** cláusula explícita de entrega imediata/pronta entrega.
  2. Não é prazo determinado: `após a nota de empenho`, `após a ordem de fornecimento`, `quando solicitado`, `em tempo hábil`, sem N.
  3. Disparar **um** finding para o TR se nenhum item/objeto tem prazo determinado. Se prazos são por item, disparar só nos itens sem prazo.
- **nao_dispara**: `15 (quinze) dias corridos`; `10 dias úteis`; `entrega imediata`; prazo só de vigência **não** conta como entrega (e portanto **dispara** se for a única menção temporal).
- **finding**: evidência do trecho de execução que fala em entregar sem N, ou da ausência da seção.
- **testes**: 003-D1, 003-D2, 003-N1, 003-N2

---

### RULE-004

- **rule_id**: RULE-004
- **descricao**: Prazo ou condição de garantia técnica citado de forma contraditória no próprio TR.
- **escopo**: Só **contradição interna**. Não exige garantia: IN 81/2022, art. 9º, I, d, é “quando for o caso”. Garantia mencionada uma vez, ou não mencionada, não dispara.
- **fundamento**: Lei nº 14.133/2021, art. 6º, XXIII, d; IN SEGES/ME nº 81/2022, art. 9º, I, d. A contradição é achado de integridade do TR como especificação, não um tipo legal autônomo.
- **severidade**: HIGH
- **entrada**: `FieldValue` tipo `garantia` (duração, marco inicial, on-site/balcão) por `item_id` ou, se omitido, pelo objeto global.
- **funcao_de_deteccao**:
  1. Agrupar menções de garantia pelo mesmo `item_id` (ou pelo objeto, se não houver item).
  2. Normalizar duração para meses.
  3. Conflito se duas durações numéricas diferem, **ou** dois marcos iniciais incompatíveis (`a partir da entrega` vs `a partir do recebimento definitivo` só é conflito se ambos forem apresentados como o único termo inicial, não como sequência), **ou** modalidades incompatíveis para o mesmo período (`on-site` vs `balcão` como única forma).
  4. `mínima de 12 meses` na especificação e `12 meses contados do recebimento definitivo` na execução = **consistente** (piso + termo inicial).
  5. Garantia legal do CDC ao lado de garantia contratual maior = **não** conflito.
- **nao_dispara**: uma única menção; 12 vs 12; 1 ano vs 12 meses; detalhamento que não altera a duração.
- **finding**: os **dois** trechos. `attrs.left`, `attrs.right`.
- **testes**: 004-D1, 004-D2, 004-N1, 004-N2, 004-N3

---

### RULE-005

- **rule_id**: RULE-005
- **descricao**: Recebimento provisório e/ou definitivo dos bens não definido.
- **escopo**: Todo TR de compras. Exige os **dois** ritos do art. 140, II, não um deles, não a mera citação do artigo.
- **fundamento**: Lei nº 14.133/2021, art. 140, II, a e b, e art. 6º, XXIII (regras para recebimentos provisório e definitivo, quando for o caso); IN SEGES/ME nº 81/2022, art. 9º, I, c; modelo AGU de TR para Compras, subseção Recebimento (em Critérios de Medição e de Pagamento).
- **severidade**: HIGH
- **entrada**: seções `gestao` e `medicao_pagamento` (o modelo AGU coloca o rito em medição/pagamento; aceitar qualquer uma).
- **funcao_de_deteccao**:
  1. `provisorio_ok` se o TR distingue recebimento provisório de compras (forma sumária / verificação posterior da conformidade) **e** indica responsável ou momento (ato da entrega ou prazo).
  2. `definitivo_ok` se distingue recebimento definitivo **e** indica responsável (servidor ou comissão) **e** termo detalhado ou prazo para esse ateste.
  3. Disparar se falta um dos dois. `attrs.falta = provisório | definitivo | ambos`.
- **nao_dispara**: os dois ritos descritos, ainda que os prazos concretos estejam em placeholder numérico (`XXXX dias úteis`) — placeholder de prazo não é ausência do rito. (Placeholder de seção inteira é RULE-001.)
- **nao_dispara também**: nomear fiscal ou dizer que o pagamento segue a NF, isoladamente.
- **finding**: evidência do trecho de gestão/pagamento onde o rito deveria estar.
- **testes**: 005-D1, 005-D2, 005-D3, 005-N1

---

### RULE-006

- **rule_id**: RULE-006
- **descricao**: TR remete a anexo/apêndice **deste** TR que não está no documento.
- **escopo**: Somente referências que afirmam fazer parte do próprio TR (`deste Termo de Referência`, `anexo I`, `apêndice B` como peça do TR). Não resolve anexos de edital, ETP ou contrato — isso é consistência entre documentos (R7).
- **fundamento**: Lei nº 14.133/2021, art. 6º, XXIII, e IN SEGES/ME nº 81/2022, art. 9º: se o TR desloca elemento descritivo para anexo, o anexo é parte do TR. Sem o anexo, o elemento não está no documento. Não há inciso específico “anexo citado deve existir”; a regra é de integridade documental necessária àqueles artigos.
- **severidade**: HIGH
- **entrada**: texto do TR + headings/blocos de anexo no **mesmo** arquivo.
- **funcao_de_deteccao**:
  1. Extrair âncoras (`Anexo I`, `Anexo 3`, `Apêndice A`).
  2. Ignorar referências explícitas a outro instrumento (`anexo do edital`, `anexo do ETP`, `anexo da ata`).
  3. Resolver contra títulos/blocos no final do TR (`# ANEXO I`, `Anexo I — ...`). Romanos = arábicos.
  4. Disparar uma vez por âncora não resolvida.
- **nao_dispara**: `Anexo III` citado e `ANEXO 3` presente; menção genérica `anexos, se houver` sem número; referência extra-TR explícita.
- **finding**: âncora + evidência da citação. `attrs.anchor = "III"`.
- **testes**: 006-D1, 006-N1, 006-N2, 006-N3

---

### RULE-007

- **rule_id**: RULE-007
- **descricao**: O mesmo item tem, em seções distintas do TR, valores incompatíveis para o mesmo atributo extraído.
- **escopo**: Contradição **estruturada** no próprio TR. Compara `Requirement` / `FieldValue` já extraídos. Contradição só no prosaico, sem campos, é R9.
- **fundamento**: Lei nº 14.133/2021, art. 6º, XXIII, a, e art. 40, V, a (compatibilidade de especificações); IN SEGES/ME nº 81/2022, art. 9º, I, b.
- **severidade**: HIGH
- **entrada**: `Requirement` e `FieldValue` com `item_id` e `atributo`.
- **funcao_de_deteccao**:
  1. Agrupar por `(item_id, atributo)` — material, tipo construtivo, dimensão, CATMAT, voltagem, capacidade, quantidade de componentes, marca **vinculante**.
  2. Disparar se dois valores, depois de normalizados, não podem ser verdadeiros ao mesmo tempo (aço vs MDF; 4 vs 3 gavetas; 220 V vs 110 V; CATMAT distintos; coluna vs mesa).
  3. Não disparar se B **refina** A (`aço nº 24` vs `aço nº 24 com pintura eletrostática`; `50 litros` vs `reservatório de 50 litros`).
  4. Não comparar itens distintos. Marca “de referência, admitidas equivalentes” não conflita com ausência de marca na outra seção.
- **nao_dispara**: detalhamento compatível; atributos diferentes (`cor` vs `material`); item 1 vs item 2.
- **finding**: os dois trechos, `item_id`, `atributo`, valores.
- **testes**: 007-D1, 007-D2, 007-N1, 007-N2

---

### RULE-008

- **rule_id**: RULE-008
- **descricao**: Requisito técnico objetivamente aferível sem critério, documento ou método de comprovação.
- **escopo**: Só requisito **objetivamente verificável** que funciona como filtro de proposta/habilitação/recebimento. Especificação ordinária do bem (cor, formato, quantidade de gavetas, gramatura descritiva) **não** entra — confere-se no recebimento (RULE-005). Expressões vagas (`alta qualidade`, `bom desempenho`) são R9, não esta regra.
- **fundamento**: Lei nº 14.133/2021, art. 42 (meios de prova de qualidade do produto) e art. 41, II (amostra / prova de conceito, se a Administração as exigir); IN SEGES/ME nº 81/2022, art. 9º, IV e V. **Não** usar art. 67, II (qualificação técnico-operacional de serviços).
- **severidade**: MED
- **entrada**: `Requirement` do TR.
- **funcao_de_deteccao**:
  1. O requisito é *aferível* se o valor extraído casa com a allowlist da v1:
     - norma nomeada (ABNT, NBR, ISO, IEC, INMETRO) como desempenho/conformidade, não como mera menção bibliográfica
     - certificação (CA/MTE, FSC, Cerflor, certificação compulsória)
     - métrica de ensaio (Joules, SRC, UPF/UV fator N, classe de inflamabilidade, IP, índice de proteção)
  2. Há critério relacionado se o mesmo item (ou a seção de requisitos/seleção) aponta pelo menos um: laudo de laboratório, certificado nomeado, CA, ensaio/norma de ensaio como método, amostra/prova de conceito, ou “comprovação na proposta/habilitação/recebimento” ligada a documento idôneo.
  3. Disparar se (1) e não (2).
- **nao_dispara**: requisito aferível com método; especificação descritiva comum; ambiguidade sem métrica (R9); método genérico demais só se **não** houver item na allowlist.
- **finding**: o requisito e a ausência de método. Evidência = trecho do requisito.
- **testes**: 008-D1, 008-D2, 008-N1, 008-N2, 008-N3

---

## 6. O que este catálogo recusa

- Julgar preço, razoabilidade ou legalidade.
- Inferir seção obrigatória só por similaridade semântica frouxa.
- Tratar vigência como prazo de entrega (RULE-003).
- Exigir garantia onde a IN 81 diz “quando for o caso” (RULE-004).
- Resolver anexo de outro documento da cadeia (RULE-006 vs R7).
- Classificar contradição puramente linguística (RULE-007 vs R9).
- Tratar “alta qualidade” como RULE-008.

Qualquer regra normativa nova precisa de fonte explícita neste arquivo e de testes em `rules_synthetic_tests.md` **antes** de entrar no linter.
