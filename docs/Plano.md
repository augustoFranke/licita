# Roadmap executável — M0 → M1 (e depois M2–M6)

Fonte de verdade do produto: [`README.md`](README.md) e `00`–`04`.
Este arquivo é o caminho de construção. Em divergência de escopo, prevalece o
perfil exclusivo de `scope.md`; nos demais pontos, vale o pack.

- **M0** = R1–R6 (F-01–F-04)
- **M1** = R7–R10 (F-05, F-06, F-11, F-12)
- **M2–M6** só depois da saída de R10 verde, na ordem de `04`

A numeração antiga “v1” = fatia M0–M1, não o produto completo.
O perfil exclusivo `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS` vale para o produto
atual inteiro: esfera municipal (`M`), Lei nº 14.133/2021, Pregão Eletrônico
(`PE`) e aquisição de bens. Escopo binário: [`scope.md`](scope.md).

---

## Contrato de fase

Cada R tem **entrada**, **saída** e **fora**. Tudo binário: sim ou não.

| Lista | Função |
|---|---|
| **Entrada** | Artefato congelado da fase anterior. Se faltar, esta R **não começa**. |
| **Saída** | O que *esta* R produz e como se prova. Se faltar, esta R **não fecha**. |
| **Fora** | O que esta R **não** conserta. Falha de fase anterior não muda de nome aqui. |

**Bloqueio:** R(n+1) não começa enquanto a saída de Rn não estiver verde.
Não há “quase”. Métrica de outra fase não conta nesta.

Prova da saída: checklist versionado neste arquivo + testes/CI quando o artefato for código ou schema. Relato informal não fecha gate.

---

## R0 — Perfil exclusivo

**Entrada:** pack `00`–`04` vigente.

**Saída**
- `scope.md` responde `SUPPORTED` ou `OUT_OF_SCOPE` sem “depende” e restringe
  todo o produto atual a `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`.
- PE está definido como Pregão Eletrônico; PNCP e Compras.gov estão registrados
  somente como canais.
- A única base normativa vinculante é a Lei nº 14.133/2021. IN SEGES/ME nº
  81/2022, modelos de TR da AGU e TR Digital são `REFERENCE_ONLY`: nunca
  determinam escopo ou finding.
- Overlay municipal permanece inativo enquanto uma norma local aplicável não
  estiver expressamente identificada e versionada.

**Fora:** não coleta corpus; não implementa engine; não presume norma local.

**Só então → R1.**

---

## R1 — Corpus real

Pares ETP→TR reais, reproduzíveis. Operação: [`corpus/README.md`](../corpus/README.md).

**Entrada:** saída de R0.

**Saída**
- `licita-gate` verde sobre os elegíveis: ≥15 processos, com alvo 20; cada um
  tem exatamente 1 ETP e 1 TR, ambos reabertos localmente, texto utilizável e
  relação `ETP → TR` catalogada.
- Cada elegível tem esfera `M`, Lei nº 14.133/2021, modalidade PE, objeto de
  aquisição de bens e perfil `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`.
- Diversidade calculada somente sobre elegíveis: ≥5 CNPJs, ≥3 categorias e
  ≤5 processos por CNPJ.
- Metadados: CNPJ/órgão, processo, data, objeto, categoria, perfil, esfera,
  modalidade, URLs/fontes e hashes.
- Os 28 atuais permanecem fisicamente: 27 elegíveis e o SAEMA energia como
  controle negativo municipal `OUT_OF_SCOPE` / `FORA_DO_PERFIL` por objeto.
  O controle não entra em R2 nem em nenhum denominador ou métrica de elegíveis.
- Pipeline reproduzível a partir do estado em `corpus/estado/` (falha de API
  não vira lista vazia), sob a policy `4-municipal-historical-ocr`.
- Comando do gate: `--processos 15 --orgaos 5 --categorias 3
  --max-por-orgao 5 --esferas M`.

