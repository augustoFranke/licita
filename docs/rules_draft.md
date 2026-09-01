# Catálogo Municipal de Regras Determinísticas do TR Linter — Compras de Bens Comuns

Catálogo versionado da R8 / F-05 determinística (fatia M1) para o perfil `PUBLICO_14133_PREGAO_ELETRONICO_BENS`: Termo de Referência municipal para aquisição de bens comuns por pregão eletrônico, sob a Lei nº 14.133/2021.

A única base normativa vinculante deste catálogo é a **Lei nº 14.133/2021 aplicável aos Municípios**. A IN SEGES/ME nº 81/2022, os modelos da AGU e o TR Digital são `REFERENCE_ONLY`: podem inspirar vocabulário, aliases e exemplos comparativos, mas nunca criam obrigação municipal, nunca sustentam finding `NORMATIVE` e nunca determinam a classificação `SUPPORTED`.

Enums de finding seguem `01_REQUIREMENTS.md`: severidade `HIGH` | `MEDIUM` | `INFO`; status `OPEN` | `UNDER_REVIEW` | `RESOLVED` | `ACCEPTED_RISK` | `FALSE_POSITIVE`. Este catálogo emite `HIGH` ou `MEDIUM`.

Este arquivo é especificação de implementação, não parecer jurídico. Finding é **achado/risco para revisão humana**. Nunca “ilegal”, “reprovado” ou “aprovado”.

Testes: `rules_synthetic_tests.md`.

---

## 1. Escopo, classes e fontes

### 1.1 Perfil suportado

| Campo | Valor |
|---|---|
| `profile_id` | `PUBLICO_14133_PREGAO_ELETRONICO_BENS` |
| ente | Município |
| regime | Lei nº 14.133/2021 |
| modalidade | pregão eletrônico |
| objeto | aquisição de bens comuns |
| fora do perfil | obras, serviços, locações, alienações, contratação direta e regimes não municipais |

A decisão `SUPPORTED` decorre apenas do classificador de escopo acima. Citação, aderência ou divergência em relação à IN nº 81/2022, a modelo AGU ou ao TR Digital não altera essa decisão.

### 1.2 Classes de controle

| `rule_class` | Efeito |
|---|---|
| `NORMATIVE` | Controle com fundamento vinculante expresso na Lei nº 14.133/2021. Integra a R8 normativa do perfil. |
| `ADVISORY` | Controle de qualidade ou integridade documental. Não é conclusão de compliance, não integra a R8 normativa e não determina `SUPPORTED`. |

São `NORMATIVE`: RULE-001, RULE-002, RULE-003, RULE-004, RULE-005 e RULE-007. São `ADVISORY`: RULE-006 (`category: INTEGRITY`) e ADVISORY-008 (`category: QUALITY`). O identificador histórico `RULE-008` fica aposentado; novos eventos usam `ADVISORY-008`.

### 1.3 Referências comparativas `REFERENCE_ONLY`

A IN SEGES/ME nº 81/2022, os modelos AGU e o TR Digital são instrumentos federais usados somente como referências comparativas. Implementações podem consultar sua terminologia para ampliar aliases ou elaborar exemplos, desde que:

1. a referência seja marcada `REFERENCE_ONLY`;
2. não apareça em `fundamento_normativo` de controle municipal;
3. não transforme estrutura de modelo federal em seção municipal obrigatória;
4. não altere `SUPPORTED`, severidade normativa ou resultado `NORMATIVE`.

---

## 2. Como ler este catálogo

Cada controle declara:

| Campo | Função |
|---|---|
| `rule_id` | Identificador estável |
| `rule_class` | `NORMATIVE` ou `ADVISORY` |
| `profile_id` | Perfil em que o controle pode rodar |
| `descricao` | O que o achado comunica ao revisor |
| `escopo` | Quando roda e quando não roda |
| `fundamento_normativo` | Dispositivo da Lei, somente para `NORMATIVE`; `não se aplica` para `ADVISORY` |
| `rationale` | Justificativa operacional de controle `ADVISORY` |
| `severidade` | `HIGH` ou `MEDIUM` |
| `entrada` | Sobre o que a função opera |
| `funcao_de_deteccao` | Predicado determinístico |
| `nao_dispara` | Guardas de falso positivo |
| `finding` | Formato do achado |
| `testes` | IDs em `rules_synthetic_tests.md` |

