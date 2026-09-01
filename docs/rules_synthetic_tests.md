# Testes Sintéticos Municipais do TR Linter — Compras de Bens Comuns

Casos para os seis controles `NORMATIVE` e os dois controles `ADVISORY` de `rules_draft.md`. Todos usam o perfil `PUBLICO_14133_PREGAO_ELETRONICO_BENS`. Finding é achado, não veredito; não usar “aprovado” ou “reprovado”.

A base vinculante dos casos normativos é somente a Lei nº 14.133/2021 aplicável aos Municípios. IN SEGES/ME nº 81/2022, modelos AGU e TR Digital são `REFERENCE_ONLY`; não participam dos oráculos de `SUPPORTED`, `finding` ou `silencio`.

---

## Harness

Cada caso declara:

| Campo | Valor |
|---|---|
| `id` | estável (`001-D1`) |
| `profile_id` | `PUBLICO_14133_PREGAO_ELETRONICO_BENS` |
| `rule_id` | controle sob teste |
| `rule_class` | `NORMATIVE` ou `ADVISORY` |
| `aplica_regras` | lista fechada; snippets parciais não rodam controles omitidos |
| `esperado` | `finding` para `NORMATIVE`; `advisory` para `ADVISORY`; ou `silencio` |
| `attrs` | conteúdo esperado, se houver evento |
| `package_files` | opcional; arquivos disponíveis para resolução de anexos |

`D` = detecta evento; `N` = silêncio do controle. O ID histórico `001-N3` é a única exceção nominal: foi preservado, mas agora espera `finding` no perfil-base, pois SRP não produz exceção universal. `SUPPORTED` é pré-condição dada pelo `profile_id`, nunca resultado da presença de referência federal.

O fixture `TR-MINIMO` é a base de regressão cruzada. Com a lista completa abaixo, espera-se silêncio total. Mutações só rodam os controles listados em `aplica_regras`.

---

## Fixture — TR-MINIMO

Documento sintético municipal que satisfaz todos os controles.

```markdown
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
1.1. Aquisição de cadeiras giratórias ergonômicas para escritório, por pregão eletrônico, com fornecimento único e prazo contratual de 60 dias.
Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios e apoio de braços.
Unidade de fornecimento: unidade.
Quantidade estimada: 50.

## 2. FUNDAMENTAÇÃO DA CONTRATAÇÃO
2.1. A contratação atende à necessidade descrita no ETP municipal nº 12/2024.

## 3. DESCRIÇÃO DA SOLUÇÃO COMO UM TODO
3.1. Fornecimento, entrega, montagem e garantia on-site do Item 1, considerados transporte, uso e descarte ao fim da vida útil.

## 4. REQUISITOS DA CONTRATAÇÃO
4.1. Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios, apoio de braços e capacidade mínima de 110 kg.
4.2. Garantia técnica on-site prestada pela contratada por 12 (doze) meses contados do recebimento definitivo.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Prazo de entrega: 15 (quinze) dias corridos, contados do recebimento da Nota de Empenho.
5.2. Local: Almoxarifado Municipal, na sede do Município/UF.

## 6. MODELO DE GESTÃO DO CONTRATO
6.1. Fiscalização por servidor municipal designado.

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
7.1. Recebimento:
a) provisório, de forma sumária, no ato da entrega, pelo fiscal, para posterior verificação de conformidade;
b) definitivo, em até 10 (dez) dias úteis após o provisório, por servidor designado, mediante termo detalhado.
7.2. Pagamento em até 10 dias úteis após a liquidação.

## 8. FORMA E CRITÉRIOS DE SELEÇÃO DO FORNECEDOR
8.1. Pregão eletrônico, menor preço por item.

## 9. ESTIMATIVAS DO VALOR DA CONTRATAÇÃO
9.1. Valor total estimado: R$ 35.000,00, conforme memória de cálculo juntada ao processo.

## 10. ADEQUAÇÃO ORÇAMENTÁRIA
10.1. Programa de Trabalho 10.122.0001, Fonte 100, Elemento 339030.
```

