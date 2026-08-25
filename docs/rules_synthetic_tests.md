# Testes Sintéticos do TR Linter (v1.1) — Compras de Bens Comuns

Casos em Markdown para as 8 regras de `rules_draft.md`. Finding é achado, não veredito. Não usar “aprovado” / “reprovado”.

---

## Harness

Cada caso declara:

| Campo           | Valor                                                                            |
| --------------- | -------------------------------------------------------------------------------- |
| `id`            | estável (`001-D1`)                                                               |
| `rule_id`       | regra sob teste                                                                  |
| `aplica_regras` | lista fechada. Snippets parciais **não** rodam RULE-001 só porque omitem seções. |
| `esperado`      | `finding` \| `silencio`                                                          |
| `attrs`         | o que o finding deve carregar, se houver                                         |

`D` = detecta (finding da regra). `N` = não detecta (silêncio dessa regra).

O fixture `TR-MINIMO` é a base de regressão cruzada: com `aplica_regras: [RULE-001 … RULE-008]` o esperado é silêncio total. Mutações em 001-D1 etc. devem disparar **somente** a regra do caso.

---

## Fixture — TR-MINIMO

Documento sintético que satisfaz as 8 regras. Usar como controle negativo do suite.

```markdown
# TERMO DE REFERÊNCIA

## 1. DEFINIÇÃO DO OBJETO
1.1. Aquisição de cadeiras giratórias ergonômicas para escritório.
Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios.
Unidade de fornecimento: unidade.
Quantidade estimada: 50.
1.2. Não se aplica sistema de registro de preços.

## 2. FUNDAMENTAÇÃO DA CONTRATAÇÃO
2.1. Conforme ETP nº 12/2024.

## 3. DESCRIÇÃO DA SOLUÇÃO COMO UM TODO
3.1. Fornecimento único do Item 1, com garantia on-site.

## 4. REQUISITOS DA CONTRATAÇÃO
4.1. Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios, conforme NR-17 no que couber à adequação do posto.
4.2. Garantia técnica on-site de 12 (doze) meses contados do recebimento definitivo.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Prazo de entrega: 15 (quinze) dias corridos, contados do recebimento da Nota de Empenho.
5.2. Local: Almoxarifado Central, Brasília/DF.

## 6. MODELO DE GESTÃO DO CONTRATO
6.1. Fiscalização pelo setor requisitante.

## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
7.1. Recebimento:
a) provisório, de forma sumária, no ato da entrega, pelo fiscal, para posterior verificação de conformidade;
b) definitivo, em até 10 (dez) dias úteis após o provisório, por servidor designado, mediante termo detalhado.
7.2. Pagamento em até 10 dias úteis após a liquidação.

## 8. FORMA E CRITÉRIOS DE SELEÇÃO DO FORNECEDOR
8.1. Pregão eletrônico, menor preço por item.

## 9. ESTIMATIVAS DO VALOR DA CONTRATAÇÃO
9.1. Valor total estimado: R$ 35.000,00.

## 10. ADEQUAÇÃO ORÇAMENTÁRIA
10.1. Programa de Trabalho 10.122.0001, Fonte 100, Elemento 339030.
```

`aplica_regras: [RULE-001, RULE-002, RULE-003, RULE-004, RULE-005, RULE-006, RULE-007, RULE-008]`
`esperado: silencio`

---

## RULE-001 — Seção obrigatória ausente

### 001-D1 — Detecta (várias seções faltando)

`aplica_regras: [RULE-001]` · `esperado: finding` · `attrs.missing` contém `solucao`, `requisitos`, `execucao`, `gestao`, `medicao_pagamento`, `selecao`, `adequacao_orcamentaria`

```markdown
# TERMO DE REFERÊNCIA

## 1. DO OBJETO
Aquisição de 100 caixas de papel toalha interfolhado.

## 2. DA FUNDAMENTAÇÃO
Conforme ETP nº 05/2024.

## 3. DO VALOR ESTIMADO
Custo total estimado: R$ 5.400,00.
```

**Motivo:** aliases de `objeto`, `fundamentacao` e `estimativa` estão presentes; os demais elementos da tabela da § 4 não.

---

### 001-D2 — Detecta (título sem conteúdo)

`aplica_regras: [RULE-001]` · `esperado: finding` · `attrs.missing` contém `execucao`