Se o predicado depender de equivalência semântica sem campo extraído, a checagem não pertence a este catálogo determinístico — vai para a R9.

---

## 3. Política de severidade

| Nível | Uso neste catálogo |
|---|---|
| `HIGH` | Omissão ou contradição normativa que impede executar, receber ou julgar o objeto de forma objetiva. |
| `MEDIUM` | Risco de integridade ou qualidade que requer revisão, sem conclusão normativa automática. |
| `INFO` | Reservado a outros engines; não usado aqui. |

O linter não emite veredito sobre o processo. Severidade ordena revisão; não classifica legalidade. Em especial, findings `ADVISORY` são recomendações mesmo quando têm severidade `MEDIUM`.

---

## 4. Entrada comum e convenções

### 4.1 Entrada preferencial

A função de detecção opera sobre o TR já estruturado (R2/R5), não sobre o PDF cru:

- `DocumentContext` (`profile_id`, `rule_class`, metadados do pacote e overlays)
- `Section` (título normalizado, corpo, evidência)
- `Item` (identificador, descrição)
- `FieldValue` (tipo, valor, unidade, item, evidência)
- `Requirement` (atributo, operador, valor, unidade, item, evidência)
- `PackageFile` (nome, tipo, hash e âncoras de anexos)

Texto original permanece só como evidência. Se um campo exigido pela regra não puder ser representado sem voltar ao texto livre, a regra ainda não está pronta — isso é gate da R2, não da R8.

### 4.2 Normalização

Antes de comparar:

- casefold; remover acentos; colapsar whitespace
- títulos: remover numeração inicial (`1.`, `1.1`, `Capítulo I`, `Seção 4`, `Item 1 -`)
- anexos: `Anexo III` = `Anexo 3` = `ANEXO III`; `Apêndice A` ≠ `Anexo A`
- duração: `1 ano` = `12 meses`; `15 (quinze) dias corridos` = `15 dias corridos`
- `dias úteis` e `dias corridos` não são a mesma unidade
- item: `Item 1`, `item 01`, `lote 1` só são o mesmo se o extrator os tiver ligado ao mesmo `item_id`
- placeholders: `....`, `XXXX`, `XX dias`, `[preencher]`, `<responsável>`, `a definir` e equivalentes não são valores preenchidos

### 4.3 Formato do finding

```text
rule_id: RULE-00X | ADVISORY-008
rule_class: NORMATIVE | ADVISORY
profile_id: PUBLICO_14133_PREGAO_ELETRONICO_BENS
severity: HIGH | MEDIUM
message: <achado, uma frase, sem juízo de ilegalidade>
evidence: [<trechos com seção/página>]
item_id: <se aplicável>
attrs: { ... }
```

---

## 5. Elementos descritivos de RULE-001

O checklist municipal deriva diretamente do art. 6º, XXIII, combinado com o conteúdo do art. 40, § 1º, da Lei nº 14.133/2021. Títulos são aliases de extração, não uma numeração obrigatória.

### 5.1 Elementos do art. 6º, XXIII

| `element_id` | Conteúdo | Títulos aceitos (não exaustivo) |
|---|---|---|
| `objeto` | definição do objeto, natureza, quantitativos, prazo do contrato e eventual prorrogação | definição do objeto; do objeto; objeto; descrição do objeto |
| `fundamentacao` | fundamentação da contratação, com referência aos estudos correspondentes ou extrato não sigiloso | fundamentação da contratação; fundamentação; justificativa; da justificativa |
| `solucao` | descrição da solução como um todo, considerado o ciclo de vida | descrição da solução como um todo; da solução; solução como um todo |
| `requisitos` | requisitos da contratação | requisitos da contratação; requisitos; especificações da contratação |
| `execucao` | modelo de execução do objeto | modelo de execução do objeto; da execução; execução do objeto |
| `gestao` | modelo de gestão do contrato | modelo de gestão do contrato; da gestão; gestão do contrato; fiscalização |
| `medicao_pagamento` | critérios de medição e de pagamento | critérios de medição e de pagamento; medição e pagamento; do pagamento |
| `selecao` | forma e critérios de seleção do fornecedor | forma e critérios de seleção do fornecedor; seleção do fornecedor; critério de julgamento |
| `estimativa` | estimativas do valor, preços unitários referenciais, memórias e documentos de suporte, ainda que em peça classificada | estimativas do valor da contratação; valor da contratação; estimativa de preços; do valor estimado |
| `adequacao_orcamentaria` | adequação orçamentária | adequação orçamentária; da dotação; dotação orçamentária |