```yaml
id: TR-MINIMO
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: ALL
rule_class: [NORMATIVE, ADVISORY]
aplica_regras: [RULE-001, RULE-002, RULE-003, RULE-004, RULE-005, RULE-006, RULE-007, ADVISORY-008]
esperado: silencio
```

---

## RULE-001 — Elemento obrigatório ausente

### 001-D1 — Detecta várias ausências

```yaml
id: 001-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-001
rule_class: NORMATIVE
aplica_regras: [RULE-001]
esperado: finding
attrs.missing: [solucao, requisitos, execucao, gestao, medicao_pagamento, selecao, adequacao_orcamentaria, local_entrega, recebimento]
```

```markdown
# TERMO DE REFERÊNCIA

## 1. DO OBJETO
Aquisição de 100 caixas de papel-toalha interfolhado, com 1.000 folhas por caixa e prazo contratual de 60 dias.

## 2. DA FUNDAMENTAÇÃO
Conforme ETP municipal nº 05/2024.

## 3. DO VALOR ESTIMADO
Custo total estimado: R$ 5.400,00, conforme memória de cálculo do processo.
```

**Motivo:** `objeto`, `fundamentacao`, `estimativa` e a especificação básica do produto estão presentes; os elementos listados não.

### 001-D2 — Detecta título sem conteúdo

```yaml
id: 001-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-001
rule_class: NORMATIVE
aplica_regras: [RULE-001]
esperado: finding
attrs.missing: [execucao, local_entrega]
```

Partir do TR-MINIMO e substituir a seção 5 por:

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
....
```

**Motivo:** heading canônico com corpo placeholder não preenche o elemento nem o local de entrega.

### 001-N1 — Silêncio com os elementos canônicos

```yaml
id: 001-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-001
rule_class: NORMATIVE
aplica_regras: [RULE-001]
esperado: silencio
```

Usar o TR-MINIMO.

### 001-N2 — Silêncio com títulos alias

```yaml
id: 001-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-001
rule_class: NORMATIVE
aplica_regras: [RULE-001]
esperado: silencio
```

```markdown
# TERMO DE REFERÊNCIA

## 1. DO OBJETO
Aquisição de 50 cadeiras giratórias, com prazo contratual de 60 dias. Unidade: unidade. Quantidade: 50.

## 2. DA JUSTIFICATIVA
Conforme ETP municipal nº 12/2024.

## 3. DA SOLUÇÃO
Fornecimento único de mobiliário, incluindo entrega e montagem.

## 4. DOS REQUISITOS
Cadeira giratória, tecido preto, cinco rodízios e apoio de braços. Garantia não exigida, consideradas a padronização e a baixa complexidade do bem.

## 5. DA EXECUÇÃO
Entrega em 15 dias corridos no Almoxarifado Municipal.

## 6. DA GESTÃO
Fiscalização por servidor municipal designado.

## 7. DO PAGAMENTO
Recebimento provisório sumário pelo fiscal no ato da entrega e definitivo por servidor designado, mediante termo detalhado, em 10 dias úteis; pagamento após ateste.

## 8. DA SELEÇÃO
Pregão eletrônico, menor preço.

## 9. DA ESTIMATIVA DE PREÇOS
R$ 35.000,00, conforme memória de cálculo juntada ao processo.

