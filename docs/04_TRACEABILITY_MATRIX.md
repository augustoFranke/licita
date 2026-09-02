# Traceability Matrix — Features, Requirements, Stories and Flows

Este arquivo é a referência para verificar se uma feature possui:
1. especificação;
2. requisito funcional;
3. história de usuário;
4. fluxo operacional;
5. ator humano responsável.

## Premissas transversais

O único perfil atual é `PUBLICO_14133_PREGAO_ELETRONICO_BENS`: qualquer esfera (`F`/`E`/`D`/`M`), Lei 14.133/2021, **Pregão Eletrônico** (`PE`, não Pernambuco) e aquisição de bens comuns. FR-006 antecede F-02–F-15: somente `SUPPORTED` entra em corpus aprovado, denominadores, comparáveis ou engines; `OUT_OF_SCOPE` pode ser retido apenas em trilha segregada de rejeição/auditoria.

Originais são imutáveis e têm hash obrigatório sobre seus bytes. OCR é derivado auditável, com motor, idioma, confiança e hash ou versão do resultado. Toda análise usa documentos ativos/utilizáveis e dados confirmados, expõe evidência e filtros de esfera/perfil e termina em decisão humana. Exportações preservam perfil, filtros, exclusões, hashes e versões.

A base normativa vinculante deste perfil é a Lei 14.133/2021. IN SEGES/ME nº 81 e modelos AGU/TR Digital são `REFERENCE_ONLY`; não determinam escopo nem sustentam isoladamente finding normativo. A plataforma não certifica legalidade.

---

| Feature | Nome | Requisitos | User Stories | Fluxo principal | Atores |
|---|---|---|---|---|---|
| F-01 | Workspace | FR-001, FR-005, FR-006 | US-001, US-004 | Flows 2, 3 | P-02 |
| F-02 | Document Intelligence | FR-002–004 | US-002, US-072 | Flows 3, 4, 8 | P-02 |
| F-03 | Requirements Engine | FR-010–013 | US-003 | Flows 3, 9, 10 | P-02, P-03, P-04 |
| F-04 | Human Review | FR-014 | US-003 | Flows 3, 9, 10 | P-02, P-03, P-04 |
| F-05 | TR Quality Linter | FR-020–027 | US-010–012 | Flow 4 | P-02, P-04 |
| F-06 | Consistency Engine | FR-030–036 | US-020–024 | Flows 4, 9, 10 | P-01, P-02, P-03 |
| F-07 | Market Feasibility | FR-040–046 | US-030–032, US-041 | Flows 5, 6 | P-02 |
| F-08 | Historical/Obsolescence | FR-050–055 | US-040–042 | Flow 6 | P-02, P-04 |
| F-09 | Price Intelligence | FR-060–064 | US-050–052 | Flow 7 | P-02 |
| F-10 | Requirement Traceability | FR-070–074 | US-012, US-021, US-042, US-060–062 | Flows 4, 6, 9, 10, 11 | P-03, P-04, P-05 |
| F-11 | Compliance & Risk | FR-080 | US-013, US-070, US-072, US-091 | Flows 4, 8 | P-02, P-04 |
| F-12 | Collaboration & Audit | FR-081–084 | US-013, US-023, US-071, US-072 | Flows 4, 8, 12 | P-02, P-04 |
| F-13 | Fiscalization | FR-090–093 | US-062, US-080–082 | Flow 11 | P-05 |
| F-14 | Agentic Pipeline | FR-100–105 | US-090, US-091 | Flows 5, 6, 13 | P-02, P-04, P-06 |
| F-15 | Integrations & Export | FR-110–111, FR-064 | US-052, US-100, US-101 | Flows 7, 14 | P-02, P-06 |

---

Grafo de dependência: `00_PRODUCT_SPEC.md` §4.

---

# Ordem sugerida de construção

Correspondência com `Plano.md`: R1–R6 → M0; R7–R10 → M1; após R10 → M2–M6.
Assistência automática à redação de cláusulas **não** está em `00`–`04`.

Milestone indica ordem e alvo, não disponibilidade automática. Uma feature ou ação de UI ainda não aceita pelo DoD permanece indisponível e não pode exibir dado sintético como resultado real.

## R1-M-GATE — Corpus multiesfera mínimo

Este gate fecha o corpus aprovado de R1 somente quando **todos** os critérios forem atendidos em conjunto:

