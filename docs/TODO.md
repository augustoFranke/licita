# Pendências após o fechamento da R3

Estado verificado em 2026-09-04: R1, R2 e R3 estão verdes. A R1 mantém 20 processos recolhidos
sob a policy `8-cadeia-completa-documentos-utilizaveis`. Cada processo possui
exatamente um ETP, um TR, um Edital e um instrumento contratual utilizáveis.
O gate foi executado com o alvo 20 e passou.

As próximas tarefas seguem a ordem obrigatória de `Plano.md`. Uma fase não
começa enquanto a anterior não fechar seu gate.

## Preservação operacional

- [ ] Copiar `corpus/documentos/` e `corpus/estado/etp_tr.sqlite3` para um
  backup fora deste Mac e conferir os hashes. Esses dados são ignorados pelo
  Git; o snapshot local em `.recovery/r1-fechado-20260904/` protege apenas
  contra alterações locais, não contra perda do disco.

## R2 — Modelo estruturado

- [x] Converter manualmente cinco processos reais das 20 cadeias completas
  atuais para `ProcurementProcess`.
- [x] Validar os cinco payloads pelo modelo Pydantic e pelo JSON Schema.
- [x] Demonstrar nos payloads o suporte estruturado aos campos que R7 e R8
  compararão, sem depender de prosa como única representação.
- [x] Criar um gate de R2 que confira a origem dos cinco IDs no lote policy 8.

Gate: `39 passed` em `tests/test_r2_current_lot.py`,
`tests/test_r2_annotations.py` e `tests/test_schema.py`. Os artefatos atuais
ficam em `r2/data/`; os dez payloads históricos em `r4/data/` não foram usados
para fechar esta fase.

## R3 — Ingestão documental

- [x] Selecionar dez processos elegíveis do lote policy 8 e medir a cobertura
  dos trechos necessários para quantidade, especificação, prazo e garantia.
- [x] Atingir pelo menos 95% de reabertura desses trechos, com página,
  `block_id`, citação literal e SHA-256 do original.
- [x] Atualizar `corpus/GATE_R3.md` com o denominador explícito das quatro
  categorias em cada um dos dez processos.

Gate: `1 passed` em `tests/test_r3_current_lot.py`; 40 de 40 trechos manuais
foram reabertos (`100%`) depois da conferência dos hashes dos originais.

## R4 — Golden dataset

- [x] Anotar de 10 a 15 processos reais e elegíveis, com pelo menos 300
  valores ou requisitos e evidência navegável.
- [ ] Substituir os cinco processos de `eval` já expostos ao benchmark R5 por
  cinco processos elegíveis nunca medidos; só então congelar o split e registrar policy, esfera,
  hashes e proveniência no manifesto externo.
- [ ] Fazer duas leituras consecutivas e incorporar no guia todas as decisões
  necessárias para campos ambíguos.

Estado auditado: o conjunto ativo tem dez processos e 392 valores/requisitos, sem
nenhuma procedência `engine_generated`. O antigo processo contaminado foi
retirado de `eval` e preservado somente como candidato histórico. Seu substituto
foi anotado diretamente das fontes com 80 registros. Porém, os cinco processos
de `eval` foram expostos a uma execução prematura do benchmark R5 e não podem
mais servir de holdout. Ainda faltam um novo `eval` nunca medido, a leitura B
cega e a adjudicação por revisor distinto; até isso ocorrer, R4 permanece
parcial e R5 não começa. Ver `r4/GATE_R4.md`.

Os cinco substitutos já reservados, com ETP e TR reabertos sem depender do
motor R5, são: `87613048000153-1-000119-2024`,
`83024240000153-1-000099-2024`, `52061181000160-1-000057-2024`,
`88814181000130-1-000180-2024` e `88814181000130-1-000098-2024`.
Ainda falta produzir a leitura A desses processos, migrar o `eval` exposto para
`dev` e congelar o novo split sem executar R5.

## R5 — Requirements Engine

- [ ] Medir somente no `eval` congelado: precisão e recall de quantidade,
  prazo e garantia, precisão de requisitos técnicos, evidência navegável e
  validade do schema nos pisos definidos em `Plano.md`.

## R6 — Revisão humana

- [ ] Validar o fluxo completo com uma pessoa que não desenvolveu o sistema,
  usando PostgreSQL: importar, aceitar, editar e rejeitar todos os campos sem
  editar JSON ou banco, preservando evidência e audit log.

## R7 — Consistência

- [ ] Executar a suíte de mutações sobre o golden confirmado e provar pelo
  menos 95% de detecção, no máximo 5% de falsos positivos e evidência bilateral
  em todos os achados.

## R8 — Linter determinístico

- [ ] Fechar no CI os oito controles do catálogo e todos os casos D/N, com
  classe, severidade, condição de não disparo e fundamento permitido.

## R9 — Linter semântico

- [ ] Produzir e congelar pelo menos 100 findings rotulados por humano em
  conjuntos separados de ajuste e avaliação.
- [ ] Demonstrar pelo menos 85% de relevância geral, 90% de precisão em `HIGH`
  e evidência em todo `HIGH`, incluindo o passe de validação.

## R10 — M1 integrado

- [ ] Rodar com uma pessoa não desenvolvedora dez processos municipais
  inéditos fora de `dev` e `eval`, do upload ao relatório e ao reprocessamento,
  sem perda silenciosa e sem apagar o audit log.
- [ ] Confirmar evidência navegável em 100% dos findings `HIGH` e `MEDIUM`.