No perfil-base municipal, os dez elementos são verificados. **SRP não cria exceção universal para `adequacao_orcamentaria` neste catálogo.** Um overlay municipal futuro poderá configurar tratamento diverso se trouxer base municipal expressa e `overlay_id`; sem esse overlay, a omissão é detectada.

### 5.2 Conteúdo adicional do art. 40, § 1º

| `element_id` | Conteúdo no TR | Aplicabilidade no perfil |
|---|---|---|
| `especificacao_produto` | especificação do produto, observados os requisitos de qualidade, rendimento, compatibilidade, durabilidade e segurança | obrigatória; pode estar em `objeto` ou `requisitos` |
| `local_entrega` | indicação do local ou dos locais de entrega | obrigatória para os bens físicos deste perfil; pode ser endereço, unidade, lista ou anexo resolvido |
| `recebimento` | regras de recebimento provisório e definitivo, quando aplicáveis | deve haver rito normal ou tratamento explícito de simultaneidade/não aplicabilidade; detalhamento é verificado por RULE-005 |
| `garantia_assistencia` | garantia exigida e condições de manutenção e assistência técnica, quando aplicáveis | condicional; ausência não dispara sem indicador estruturado de aplicabilidade |

Esses conteúdos não precisam ser seções autônomas. Garantia, entrega e recebimento também possuem controles específicos (RULE-003, RULE-004 e RULE-005). Corpo vazio ou só placeholder conta como ausente.

---

## 6. Controles

### RULE-001

- **rule_id**: RULE-001
- **rule_class**: NORMATIVE
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Elemento descritivo exigido ausente ou sem conteúdo no TR.
- **escopo**: Todo TR classificado `SUPPORTED` neste perfil. Avalia presença determinística, não qualidade argumentativa nem numeração de modelo.
- **fundamento_normativo**: Lei nº 14.133/2021, art. 6º, XXIII, alíneas a a j, e art. 40, § 1º, incisos I a III.
- **severidade**: HIGH
- **entrada**: `DocumentContext`, `Section[]`, campos dos conteúdos da § 5 e eventual overlay municipal explícito.
- **funcao_de_deteccao**:
  1. Confirmar o `profile_id`; caso diverso, não rodar.
  2. Normalizar títulos e casar os dez elementos da § 5.1.
  3. Considerar presente apenas seção ou conteúdo equivalente com texto não-placeholder.
  4. Verificar os conteúdos aplicáveis da § 5.2. `especificacao_produto` e `local_entrega` são exigidos no perfil; `recebimento` aceita os modos detalhados em RULE-005; `garantia_assistencia` só é exigida quando `garantia_applicability = APPLICABLE` já foi extraído.
  5. Não ignorar `adequacao_orcamentaria` apenas porque o documento menciona SRP. Exceção somente por overlay municipal explícito, versionado e fora do perfil-base.
  6. Disparar um finding por `element_id` ausente.
- **nao_dispara**: conteúdo em seção com alias reconhecido; estimativa em anexo classificado resolvido no pacote; garantia marcada justificadamente `NOT_APPLICABLE`; exceção configurada por overlay municipal expresso.
- **finding**: `attrs.missing = [element_id, ...]`; incluir `profile_id` e, se usado, `overlay_id`.
- **testes**: 001-D1, 001-D2, 001-N1, 001-N2, 001-N3

---

### RULE-002