## 10. DA DOTAÇÃO
Programa de Trabalho 10.122.0001, Fonte 100.
```

**Motivo:** a regra casa aliases e conteúdo, não numeração de modelo.

### 001-N3 — ID preservado; agora detecta SRP sem adequação orçamentária

```yaml
id: 001-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-001
rule_class: NORMATIVE
aplica_regras: [RULE-001]
esperado: finding
attrs.missing: [adequacao_orcamentaria]
```

Partir do TR-MINIMO, acrescentar `Contratação por sistema de registro de preços.` ao objeto e remover a seção 10.

**Motivo:** no perfil-base municipal, a simples menção a SRP não afasta `adequacao_orcamentaria`. Apenas overlay municipal futuro, expresso e versionado, poderia alterar o predicado.

---

## RULE-002 — Quantidade ou unidade ausente

### 002-D1 — Detecta prosa sem quantidade demandada

```yaml
id: 002-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-002
rule_class: NORMATIVE
aplica_regras: [RULE-002]
esperado: finding
attrs.falta: quantidade
```

```markdown
## 1. OBJETO
Item 1: Papel sulfite A4, alcalino, branco, 75 g/m², embalagem com 500 folhas (resma), certificado FSC ou Cerflor.
Valor unitário de referência: R$ 26,00.
```

**Motivo:** embalagem não é quantitativo demandado; valor monetário não é quantidade.

### 002-D2 — Detecta célula de quantidade vazia

```yaml
id: 002-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-002
rule_class: NORMATIVE
aplica_regras: [RULE-002]
esperado: finding
attrs.falta: quantidade
```

```markdown
| Item | Descrição | Unidade | Qtd. estimada | Valor unitário |
|---|---|---|---|---|
| 1 | Notebook, 16 GB RAM, SSD 512 GB | Unidade |  | R$ 4.500,00 |
```

### 002-D3 — Detecta quantidade sem unidade

```yaml
id: 002-D3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-002
rule_class: NORMATIVE
aplica_regras: [RULE-002]
esperado: finding
attrs.falta: unidade
```

```markdown
Item 1: Papel sulfite A4, 75 g/m².
Quantidade estimada: 1.200.
Valor unitário de referência: R$ 26,00.
```

### 002-N1 — Silêncio com tabela completa

```yaml
id: 002-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-002
rule_class: NORMATIVE
aplica_regras: [RULE-002]
esperado: silencio
```

```markdown
| Item | Descrição | Unidade | Qtd. estimada | Valor unitário | Valor total |
|---|---|---|---|---|---|
| 1 | Notebook, 16 GB RAM, SSD 512 GB | Unidade | 30 | R$ 4.500,00 | R$ 135.000,00 |
```

### 002-N2 — Silêncio com quantidade em prosa

```yaml
id: 002-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-002
rule_class: NORMATIVE
aplica_regras: [RULE-002]
esperado: silencio
```

```markdown
Aquisição de 50 cadeiras giratórias ergonômicas.
Unidade de fornecimento: unidade. Quantidade estimada: 50.
```

---

## RULE-003 — Prazo de entrega ausente

### 003-D1 — Detecta evento sem duração

```yaml
id: 003-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-003
rule_class: NORMATIVE
aplica_regras: [RULE-003]
esperado: finding
```

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
A contratada entregará os materiais no Almoxarifado Municipal após notificação e recebimento da Nota de Empenho.
```

### 003-D2 — Detecta apenas prazo de vigência

```yaml
id: 003-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-003
rule_class: NORMATIVE
aplica_regras: [RULE-003]
esperado: finding
```

```markdown
## 1. DEFINIÇÃO DO OBJETO
Aquisição de 50 cadeiras. Vigência da contratação: 12 meses.

## 5. MODELO DE EXECUÇÃO DO OBJETO
A contratada entregará os bens mediante ordem de fornecimento.
```

**Motivo:** vigência não substitui prazo de entrega.

### 003-N1 — Silêncio com dias corridos

```yaml
id: 003-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-003
rule_class: NORMATIVE
aplica_regras: [RULE-003]
esperado: silencio
```

```markdown
Entrega no Almoxarifado Municipal em até 15 dias corridos da confirmação do recebimento da Nota de Empenho.
```

### 003-N2 — Silêncio com dias úteis ou pronta entrega

```yaml
id: 003-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-003
rule_class: NORMATIVE
aplica_regras: [RULE-003]
esperado: silencio
```

Dois documentos distintos; ambos devem silenciar:

```markdown
Prazo de entrega: 10 dias úteis, contados da ordem de fornecimento.
```

```markdown
Entrega imediata, no ato da retirada, mediante Nota de Empenho.
```