Partir do TR-MINIMO e substituir a seção 5 por:

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
....
```

**Motivo:** heading canônico com corpo placeholder conta como ausente.

---

### 001-N1 — Silêncio (dez elementos canônicos)

`aplica_regras: [RULE-001]` · `esperado: silencio`

Usar o TR-MINIMO.

---

### 001-N2 — Silêncio (títulos alias)

`aplica_regras: [RULE-001]` · `esperado: silencio`

```markdown
# TERMO DE REFERÊNCIA

## 1. DO OBJETO
Aquisição de 50 cadeiras giratórias. Unidade: unidade. Quantidade: 50.

## 2. DA JUSTIFICATIVA
Conforme ETP nº 12/2024.

## 3. DA SOLUÇÃO
Fornecimento único de mobiliário.

## 4. DOS REQUISITOS
Cadeira giratória, tecido preto, cinco rodízios.

## 5. DA EXECUÇÃO
Entrega em 15 dias corridos no Almoxarifado Central.

## 6. DA GESTÃO
Fiscalização pelo setor requisitante.

## 7. DO PAGAMENTO
Recebimento provisório no ato da entrega e definitivo em 10 dias úteis; pagamento após ateste.

## 8. DA SELEÇÃO
Pregão eletrônico, menor preço.

## 9. DA ESTIMATIVA DE PREÇOS
R$ 35.000,00.

## 10. DA DOTAÇÃO
Programa de Trabalho 10.122.0001, Fonte 100.
```

**Motivo:** a regra casa aliases, não a numeração AGU.

---

### 001-N3 — Silêncio (SRP sem adequação orçamentária)

`aplica_regras: [RULE-001]` · `esperado: silencio`

TR-MINIMO com as seguintes alterações: (i) em 1.2, `Contratação por sistema de registro de preços.`; (ii) remover a seção 10.

**Motivo:** IN 81/2022, art. 9º, X — adequação orçamentária não se aplica a SRP. Os outros nove elementos permanecem.

---

## RULE-002 — Quantidade ou unidade ausente

### 002-D1 — Detecta (prosa sem quantidade)

`aplica_regras: [RULE-002]` · `esperado: finding` · `attrs.falta` inclui `quantidade`

```markdown
## 1. OBJETO
Item 1: Papel sulfite A4, alcalino, branco, 75 g/m², embalagem com 500 folhas (resma), certificado FSC ou Cerflor.
Valor unitário de referência: R$ 26,00.
```

**Motivo:** embalagem na descrição não é quantitativo demandado. Valor unitário não é quantidade.

---

### 002-D2 — Detecta (célula de quantidade vazia)

`aplica_regras: [RULE-002]` · `esperado: finding`

```markdown
## 1. DEFINIÇÃO DO OBJETO
| Item | Descrição | Unidade | Qtd Estimada | Valor Unit. Ref. |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Notebook i7, 16GB RAM, SSD 512GB | Unidade |  | R$ 4.500,00 |
```

**Motivo:** unidade preenchida; quantidade vazia.

---

### 002-D3 — Detecta (quantidade sem unidade)

`aplica_regras: [RULE-002]` · `esperado: finding` · `attrs.falta` inclui `unidade`

```markdown
## 1. DEFINIÇÃO DO OBJETO
Item 1: Papel sulfite A4, 75 g/m².
Quantidade estimada: 1.200.
Valor unitário de referência: R$ 26,00.
```

**Motivo:** número sem unidade de fornecimento. `1.200` não diz se é folha, resma ou caixa.

---

### 002-N1 — Silêncio (tabela completa)

`aplica_regras: [RULE-002]` · `esperado: silencio`

```markdown
## 1. DEFINIÇÃO DO OBJETO
| Item | Descrição | Unidade | Qtd Estimada | Valor Unit. Ref. | Valor Total Ref. |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Notebook i7, 16GB RAM, SSD 512GB | Unidade | 30 | R$ 4.500,00 | R$ 135.000,00 |
```

---

### 002-N2 — Silêncio (quantidade em prosa)

`aplica_regras: [RULE-002]` · `esperado: silencio`

```markdown
## 1. DEFINIÇÃO DO OBJETO
Aquisição de 50 cadeiras giratórias ergonômicas.
Unidade de fornecimento: unidade.
Quantidade estimada: 50.
```

---

## RULE-003 — Prazo de entrega ausente

### 003-D1 — Detecta (evento sem duração)

`aplica_regras: [RULE-003]` · `esperado: finding`

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. A contratada deverá entregar os materiais no Almoxarifado Central após a devida notificação e recebimento da Nota de Empenho.
5.2. O frete e o descarregamento correrão por conta da fornecedora.
```