- **rule_id**: RULE-002
- **rule_class**: NORMATIVE
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Item ou lote sem quantidade numérica estimada ou sem unidade de fornecimento.
- **escopo**: Cada `Item` extraído do TR. Não roda se o TR não tiver item identificável; isso é falha de extração ou RULE-001 em `objeto`.
- **fundamento_normativo**: Lei nº 14.133/2021, art. 6º, XXIII, a, e art. 40, III.
- **severidade**: HIGH
- **entrada**: `Item[]` com `FieldValue` de `quantidade` e `unidade`.
- **funcao_de_deteccao**:
  1. Para cada item, ler quantidade e unidade em tabela, prosa ou campo extraído.
  2. Quantidade válida = número finito > 0 (aceitar `1.200`, `1200`, `1.200,5`). Inválida: célula vazia, `—`, `a definir`, `conforme demanda`, `xx`, 0 ou não numérico.
  3. Unidade válida = token de unidade de fornecimento (`unidade`, `un`, `resma`, `caixa`, `kg`, `l`, etc.) ligado ao item. Embalagem na descrição (`resma com 500 folhas`) não substitui a quantidade de unidades demandadas.
  4. Disparar por item, com `attrs.falta = quantidade | unidade | ambas`.
- **nao_dispara**: quantidade em prosa; unidade implícita canônica já extraída (`50 cadeiras` → qtd. 50, un. `unidade`); valores monetários que não sejam quantidade.
- **finding**: evidência da linha ou trecho do item.
- **testes**: 002-D1, 002-D2, 002-D3, 002-N1, 002-N2

---

### RULE-003

- **rule_id**: RULE-003
- **rule_class**: NORMATIVE
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Prazo determinado de entrega ou de cada fornecimento ausente.
- **escopo**: Todo TR do perfil. Só prazo de entrega/fornecimento. Prazo de vigência contratual é outro campo e não substitui o prazo operacional.
- **fundamento_normativo**: Lei nº 14.133/2021, art. 6º, XXIII, a e e, e art. 40, § 1º, II.
- **severidade**: HIGH
- **entrada**: `FieldValue` tipo `prazo_entrega`; seções `execucao` e `objeto`.
- **funcao_de_deteccao**:
  1. Há prazo determinado se existe duração numérica (`N dias úteis|corridos`, `N horas`), data certa ou cláusula explícita de entrega imediata/pronta entrega.
  2. Em fornecimento parcelado ou sob demanda, cada ordem deve estar vinculada a prazo determinado; o período global de vigência não basta.
  3. Não é prazo determinado: `após a nota de empenho`, `após a ordem de fornecimento`, `quando solicitado`, `em tempo hábil`, sem N.
  4. Disparar um finding para o TR se nenhum item/objeto tem prazo determinado. Se prazos são por item, disparar só nos itens sem prazo.
- **nao_dispara**: `15 (quinze) dias corridos`; `10 dias úteis`; `entrega imediata`; `fornecimento sob demanda, em até 5 dias úteis de cada ordem`.
- **finding**: evidência do trecho que fala em entregar sem prazo, ou da ausência do conteúdo.
- **testes**: 003-D1, 003-D2, 003-N1, 003-N2, 003-N3

---

### RULE-004

- **rule_id**: RULE-004
- **rule_class**: NORMATIVE
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Prazo ou condição da mesma garantia técnica, para o mesmo bem e sujeito obrigado, citado de forma contraditória no TR.
- **escopo**: Só contradição interna. Não torna garantia obrigatória quando ela não for aplicável. Menção única, ausência de garantia ou declaração justificada de não aplicabilidade não dispara.
- **fundamento_normativo**: Lei nº 14.133/2021, art. 40, § 1º, III.
- **severidade**: HIGH
- **entrada**: `FieldValue` tipo `garantia` (duração, marco inicial, modalidade, `item_id`, `guarantor_id` e tipo de garantia).
- **funcao_de_deteccao**:
  1. Agrupar menções pela mesma garantia, mesmo `item_id`/objeto e mesmo sujeito obrigado (`guarantor_id`). Se esses vínculos não puderem ser determinados, não declarar contradição nesta regra.
  2. Normalizar duração para meses.
  3. Há conflito se duas durações vinculantes diferem; se marcos iniciais exclusivos são incompatíveis; ou se modalidades exclusivas são incompatíveis para o mesmo período.
  4. `mínima de 12 meses` e `12 meses contados do recebimento definitivo` são consistentes quando tratam da mesma garantia.
  5. Garantia legal ao lado de garantia contratual ou garantia do fabricante ao lado de obrigação distinta da contratada não são comparadas sem vínculo explícito de identidade.
- **nao_dispara**: uma única menção; 12 vs 12; 1 ano vs 12 meses; detalhamento compatível; garantias ou sujeitos distintos; garantia não aplicável.
- **finding**: os dois trechos e `attrs.left`, `attrs.right`, `attrs.guarantee_key`.
- **testes**: 004-D1, 004-D2, 004-N1, 004-N2, 004-N3, 004-N4