### 003-N3 — Silêncio no fornecimento sob demanda com prazo definido

```yaml
id: 003-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-003
rule_class: NORMATIVE
aplica_regras: [RULE-003]
esperado: silencio
```

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
O fornecimento será parcelado, sob demanda, durante a vigência. Cada parcela deverá ser entregue no Almoxarifado Municipal em até 5 (cinco) dias úteis do recebimento da respectiva ordem de fornecimento.
```

**Motivo:** cada demanda tem prazo determinado; a vigência apenas delimita o período global.

---

## RULE-004 — Mesma garantia contraditória

### 004-D1 — Detecta 12 vs 36 meses para a mesma garantia e sujeito

```yaml
id: 004-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-004
rule_class: NORMATIVE
aplica_regras: [RULE-004]
esperado: finding
attrs.guarantee_key: item-1/contratada/garantia-tecnica-integral
```

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
A garantia técnica integral do Item 1 (ar-condicionado split 18.000 BTUs), prestada pela contratada, será de 12 meses.

## 5. MODELO DE EXECUÇÃO DO OBJETO
Para o mesmo Item 1, a garantia técnica integral prestada pela contratada contra defeitos será de 36 meses a partir do recebimento definitivo.
```

**Motivo:** os dois trechos identificam a mesma garantia, o mesmo bem e a mesma contratada; 12 ≠ 36.

### 004-D2 — Detecta 1 ano vs 24 meses

```yaml
id: 004-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-004
rule_class: NORMATIVE
aplica_regras: [RULE-004]
esperado: finding
```

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
Garantia técnica integral do Item 1 pela contratada: 1 ano.