---

### 003-D2 — Detecta (só há prazo de vigência)

`aplica_regras: [RULE-003]` · `esperado: finding`

```markdown
## 1. DEFINIÇÃO DO OBJETO
1.1. Aquisição de 50 cadeiras. Vigência da contratação: 12 (doze) meses.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. A contratada entregará os bens no Almoxarifado Central mediante ordem de fornecimento.
```

**Motivo:** vigência não substitui prazo de entrega. A regra não mistura os dois campos.

---

### 003-N1 — Silêncio (dias corridos)

`aplica_regras: [RULE-003]` · `esperado: silencio`

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Entrega no Almoxarifado Central no prazo máximo de 15 (quinze) dias corridos, contados da confirmação do recebimento da Nota de Empenho.
```

---

### 003-N2 — Silêncio (dias úteis ou pronta entrega)

`aplica_regras: [RULE-003]` · `esperado: silencio`

Dois documentos distintos; ambos devem silenciar:

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Prazo de entrega: 10 (dez) dias úteis, contados da ordem de fornecimento.
```

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Entrega imediata, no ato da retirada no Almoxarifado Central, mediante Nota de Empenho.
```

---

## RULE-004 — Garantia contraditória

### 004-D1 — Detecta (12 vs 36 meses)

`aplica_regras: [RULE-004]` · `esperado: finding`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.2. O Item 1 (ar-condicionado split 18.000 BTUs) deverá possuir garantia técnica mínima de 12 (doze) meses fornecida pelo fabricante.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.6. A contratada prestará assistência técnica e garantia integral contra defeitos pelo período de 36 (trinta e seis) meses a partir do ateste definitivo.
```

---

### 004-D2 — Detecta (1 ano vs 24 meses)

`aplica_regras: [RULE-004]` · `esperado: finding`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.2. Garantia de 1 (um) ano.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.6. Garantia de 24 (vinte e quatro) meses contados do recebimento definitivo.
```

**Motivo:** após normalizar, 12 meses ≠ 24 meses.

---

### 004-N1 — Silêncio (mesma duração)

`aplica_regras: [RULE-004]` · `esperado: silencio`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.2. Garantia técnica integral mínima de 12 (doze) meses fornecida pelo fabricante.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.6. Garantia integral contra defeitos pelo período de 12 (doze) meses a partir do ateste definitivo.
```

**Motivo:** piso + termo inicial, mesma duração.

---

### 004-N2 — Silêncio (1 ano = 12 meses)

`aplica_regras: [RULE-004]` · `esperado: silencio`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.2. Garantia de 1 (um) ano.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.6. Garantia de 12 (doze) meses contados do recebimento definitivo.
```

---

### 004-N3 — Silêncio (garantia citada uma vez)

`aplica_regras: [RULE-004]` · `esperado: silencio`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.2. Garantia técnica on-site de 12 (doze) meses.

## 5. MODELO DE EXECUÇÃO DO OBJETO
5.1. Entrega em 15 dias corridos no Almoxarifado Central.
```

**Motivo:** ausência de segunda menção não é contradição. A IN 81 não torna a garantia obrigatória em todo caso.

---

## RULE-005 — Recebimento não definido

### 005-D1 — Detecta (só fiscal e pagamento)

`aplica_regras: [RULE-005]` · `esperado: finding` · `attrs.falta = ambos`

```markdown
## 6. MODELO DE GESTÃO DO CONTRATO
6.1. O contrato será fiscalizado pelo Setor de Patrimônio.
6.2. Os bens serão entregues na sede e o pagamento será liberado após o envio da fatura fiscal.
```

---

### 005-D2 — Detecta (cita o art. 140 sem distinguir os ritos)

`aplica_regras: [RULE-005]` · `esperado: finding`

```markdown
## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
7.1. O recebimento observará o art. 140 da Lei nº 14.133/2021.
7.2. Pagamento em até 10 dias úteis após o ateste da nota fiscal.
```

**Motivo:** remissão legal não descreve provisório (sumário) nem definitivo (termo detalhado).

---

### 005-D3 — Detecta (só provisório)

`aplica_regras: [RULE-005]` · `esperado: finding` · `attrs.falta = definitivo`