**Fora**
- Não baixa edital/contrato/DFD (tipos do produto, não deste lote).
- Não classifica qualidade do TR.
- Não usa processos inelegíveis para fechar quantidade ou diversidade.
- PNCP e Compras.gov, como canais, não comprovam sozinhos o enquadramento.

**Só então → R2.**

---

## R2 — Modelo estruturado

Schema versionado que M0–M1 usa sem voltar ao texto livre.

**Entrada:** saída de R1 (lote elegível existe; schema ainda não precisa dos 15).

**Saída**
- Schema Pydantic + JSON Schema vigente valida contra os enums de `01` (`Document.type`, `Finding.severity`, `Finding.status`, revisão `EXTRACTED|CONFIRMED|REJECTED`).
- Entidades de `00` F-03 representáveis (`FieldValue` / `Requirement` conforme `04`).
- 5 processos **reais e elegíveis** do lote convertidos manualmente ao schema, `valid: true`.
- Campos que R7/R8 vão comparar (quantidade, unidade, prazo de entrega, vigência, garantia, especificação, local, valores comparáveis) existem **sem** prosa como único suporte.
- Testes de schema no CI.

**Fora**
- Não extrai automaticamente (R5).
- Não anota o golden completo (R4).
- O controle negativo SAEMA e qualquer `FORA_DO_PERFIL` não são convertidos.
- Perfil, esfera, hashes e metadados de OCR ficam no catálogo/manifesto externo,
  não como novos campos do payload `ProcurementProcess`.

**Só então → R3.**

---

## R3 — Ingestão documental

`arquivo → blocos` com âncora navegável.

**Entrada:** schema de R2; arquivos e hashes de R1.

**Saída**
- Em 10 processos elegíveis do lote, ≥95% dos trechos que R4 precisará para
  quantidade, especificação, prazo e garantia reabrem: `document_id`, página
  ≥1, `block_id`, `quote` substring do bloco.
- SHA-256 dos bytes do arquivo original conferido; original imutável.
- OCR pode ser aplicado a qualquer arquivo e é cacheável por `SHA-256 do
  original + idioma + versão/configuração`. A saída é artefato derivado
  auditável, com hash e proveniência, e nunca substitui o original.
- Parse/OCR falho é **explícito** (NFR-002). Zero falha silenciosa no conjunto
  medido. Arquivo sem texto utilizável após OCR → processo `OUT_OF_SCOPE`, não
  texto inventado.

**Fora**
- Não cria `Item` / `Requirement` / `Finding`.
- Não corrige OCR “de olho” nem altera o original.
- Não classifica o TR.

**Só então → R4.**

---

## R4 — Golden dataset

Oráculo de extração. Política: [`r4/GUIA.md`](../r4/GUIA.md), formato [`r4/FORMATO.md`](../r4/FORMATO.md).

**Entrada:** blocos de R3 nos processos a anotar; schema de R2.

**Saída**
- 10–15 processos reais e elegíveis anotados; exemplo sintético, controle
  negativo SAEMA e qualquer `FORA_DO_PERFIL` **não** contam.
- ≥300 valores/requisitos com evidência navegável.
- Split `dev` / `eval` congelado **por processo** (nenhum documento do mesmo processo nos dois).
- Duas leituras consecutivas não revelam campo ambíguo sem decisão já escrita no `GUIA`.
- Manifesto/catálogo externo com split, perfil, esfera `M`, hashes dos
  originais, versão da policy `4-municipal-historical-ocr` e, quando houver,
  idioma, versão/configuração e hash do artefato OCR. Payload fechado =
  `ProcurementProcess` vigente, sem campos de esfera, perfil, hash ou OCR.

**Fora**
- Não treina extrator (R5).
- Não “conserta” o documento-fonte.
- Não avalia linter (R8) nem consistência (R7), salvo registrar conflito visível como `Finding` `OPEN`.
- `eval` não é lido para ajustar política, prompt ou regra.

**Só então → R5.**

---

## R5 — Requirements Engine