## 5. MODELO DE EXECUÇÃO DO OBJETO
Garantia técnica integral do Item 1 pela contratada: 24 meses do recebimento definitivo.
```

### 004-N1 — Silêncio com mesma duração

```yaml
id: 004-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-004
rule_class: NORMATIVE
aplica_regras: [RULE-004]
esperado: silencio
```

```markdown
Garantia técnica integral mínima de 12 meses pela contratada.
A mesma garantia terá 12 meses, contados do recebimento definitivo.
```

### 004-N2 — Silêncio porque 1 ano = 12 meses

```yaml
id: 004-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-004
rule_class: NORMATIVE
aplica_regras: [RULE-004]
esperado: silencio
```

```markdown
Garantia técnica do Item 1 pela contratada: 1 ano.
Garantia técnica do Item 1 pela contratada: 12 meses do recebimento definitivo.
```

### 004-N3 — Silêncio com uma menção

```yaml
id: 004-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-004
rule_class: NORMATIVE
aplica_regras: [RULE-004]
esperado: silencio
```

```markdown
Garantia técnica on-site de 12 meses. Entrega em 15 dias corridos.
```

### 004-N4 — Silêncio quando garantia não é aplicável

```yaml
id: 004-N4
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-004
rule_class: NORMATIVE
aplica_regras: [RULE-004]
esperado: silencio
```

```markdown
Não se exige garantia técnica adicional para os gêneros perecíveis, considerada a validade indicada em cada embalagem e o consumo imediato após a entrega.
```

**Motivo:** RULE-004 detecta contradição; não cria obrigação de garantia quando não aplicável.

---

## RULE-005 — Recebimento insuficientemente definido

### 005-D1 — Detecta apenas fiscal e pagamento

```yaml
id: 005-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: finding
attrs.falta: [provisorio, definitivo]
```

```markdown
O contrato será fiscalizado pelo Setor de Patrimônio. Os bens serão entregues na sede e o pagamento ocorrerá após o envio da nota fiscal.
```

### 005-D2 — Detecta mera citação do art. 140

```yaml
id: 005-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: finding
attrs.mode: indefinido
```

```markdown
O recebimento observará o art. 140 da Lei nº 14.133/2021. Pagamento em até 10 dias úteis após o ateste da nota fiscal.
```

### 005-D3 — Detecta apenas provisório

```yaml
id: 005-D3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: finding
attrs.falta: [definitivo]
```

```markdown
Os bens serão recebidos provisoriamente, de forma sumária, no ato da entrega, pelo fiscal. Pagamento após a nota fiscal.
```

### 005-D4 — Detecta template com placeholders

```yaml
id: 005-D4
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: finding
attrs.falta: [responsavel_provisorio, prazo_definitivo, responsavel_definitivo]
```

```markdown
## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
Os bens serão recebidos provisoriamente por <responsável>, no ato da entrega, para verificação posterior.
O recebimento definitivo ocorrerá em XXXX dias por [servidor/comissão a indicar], mediante termo detalhado.
```

**Motivo:** texto de template e prazo placeholder não definem o rito concreto.

### 005-N1 — Silêncio com os dois ritos

```yaml
id: 005-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: silencio
```

```markdown
Os bens serão recebidos provisoriamente, de forma sumária, pelo fiscal no ato da entrega, para posterior verificação; e definitivamente por servidor ou comissão designada, em até 10 dias úteis após o provisório, mediante termo detalhado.
```

### 005-N2 — Silêncio com recebimentos simultâneos definidos

```yaml
id: 005-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: silencio
```

```markdown
Para estes bens padronizados de pronta entrega, os recebimentos provisório e definitivo ocorrerão simultaneamente no ato da entrega. O servidor municipal designado fará a conferência integral das quantidades, embalagens, validade e especificações e registrará o aceite em termo detalhado, sem prejuízo da rejeição de item desconforme.
```

### 005-N3 — Silêncio com etapa não aplicável fundamentada

```yaml
id: 005-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-005
rule_class: NORMATIVE
aplica_regras: [RULE-005]
esperado: silencio
```

```markdown
Em razão da conferência integral e imediata de cada unidade no balcão de retirada, não se aplica etapa provisória separada. O recebimento definitivo será realizado no mesmo ato por servidor municipal designado, após conferência de quantidade, integridade e especificação, e será registrado em termo detalhado.
```

**Motivo:** a não aplicabilidade não é fórmula isolada; identifica a etapa, justifica e define o aceite aplicável.

---

## RULE-006 — Integridade de anexo (`ADVISORY`)

### 006-D1 — Emite advisory para Anexo III não resolvido no pacote

```yaml
id: 006-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-006
rule_class: ADVISORY
aplica_regras: [RULE-006]
esperado: advisory
attrs.anchor: III
package_files: [termo-referencia.md]
```

```markdown
A distribuição das 500 carteiras seguirá os quantitativos e endereços das escolas relacionados no Anexo III deste Termo de Referência.
```

**Motivo:** é risco de integridade no pacote observado, não finding de compliance normativo.

### 006-N1 — Silêncio com anexo incorporado

```yaml
id: 006-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-006
rule_class: ADVISORY
aplica_regras: [RULE-006]
esperado: silencio
```

```markdown
A distribuição seguirá o Anexo I deste TR.
# ANEXO I — CRONOGRAMA E LOCAIS
1. Escola Norte — 250 carteiras.
2. Escola Sul — 250 carteiras.
```

### 006-N2 — Silêncio porque romano = arábico

```yaml
id: 006-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-006
rule_class: ADVISORY
aplica_regras: [RULE-006]
esperado: silencio
```

```markdown
Locais conforme Anexo III deste TR.
# ANEXO 3 — LOCAIS DE ENTREGA
Almoxarifado Municipal.
```

### 006-N3 — Silêncio para outro instrumento

```yaml
id: 006-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-006
rule_class: ADVISORY
aplica_regras: [RULE-006]
esperado: silencio
```

```markdown
A demanda está detalhada no Anexo I do ETP municipal nº 12/2024, que não integra este TR.
```

### 006-N4 — Silêncio com anexo em arquivo separado do pacote

```yaml
id: 006-N4
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-006
rule_class: ADVISORY
aplica_regras: [RULE-006]
esperado: silencio
package_files: [termo-referencia.md, anexo-iii-locais.pdf]
package_anchors:
  anexo-iii-locais.pdf: [ANEXO III]