```markdown
## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
7.1. Os bens serão recebidos provisoriamente, de forma sumária, no ato da entrega, pelo fiscal.
7.2. Pagamento em até 10 dias úteis após a nota fiscal.
```

---

### 005-N1 — Silêncio (os dois ritos)

`aplica_regras: [RULE-005]` · `esperado: silencio`

```markdown
## 7. CRITÉRIOS DE MEDIÇÃO E PAGAMENTO
7.1. O recebimento do objeto observará o art. 140, II, da Lei nº 14.133/2021:
a) provisoriamente, de forma sumária, pelo fiscal, no ato da entrega, para posterior verificação da conformidade;
b) definitivamente, por servidor ou comissão designada, em até 10 (dez) dias úteis após o provisório, mediante termo detalhado.
```

---

## RULE-006 — Anexo inexistente

### 006-D1 — Detecta (Anexo III citado e ausente)

`aplica_regras: [RULE-006]` · `esperado: finding` · `attrs.anchor = "III"`

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.3. A distribuição das 500 carteiras escolares deverá seguir o quantitativo e os endereços das 14 escolas polo relacionados no Anexo III deste Termo de Referência.

[FIM DO ARQUIVO]
```

---

### 006-N1 — Silêncio (anexo presente)

`aplica_regras: [RULE-006]` · `esperado: silencio`

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.3. A distribuição seguirá o Anexo I deste Termo de Referência.

---
# ANEXO I - CRONOGRAMA E LOCAIS DE ENTREGA
1. Escola Polo Norte — 250 carteiras.
2. Escola Polo Sul — 250 carteiras.
```

---

### 006-N2 — Silêncio (romano = arábico)

`aplica_regras: [RULE-006]` · `esperado: silencio`

```markdown
## 5. MODELO DE EXECUÇÃO DO OBJETO
5.3. Locais de entrega conforme Anexo III deste Termo de Referência.

---
# ANEXO 3 - LOCAIS DE ENTREGA
Almoxarifado Central, Brasília/DF.
```

---

### 006-N3 — Silêncio (anexo de outro instrumento)

`aplica_regras: [RULE-006]` · `esperado: silencio`

```markdown
## 2. FUNDAMENTAÇÃO DA CONTRATAÇÃO
2.1. A demanda está detalhada no Anexo I do ETP nº 12/2024, que não integra este TR.
```

**Motivo:** referência extra-TR explícita. Resolução ETP↔TR é R7.

---

## RULE-007 — Definição divergente no TR

### 007-D1 — Detecta (material e tipo)

`aplica_regras: [RULE-007]` · `esperado: finding`

```markdown
## 1. DEFINIÇÃO DO OBJETO
1.1. Aquisição de 20 bebedouros industriais de coluna em aço inox, capacidade de 50 litros, 220 V.

## 4. REQUISITOS DA CONTRATAÇÃO / ESPECIFICAÇÃO TÉCNICA
4.1. Item 1 - Bebedouro: tipo mesa/bancada, gabinete em plástico ABS, refrigeração de 10 litros/hora, 110 V.
```

**Motivo:** mesmo item; tipo, material, capacidade e voltagem incompatíveis.

---

### 007-D2 — Detecta (atributo discreto)

`aplica_regras: [RULE-007]` · `esperado: finding` · atributo: número de gavetas e/ou material

```markdown
## 1. DO OBJETO
Item 1: 100 gaveteiros volantes com 4 gavetas, chapa de aço nº 24, fechadura central.

## 4. REQUISITOS DA CONTRATAÇÃO
Item 1 - Gaveteiro volante: MDF 18 mm, 3 gavetas com corrediças telescópicas.
```

---

### 007-N1 — Silêncio (refinamento compatível)

`aplica_regras: [RULE-007]` · `esperado: silencio`

```markdown
## 1. DEFINIÇÃO DO OBJETO
1.1. Aquisição de 20 bebedouros industriais de coluna em aço inox, capacidade de 50 litros, 220 V.

## 4. REQUISITOS DA CONTRATAÇÃO / ESPECIFICAÇÃO TÉCNICA
4.1. Item 1 - Bebedouro: tipo coluna, chapa de aço inox escovado, reservatório de 50 litros, 220 V.
```

**Motivo:** B detalha A; nenhum par (atributo, valor) é disjunto.

---

### 007-N2 — Silêncio (itens distintos)