`blocos → structured procurement` automático.

**Entrada:** golden R4 com `eval` congelado; ingestão R3.

**Saída** (medida **só** no `eval`, nunca no `dev`)
- Quantidade / prazo / garantia: precisão ≥97%, recall ≥90%.
- Requisitos técnicos: precisão ≥90%.
- 100% das extrações têm evidência navegável até o bloco de R3.
- Saída valida no schema (LLM sem prosa solta).
- Status inicial = `EXTRACTED` (ainda não é verdade de motor).

**Fora**
- Não confirma extração (R6).
- Não emite finding de consistência/linter.
- Erro de ingestão (bloco ausente) é falha de R3, não de recall de R5.
- Reabrir `eval` para “melhorar o número” invalida a saída.

**Só então → R6.**

---

## R6 — Human Review

Primeira UI. Só dados `CONFIRMED` alimentam R7–R9.

**Entrada:** extração R5 no schema; evidências clicáveis (R3).

**Saída**
- Pessoa que **não** desenvolveu o sistema importa um processo do lote e aceita/edita/rejeita **todos** os campos visíveis sem editar JSON nem banco.
- `CONFIRMED` exige evidência (FR-013). `REJECTED` conserva o valor extraído original.
- Audit log: usuário, timestamp, anterior, posterior.
- Downstream (API/relatório de extração) expõe o último `CONFIRMED`, nunca um `REJECTED` como fato.

**Ferramentas desta fatia:** FastAPI + PostgreSQL + HTML/CSS/JS vanilla. Sem framework de frontend.

**Fora**
- Não implementa linter nem consistência.
- Não é UI de agentes.
- Não “corrige” o PDF.

**Só então → R7.**

---

## R7 — Consistency Engine [C]

Compara valores **já confirmados** (ou golden R4 no lugar da UI, em teste).

**Entrada:** valores `CONFIRMED` (R6) ou anotações R4; pares de documentos existentes. Ausência de DFD/edital/contrato ≠ inconsistência.

**Saída**
- Compara: ETP↔TR; TR↔edital; edital↔contrato; TR↔contrato; DFD↔ETP se houver DFD (FR-030–036).
- Campos: quantidade, unidade, prazo de entrega, vigência, garantia, especificação, local, valores comparáveis.
- Suíte de mutações sobre o golden: ≥95% das inconsistências determinísticas **injetadas** detectadas; ≤5% FP nessa suíte; 100% dos findings com evidência **bilateral**.
- Finding usa enums de `01`. Extração errada **não** vira finding de consistência: se o valor confirmado/anotado está certo e o motor diverge, é bug de R7; se o valor extraído estava errado e não confirmado, a suíte não roda.

**Fora**
- Não julga mercado, preço nem legalidade.
- Não compara texto bruto se existir `CONFIRMED`.
- LLM só para equivalência semântica inevitável; igualdade numérica/unidade/data é determinística (FR-104).

**Só então → R8.**

---

## R8 — TR Linter determinístico [B]

Catálogo: [`rules_draft.md`](rules_draft.md). Casos: [`rules_synthetic_tests.md`](rules_synthetic_tests.md).

**Entrada:** TR estruturado `CONFIRMED` ou fixture sintético no schema; perfil
`MUNICIPAL_14133_PREGAO_ELETRONICO_BENS` de `scope.md`. Processo
`FORA_DO_PERFIL`, inclusive o controle negativo SAEMA, não entra na prova.

**Saída**
- Os 8 controles determinísticos do catálogo estão implementados: 6 `NORMATIVE`
  (RULE-001–005 e RULE-007) e 2 `ADVISORY` (RULE-006 e ADVISORY-008; o ID
  histórico RULE-008 fica aposentado).
- 100% dos casos D/N do markdown rodam no pytest e batem o esperado
  (`finding` | `advisory` | `silencio`).