---

### RULE-005

- **rule_id**: RULE-005
- **rule_class**: NORMATIVE
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Regras aplicáveis de recebimento dos bens ausentes ou insuficientemente definidas.
- **escopo**: Todo TR do perfil. Aceita rito provisório/definitivo, recebimento simultâneo explicitamente definido ou declaração fundamentada de não aplicabilidade de uma etapa. Mera citação da Lei não basta.
- **fundamento_normativo**: Lei nº 14.133/2021, art. 140, II, a e b, e art. 40, § 1º, II.
- **severidade**: HIGH
- **entrada**: seções `gestao`, `medicao_pagamento` e campos estruturados de recebimento.
- **funcao_de_deteccao**:
  1. `normal_ok`: o TR distingue provisório (forma sumária, no ato da entrega ou prazo definido, com responsável) e definitivo (verificação de conformidade, responsável e termo detalhado ou prazo de ateste).
  2. `simultaneo_ok`: o TR declara que as etapas ocorrerão no mesmo ato para o objeto indicado e define responsável, verificação de conformidade e registro/termo do recebimento. Simultaneidade não pode ser inferida apenas de um prazo igual.
  3. `nao_aplicavel_ok`: o TR identifica expressamente a etapa não aplicável, apresenta justificativa ligada às características do objeto e define como ocorrerá o aceite aplicável, com responsável e verificação. `Não se aplica` isolado não basta.
  4. Placeholder em responsável, prazo, método ou termo não preenche o componente. Disparar com `attrs.falta` indicando os componentes insuficientes.
  5. Silenciar se um dos três modos estiver completo; caso contrário, disparar.
- **nao_dispara**: rito normal completo; recebimento simultâneo completo; não aplicabilidade fundamentada com rito alternativo completo.
- **dispara apesar de**: mera remissão ao art. 140; nomeação isolada de fiscal; pagamento após NF; template com `XXXX`, colchetes ou campos a preencher.
- **finding**: evidência e `attrs.mode = normal | simultaneo | nao_aplicavel | indefinido`, com `attrs.falta`.
- **testes**: 005-D1, 005-D2, 005-D3, 005-D4, 005-N1, 005-N2, 005-N3

---

### RULE-006

- **rule_id**: RULE-006
- **rule_class**: ADVISORY
- **category**: INTEGRITY
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Referência a anexo ou apêndice do TR não resolvida no pacote documental disponível.
- **escopo**: Referências que afirmam integrar o TR. O arquivo referido pode estar incorporado ao TR ou separado no mesmo pacote. Não resolve anexos de edital, ETP, contrato ou ata declarados como outros instrumentos.
- **fundamento_normativo**: não se aplica — controle de integridade documental, sem conclusão de compliance normativo.
- **rationale**: uma referência não resolvida pode ocultar conteúdo necessário à revisão; a checagem apenas solicita conferência do pacote.
- **severidade**: MEDIUM
- **entrada**: texto do TR, headings/blocos de anexo e `PackageFile[]` do pacote.
- **funcao_de_deteccao**:
  1. Extrair âncoras (`Anexo I`, `Anexo 3`, `Apêndice A`) e eventual nome de arquivo.
  2. Ignorar referências explícitas a outro instrumento.
  3. Resolver primeiro contra títulos/blocos do TR e depois contra arquivos/manifesto do pacote. Romanos = arábicos.
  4. Emitir advisory uma vez por âncora não resolvida, sem afirmar que o anexo inexiste fora do pacote observado.
- **nao_dispara**: anexo incorporado; anexo em arquivo separado do pacote com âncora correspondente; menção genérica `anexos, se houver`; referência extra-TR explícita.
- **finding**: `rule_class: ADVISORY`, âncora, arquivos examinados e `attrs.anchor`.
- **testes**: 006-D1, 006-N1, 006-N2, 006-N3, 006-N4

---

### RULE-007