`aplica_regras: [RULE-007]` · `esperado: silencio`

```markdown
## 1. DEFINIÇÃO DO OBJETO
Item 1: bebedouro de coluna, aço inox, 50 litros, 220 V. Quantidade: 10.
Item 2: bebedouro de mesa, plástico ABS, 10 litros/hora, 110 V. Quantidade: 10.

## 4. REQUISITOS DA CONTRATAÇÃO
Item 1: coluna, aço inox, 50 litros, 220 V.
Item 2: mesa, plástico ABS, 10 litros/hora, 110 V.
```

---

## RULE-008 — Requisito aferível sem critério

### 008-D1 — Detecta (ensaio mecânico sem comprovação)

`aplica_regras: [RULE-008]` · `esperado: finding`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.4. O calçado de segurança tipo botina de couro deverá possuir biqueira de composite com resistência a impactos de até 200 Joules e solado com resistência a escorregamento SRC.
```

**Motivo:** Joules e SRC estão na allowlist; não há CA, laudo ou norma de ensaio como método.

---

### 008-D2 — Detecta (desempenho certificado sem método)

`aplica_regras: [RULE-008]` · `esperado: finding`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.1. O tecido dos uniformes deve possuir proteção solar UV fator 50+ e propriedade retardante a chamas classe A.
```

---

### 008-N1 — Silêncio (método ligado ao requisito)

`aplica_regras: [RULE-008]` · `esperado: silencio`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.4. O calçado de segurança tipo botina de couro deverá possuir biqueira de composite (200 Joules) e solado SRC.
4.5. A comprovação do subitem 4.4 dar-se-á por Certificado de Aprovação (CA) válido e laudo de ensaio de laboratório credenciado, apresentados com a proposta.
```

---

### 008-N2 — Silêncio (especificação ordinária)

`aplica_regras: [RULE-008]` · `esperado: silencio`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.1. Item 1: cadeira giratória, revestimento em tecido preto, cinco rodízios, apoio de braços fixos.
```

**Motivo:** descritivo comum. Conformidade se verifica no recebimento (RULE-005), não por laudo.

---

### 008-N3 — Silêncio nesta regra (ambiguidade é R9)

`aplica_regras: [RULE-008]` · `esperado: silencio`

```markdown
## 4. REQUISITOS DA CONTRATAÇÃO
4.1. Os equipamentos deverão ser de alta qualidade e tecnologia moderna, com bom desempenho em uso contínuo.
```

**Motivo:** sem métrica da allowlist. Se algum linter semântico apontar risco, é R9. RULE-008 não dispara.

---

## Matriz rápida

| id | regra | esperado |
|---|---|---|
| TR-MINIMO | todas | silêncio |
| 001-D1 | 001 | finding |
| 001-D2 | 001 | finding |
| 001-N1 | 001 | silêncio |
| 001-N2 | 001 | silêncio |
| 001-N3 | 001 | silêncio |
| 002-D1 | 002 | finding |
| 002-D2 | 002 | finding |
| 002-D3 | 002 | finding |
| 002-N1 | 002 | silêncio |
| 002-N2 | 002 | silêncio |
| 003-D1 | 003 | finding |
| 003-D2 | 003 | finding |
| 003-N1 | 003 | silêncio |
| 003-N2 | 003 | silêncio |
| 004-D1 | 004 | finding |
| 004-D2 | 004 | finding |
| 004-N1 | 004 | silêncio |
| 004-N2 | 004 | silêncio |
| 004-N3 | 004 | silêncio |
| 005-D1 | 005 | finding |
| 005-D2 | 005 | finding |
| 005-D3 | 005 | finding |
| 005-N1 | 005 | silêncio |
| 006-D1 | 006 | finding |
| 006-N1 | 006 | silêncio |
| 006-N2 | 006 | silêncio |
| 006-N3 | 006 | silêncio |
| 007-D1 | 007 | finding |
| 007-D2 | 007 | finding |
| 007-N1 | 007 | silêncio |
| 007-N2 | 007 | silêncio |
| 008-D1 | 008 | finding |
| 008-D2 | 008 | finding |
| 008-N1 | 008 | silêncio |
| 008-N2 | 008 | silêncio |
| 008-N3 | 008 | silêncio |

Nenhuma regra entra no linter sem os casos D e N correspondentes. Caso novo que mude o predicado exige atualizar `rules_draft.md` no mesmo commit.