- Todo controle tem `rule_id`, `rule_class`, severidade `HIGH|MEDIUM` e
  `nao_dispara`. Controle `NORMATIVE` usa fundamento somente na Lei nº
  14.133/2021; controle `ADVISORY` declara rationale e não alega compliance.
- Nenhuma regra normativa entra sem artigo da Lei no catálogo **e** caso de
  teste. Materiais `REFERENCE_ONLY` nunca fundamentam nem disparam finding.

**Fora**
- Não faz FR-021/027/R9 (ambiguidade/subjetividade).
- Não faz FR-026 sem dados de F-07 (M2).
- Não emite `INFO`.
- Não diz “ilegal” / “aprovado”.
- Não resolve anexo de outro documento da cadeia (isso é R7).

**Só então → R9.**

---

## R9 — TR Linter semântico [B]

FR-021, FR-022, FR-027 e contradição só linguística.

**Entrada:** R8 verde no CI; TR com evidências; harness de eval.

**Saída**
- ≥100 findings semânticos rotulados por humano (relevante | irrelevante).
- ≥85% dos emitidos são relevantes; ≥90% de precisão nos `HIGH`; nenhum `HIGH` sem evidência.
- `HIGH` semântico só aparece depois do validation pass (FR-105).
- Structured output no schema de finding.

**Fora**
- Não substitui RULE-001–008. Se a regra determinística resolve, ela prevalece (FR-104).
- Não conclui ilegalidade.
- Não usa o conjunto rotulado para “ensinar” e depois medir no mesmo conjunto.

**Só então → R10.**

---

## R10 — M1 integrado

Compõe R3–R9 num fluxo. **Não refaz** as métricas de extração/linter/consistência: elas continuam verdes. Se alguma reabrir, R10 não está verde.

**Entrada:** saídas de R3, R5, R6, R7, R8, R9 verdes.

**Saída**
- 10 processos **inéditos, elegíveis e municipais** (fora de `dev` e `eval` da
  R4) sobem pelo app: importar → extrair → revisar → consistência → linter det.
  → linter sem. → findings → reprocessar após correção → exportar relatório.
  Os 27 elegíveis atuais devem deixar 10 inéditos após o split; se uma divisão
  futura consumir esse saldo, R10 aguarda nova expansão. O controle SAEMA
  nunca completa a meta.
- Cada execução conserva o perfil exclusivo e não usa referência orientativa
  como fundamento de finding.
- Zero perda silenciosa de documento ou artefato OCR.
- 100% dos findings `HIGH` e `MEDIUM` têm evidência navegável (NFR-001).
- Reprocessamento recalcula só o que a correção afeta (FR-084), sem apagar audit log.
- Quem não é desenvolvedor conclui o fluxo sem editar JSON/banco.

**Fora**
- Não implementa F-07–F-10, F-13–F-15.
- Não mede mercado nem preço.
- Redução de tempo de revisão (≥30% mediano em ≥5 TRs, contra método manual) é **métrica de produto**, não bloqueia M2. Correção bloqueia; velocidade não.

**Quando a saída de R10 estiver verde:** M2 (F-07 + F-14 parcial), depois M3–M6.

Fluxos: [`03_USAGE_FLOWS.md`](03_USAGE_FLOWS.md). M1 = compilador/pre-flight; não substitui decisão humana.

---

## Stack desta fatia

Python, FastAPI, PostgreSQL, Pydantic, PyMuPDF, python-docx, pytest, RapidFuzz, LLM com structured output.

Sem vector DB, agentes, RAG framework ou microservices **em M0–M1**, salvo problema concreto. F-14 entra em M2, interno, sem UI de agentes.

Frontend M1: HTML/CSS/JS vanilla.

Fonte normativa vinculante: somente Lei nº 14.133/2021.
`REFERENCE_ONLY`: IN SEGES/ME nº 81/2022, modelos de TR da AGU e TR Digital;
nunca determinam `SUPPORTED` nem finding. Overlay municipal futuro exige norma
local expressamente identificada.
Canais de dados públicos (não normativos): PNCP, Compras.gov.