- **rule_id**: RULE-007
- **rule_class**: NORMATIVE
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: O mesmo item tem, em seções distintas do TR, valores incompatíveis para o mesmo atributo extraído.
- **escopo**: Contradição estruturada no próprio TR. Compara `Requirement` e `FieldValue` já extraídos. Contradição apenas prosaica, sem campos, é R9.
- **fundamento_normativo**: Lei nº 14.133/2021, art. 6º, XXIII, a, e art. 40, V, a.
- **severidade**: HIGH
- **entrada**: `Requirement` e `FieldValue` com `item_id`, `atributo` e, para catálogo, conceito normalizado.
- **funcao_de_deteccao**:
  1. Agrupar por `(item_id, atributo)`: material, tipo construtivo, dimensão, CATMAT, voltagem, capacidade, quantidade de componentes ou marca vinculante.
  2. Disparar se dois valores normalizados não podem ser verdadeiros ao mesmo tempo.
  3. Para CATMAT, código bruto diferente não basta: disparar apenas se o mapeamento determinístico indicar conceitos incompatíveis. Códigos diferentes ligados ao mesmo conceito ou a descrições semanticamente compatíveis não geram finding.
  4. Não disparar se B refina A (`aço nº 24` vs `aço nº 24 com pintura eletrostática`).
  5. Não comparar itens distintos. Marca de referência com equivalentes admitidos não conflita com ausência de marca em outra seção.
- **nao_dispara**: detalhamento compatível; atributos diferentes; itens distintos; CATMAT diferente mas com `normalized_concept_id` igual/compatível; CATMAT sem mapeamento suficiente para provar incompatibilidade.
- **finding**: os dois trechos, `item_id`, `atributo`, valores e conceito normalizado usado.
- **testes**: 007-D1, 007-D2, 007-N1, 007-N2, 007-N3

---

### ADVISORY-008

- **rule_id**: ADVISORY-008
- **legacy_id**: RULE-008 (aposentado)
- **rule_class**: ADVISORY
- **category**: QUALITY
- **profile_id**: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **descricao**: Requisito técnico objetivamente aferível sem critério, documento ou método de comprovação explicitado.
- **escopo**: Controle opcional de qualidade editorial, fora da R8 normativa. Só requisito objetivamente verificável usado como filtro de proposta, habilitação ou recebimento. Especificação ordinária do bem não entra; expressão vaga pertence à R9.
- **fundamento_normativo**: não se aplica — não é teste automático de compliance municipal.
- **rationale**: explicitar a forma de verificação reduz dúvida operacional, mas a ausência não autoriza conclusão normativa determinística.
- **severidade**: MEDIUM
- **entrada**: `Requirement` do TR.
- **funcao_de_deteccao**:
  1. O requisito é aferível se o valor extraído casa com a allowlist: norma técnica nomeada como desempenho/conformidade; certificação; ou métrica de ensaio (Joules, SRC, UPF/UV, classe de inflamabilidade, IP).
  2. Há critério relacionado se o mesmo item aponta laudo, certificado, ensaio/norma de ensaio como método, amostra/prova de conceito ou comprovação ligada a documento idôneo.
  3. Emitir advisory se (1) e não (2).
- **nao_dispara**: requisito aferível com método; especificação descritiva comum; ambiguidade sem métrica; controle advisory desabilitado.
- **finding**: `rule_class: ADVISORY`, requisito e ausência de método.
- **testes**: 008-D1, 008-D2, 008-N1, 008-N2, 008-N3

---

## 7. O que este catálogo recusa

- Usar IN nº 81/2022, modelo AGU ou TR Digital como fundamento municipal ou como determinante de `SUPPORTED`.
- Julgar preço, razoabilidade ou legalidade do processo.
- Inferir seção obrigatória por similaridade semântica frouxa.
- Tratar vigência como prazo de entrega (RULE-003).
- Exigir garantia quando não aplicável (RULE-004).
- Confundir anexo ausente no mesmo arquivo com anexo ausente no pacote (RULE-006).
- Tratar advisory de integridade ou qualidade como finding normativo.
- Classificar contradição puramente linguística (RULE-007 vs R9).
- Tratar `alta qualidade` ou subjetividade como ADVISORY-008.
- Apontar restrição de mercado sem os dados e controles próprios; nunca converter automaticamente o risco em juízo de ilegalidade.

Qualquer controle `NORMATIVE` novo precisa de dispositivo expresso da Lei nº 14.133/2021 e de testes neste perfil. Referências `REFERENCE_ONLY` podem enriquecer comparação, nunca suprir a base vinculante.