- pelo menos **15 processos elegíveis** no perfil `PUBLICO_14133_PREGAO_ELETRONICO_BENS`;
- pelo menos **5 CNPJs distintos** de órgãos/entidades entre os processos elegíveis;
- pelo menos **3 categorias** entre os processos elegíveis;
- no máximo **5 processos elegíveis por CNPJ**;
- em cada nova coleta, exatamente **1 ETP, 1 TR, 1 Edital e 1 instrumento contratual ativos/utilizáveis**, com as relações consecutivas verificáveis; processos históricos apenas com ETP/TR permanecem preservados;
- hash conferido para cada arquivo original; quando houver OCR, derivado auditável com motor, idioma, confiança e hash ou versão do resultado, sem alteração do original;
- filtros de perfil aplicados antes da contagem. Registros fora do perfil podem constar na trilha de rejeição/auditoria, mas não contam nos 15 elegíveis, nos denominadores nem como entrada de analisadores.

O teto por CNPJ e a diversidade mínima de CNPJs/categorias são controles de composição do **corpus R1**, não limites do produto em uso. Um workspace suportado não é rejeitado por o produto já possuir mais processos do mesmo CNPJ ou por pertencer a categoria já existente.

## Milestone M0 — Fundação
- F-01
- F-02
- F-03
- F-04

**Resultado:** transformar processo em dados confiáveis.

## Milestone M1 — Primeira utilidade real
- F-05
- F-06
- F-11
- F-12

**Resultado:** revisar TR e consistência documental.

## Milestone M2 — Mercado
- F-07
- F-14 parcial

**Resultado:** avaliar aderência/competitividade da especificação.

## Milestone M3 — Histórico + preço
- F-08
- F-09

**Resultado:** compreender origem, obsolescência e custo.

## Milestone M4 — Rastreabilidade
- F-10

**Resultado:** acompanhar requisito por todo o processo.

## Milestone M5 — Execução
- F-13

**Resultado:** conectar planejamento à fiscalização.

## Milestone M6 — Integrações institucionais
- F-15

**Resultado:** exportar e conectar sistemas institucionais sem quebrar o workspace local.

---

# Definition of Done por feature

Uma feature só é considerada concluída quando:

- possui schema de entrada e saída;
- possui testes, inclusive bloqueio de `OUT_OF_SCOPE` e segregação de denominadores;
- valida FR-006 antes de processamento de domínio e demonstra o perfil e a esfera ativos;
- opera somente sobre documentos ativos/utilizáveis e dados confirmados quando aplicável;
- preserva o original e seu hash; OCR, quando usado, é derivado versionado/auditável com motor, idioma e confiança;
- possui evidência navegável quando produz valor, comparação, finding ou conclusão;
- possui tratamento explícito de erro;
- possui versão;
- aparece em pelo menos uma história de usuário;
- aparece em pelo menos um fluxo com ator responsável e decisão humana;
- consultas e contagens exibem filtros de esfera/perfil e exclusões; exports carregam perfil, filtros, hashes e versões;
- distingue regra `NORMATIVE` aplicável da fonte `REFERENCE_ONLY`, sem alegar certificação legal;
- possui telemetria mínima;
- pode ser demonstrada usando um processo real `SUPPORTED`;
- permanece indisponível na UI até satisfazer este DoD;
- não depende de edição manual de banco/JSON para o fluxo normal.

Para R1, o DoD inclui ainda o `R1-M-GATE` integral acima; nenhuma média compensa falha em um de seus critérios.

---

# Cobertura de A/B/C/D

| Thread | Features |
|---|---|
| A — Mercado | F-07, F-09 |
| B — Qualidade do TR | F-05 |
| C — Consistência | F-06, F-10 |
| D — Histórico/reutilização | F-08 |
| Infraestrutura transversal | F-01, F-02, F-03, F-04, F-11, F-12, F-14, F-15 |
| Pós-contratação | F-13 |

---

# Regra de produto

Nenhuma feature A/B/C/D deve operar diretamente sobre texto bruto quando houver representação estruturada confirmada disponível. Nenhuma delas recebe processo ou documento `OUT_OF_SCOPE`.

Fluxo preferido:

`perfil → FR-006 → original + hash → parsing/OCR derivado → extração + evidência → confirmação → engine filtrada → finding → decisão humana → exportação auditável`

## Mapeamento F-03 → persistência

| Conceito em `00` | Representação persistida |
|---|---|
| `Quantity` | `FieldValue` `QUANTITY` |
| `Deadline` | `FieldValue` `DELIVERY_DEADLINE` / `CONTRACT_TERM` / `RECEIPT_DEADLINE` / `PAYMENT_DEADLINE` |
| `Warranty` | `FieldValue` `WARRANTY_TERM` |
| `AcceptanceCriterion` | `Requirement` `receipt.*` / `measurement.*` |
| `Obligation` | `Requirement` `execution.*` |
| `PaymentCondition` | `Requirement` `payment.*` + `FieldValue` `PAYMENT_DEADLINE` |
| revisão humana | `EXTRACTED` → `CONFIRMED` \| `REJECTED` |