```

```markdown
Os endereços e quantitativos constam do Anexo III deste Termo de Referência, juntado em arquivo separado.
```

**Motivo:** a âncora está resolvida no pacote; não precisa estar no mesmo arquivo do TR.

---

## RULE-007 — Definição divergente no TR

### 007-D1 — Detecta material e tipo incompatíveis

```yaml
id: 007-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-007
rule_class: NORMATIVE
aplica_regras: [RULE-007]
esperado: finding
```

```markdown
## 1. DEFINIÇÃO DO OBJETO
Item 1: 20 bebedouros industriais de coluna em aço inox, capacidade de 50 litros, 220 V.

## 4. REQUISITOS
Item 1: bebedouro de mesa, gabinete em plástico ABS, capacidade de 10 litros, 110 V.
```

### 007-D2 — Detecta atributo discreto incompatível

```yaml
id: 007-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-007
rule_class: NORMATIVE
aplica_regras: [RULE-007]
esperado: finding
attrs.atributo: [numero_gavetas, material]
```

```markdown
Item 1: 100 gaveteiros com 4 gavetas, chapa de aço nº 24.
Item 1 — especificação: MDF 18 mm, 3 gavetas.
```

### 007-N1 — Silêncio com refinamento compatível

```yaml
id: 007-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-007
rule_class: NORMATIVE
aplica_regras: [RULE-007]
esperado: silencio
```

```markdown
Item 1: bebedouro de coluna em aço inox, reservatório de 50 litros, 220 V.
Item 1: tipo coluna, chapa de aço inox escovado, reservatório de 50 litros, 220 V.
```

### 007-N2 — Silêncio com itens distintos

```yaml
id: 007-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-007
rule_class: NORMATIVE
aplica_regras: [RULE-007]
esperado: silencio
```

```markdown
Item 1: bebedouro de coluna, aço inox, 50 litros, 220 V.
Item 2: bebedouro de mesa, plástico ABS, 10 litros, 110 V.
```

### 007-N3 — Silêncio com CATMAT diferente e semanticamente compatível

```yaml
id: 007-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: RULE-007
rule_class: NORMATIVE
aplica_regras: [RULE-007]
esperado: silencio
extracted:
  - {item_id: item-1, atributo: CATMAT, valor: "150123", normalized_concept_id: cadeira-giratoria-escritorio}
  - {item_id: item-1, atributo: CATMAT, valor: "478901", normalized_concept_id: cadeira-giratoria-escritorio}
```

```markdown
## 1. OBJETO
Item 1: cadeira giratória de escritório, CATMAT 150123.

