# Pendências após o fechamento da R1

Estado verificado em 2026-09-04: a R1 está verde com 20 processos recolhidos
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

- [ ] Converter manualmente cinco processos reais das 20 cadeias completas
  atuais para `ProcurementProcess`.
- [ ] Validar os cinco payloads pelo modelo Pydantic e pelo JSON Schema.
- [ ] Demonstrar nos payloads o suporte estruturado aos campos que R7 e R8
  compararão, sem depender de prosa como única representação.
- [ ] Criar um gate de R2 que confira a origem dos cinco IDs no lote policy 8.

Os dez payloads existentes em `r4/data/` validam no schema, mas nenhum dos IDs
pertence às 20 cadeias completas atuais; portanto, eles não fecham a nova R2.

## R3 — Ingestão documental

- [ ] Selecionar dez processos elegíveis do lote policy 8 e medir a cobertura
  dos trechos necessários para quantidade, especificação, prazo e garantia.
- [ ] Atingir pelo menos 95% de reabertura desses trechos, com página,
  `block_id`, citação literal e SHA-256 do original.
- [ ] Atualizar `corpus/GATE_R3.md`: a prova existente confirma 54 de 54
  âncoras escolhidas por leitura, mas não mede o denominador de cobertura.

## R4 — Golden dataset

- [ ] Anotar de 10 a 15 processos reais e elegíveis, com pelo menos 300
  valores ou requisitos e evidência navegável.
- [ ] Congelar o split `dev`/`eval` por processo e registrar policy, esfera,
  hashes e proveniência no manifesto externo.
- [ ] Fazer duas leituras consecutivas e incorporar no guia todas as decisões
  necessárias para campos ambíguos.

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