## 4. REQUISITOS
Item 1: cadeira giratória para escritório, CATMAT 478901, com apoio de braços.
```

**Motivo:** código bruto diferente não prova incompatibilidade; ambos foram mapeados ao mesmo conceito e o segundo trecho apenas refina a descrição.

---

## ADVISORY-008 — Requisito aferível sem método

Estes testes são de qualidade editorial `ADVISORY`, fora da R8 normativa. Nunca retornam `finding` normativo.

### 008-D1 — Emite advisory para ensaio mecânico sem comprovação

```yaml
id: 008-D1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: ADVISORY-008
rule_class: ADVISORY
aplica_regras: [ADVISORY-008]
esperado: advisory
```

```markdown
O calçado de segurança deverá possuir biqueira de composite com resistência a impactos de 200 Joules e solado com resistência a escorregamento SRC.
```

### 008-D2 — Emite advisory para desempenho sem método

```yaml
id: 008-D2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: ADVISORY-008
rule_class: ADVISORY
aplica_regras: [ADVISORY-008]
esperado: advisory
```

```markdown
O tecido dos uniformes deve possuir proteção solar UV fator 50+ e propriedade retardante a chamas classe A.
```

### 008-N1 — Silêncio com método ligado ao requisito

```yaml
id: 008-N1
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: ADVISORY-008
rule_class: ADVISORY
aplica_regras: [ADVISORY-008]
esperado: silencio
```

```markdown
O calçado deverá possuir biqueira de composite de 200 Joules e solado SRC. A comprovação ocorrerá por certificado válido e laudo de ensaio de laboratório acreditado, apresentados com a proposta.
```

### 008-N2 — Silêncio com especificação ordinária

```yaml
id: 008-N2
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: ADVISORY-008
rule_class: ADVISORY
aplica_regras: [ADVISORY-008]
esperado: silencio
```

```markdown
Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios e apoio de braços fixos.
```

### 008-N3 — Silêncio porque ambiguidade é R9

```yaml
id: 008-N3
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
rule_id: ADVISORY-008
rule_class: ADVISORY
aplica_regras: [ADVISORY-008]
esperado: silencio
```

```markdown
Os equipamentos deverão ser de alta qualidade e tecnologia moderna, com bom desempenho em uso contínuo.
```

---

## Matriz rápida

| id | profile_id | rule_id | rule_class | esperado |
|---|---|---|---|---|
| TR-MINIMO | PUBLICO_14133_PREGAO_ELETRONICO_BENS | ALL | NORMATIVE + ADVISORY | silêncio |
| 001-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-001 | NORMATIVE | finding |
| 001-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-001 | NORMATIVE | finding |
| 001-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-001 | NORMATIVE | silêncio |
| 001-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-001 | NORMATIVE | silêncio |
| 001-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-001 | NORMATIVE | finding |
| 002-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-002 | NORMATIVE | finding |
| 002-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-002 | NORMATIVE | finding |
| 002-D3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-002 | NORMATIVE | finding |
| 002-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-002 | NORMATIVE | silêncio |
| 002-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-002 | NORMATIVE | silêncio |
| 003-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-003 | NORMATIVE | finding |
| 003-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-003 | NORMATIVE | finding |
| 003-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-003 | NORMATIVE | silêncio |
| 003-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-003 | NORMATIVE | silêncio |
| 003-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-003 | NORMATIVE | silêncio |
| 004-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-004 | NORMATIVE | finding |
| 004-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-004 | NORMATIVE | finding |
| 004-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-004 | NORMATIVE | silêncio |
| 004-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-004 | NORMATIVE | silêncio |
| 004-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-004 | NORMATIVE | silêncio |
| 004-N4 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-004 | NORMATIVE | silêncio |
| 005-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | finding |
| 005-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | finding |
| 005-D3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | finding |
| 005-D4 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | finding |
| 005-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | silêncio |
| 005-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | silêncio |
| 005-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-005 | NORMATIVE | silêncio |
| 006-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-006 | ADVISORY / INTEGRITY | advisory |
| 006-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-006 | ADVISORY / INTEGRITY | silêncio |
| 006-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-006 | ADVISORY / INTEGRITY | silêncio |
| 006-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-006 | ADVISORY / INTEGRITY | silêncio |
| 006-N4 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-006 | ADVISORY / INTEGRITY | silêncio |
| 007-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-007 | NORMATIVE | finding |
| 007-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-007 | NORMATIVE | finding |
| 007-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-007 | NORMATIVE | silêncio |
| 007-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-007 | NORMATIVE | silêncio |
| 007-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | RULE-007 | NORMATIVE | silêncio |
| 008-D1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | ADVISORY-008 | ADVISORY / QUALITY | advisory |
| 008-D2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | ADVISORY-008 | ADVISORY / QUALITY | advisory |
| 008-N1 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | ADVISORY-008 | ADVISORY / QUALITY | silêncio |
| 008-N2 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | ADVISORY-008 | ADVISORY / QUALITY | silêncio |
| 008-N3 | PUBLICO_14133_PREGAO_ELETRONICO_BENS | ADVISORY-008 | ADVISORY / QUALITY | silêncio |

Nenhum controle entra no linter sem casos D e N correspondentes. Caso que altere predicado exige atualizar `rules_draft.md` no mesmo commit e preservar a separação entre `NORMATIVE` e `ADVISORY`.
