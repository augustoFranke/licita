# Requirements — TR Intelligence Platform

**Convenção:**  
- `FR-*`: requisito funcional  
- `NFR-*`: requisito não funcional  
- `AC`: critério de aceite  
- `F-*`: feature definida em `00_PRODUCT_SPEC.md`

## Contratos canônicos

Estes enums são normativos. Schema e demais docs devem convergir para eles.

| Contrato | Valores |
|---|---|
| `Workspace.scope_profile` | `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS` |
| `Workspace.scope_status` | `SCOPE_VALIDATION`, `SUPPORTED`, `OUT_OF_SCOPE` |
| `Workspace.government_sphere` | `MUNICIPAL`, `ESTADUAL`, `DISTRITAL`, `FEDERAL` |
| `Workspace.legal_regime` | `LEI_14133_2021` |
| `Workspace.procurement_mode` | `PREGAO` |
| `Workspace.procurement_form` | `ELETRONICO` |
| `Workspace.object_nature` | `AQUISICAO_BENS_COMUNS` |
| `Document.type` | `DFD`, `ETP`, `TR`, `EDITAL`, `CONTRATO`, `PESQUISA_PRECOS`, `OUTROS` |
| `Rule.source_type` | `NORMATIVE`, `REFERENCE_ONLY` |
| `Finding.severity` | `HIGH`, `MEDIUM`, `INFO` |
| `Finding.status` | `OPEN`, `UNDER_REVIEW`, `RESOLVED`, `ACCEPTED_RISK`, `FALSE_POSITIVE` |
| `Finding.category` | `STRUCTURE`, `CONSISTENCY`, `MARKET`, `HISTORY`, `PRICE`, `EXECUTION`, `COMPLIANCE` |
| Revisão de extração | `EXTRACTED`, `CONFIRMED`, `REJECTED` |

`MEDIUM` substitui qualquer uso anterior de `MED`. `INFO` substitui `LOW`. Campos de escopo podem permanecer sem valor enquanto `scope_status = SCOPE_VALIDATION`; isso não cria novos valores de enum.

Nesta versão, `SUPPORTED` significa exclusivamente a conjunção: esfera `MUNICIPAL`, regime `LEI_14133_2021`, modalidade `PREGAO`, forma `ELETRONICO` e natureza `AQUISICAO_BENS_COMUNS`. Qualquer outro perfil é `OUT_OF_SCOPE`. O desenho pode admitir novos perfis no futuro, mas eles não são aceitos agora.

PNCP e Compras.gov são canais de dados, não valores ou evidências suficientes de `government_sphere`. IN SEGES/ME nº 81 e modelos AGU devem ser cadastrados como `REFERENCE_ONLY` para este perfil. Somente `NORMATIVE` aplicável ao perfil ativo pode fundamentar finding normativo; `REFERENCE_ONLY` não determina `SUPPORTED`.

O contrato externo desses metadados é `schemas/corpus_process.v0.1.0.json`; ele não adiciona campos à raiz fechada de `ProcurementProcess`.

---

## 1. Workspace e documentos

### FR-001 — Criar contratação
**Feature:** F-01  
O sistema deve permitir criar um workspace com identificador único, CNPJ e identificação do órgão/entidade, unidade, objeto, responsável, status documental, `scope_profile`, `scope_status`, esfera, regime legal, modalidade, forma, natureza do objeto e canal de origem dos dados.

**AC**
- workspace recebe ID persistente;
- status documental inicial = `DRAFT` e estado de escopo inicial = `SCOPE_VALIDATION`;
- canal PNCP/Compras.gov não preenche nem infere esfera;
- alterações ficam auditadas.

### FR-002 — Importar documentos
**Feature:** F-02  
Deve aceitar PDF e DOCX, executar OCR quando necessário e manter original e derivados separados.

**AC**
- arquivo original é preservado de forma imutável, inclusive após OCR ou reprocessamento;
- SHA-256 é calculado sobre os bytes do original;
- para o mesmo SHA-256 e a mesma versão do pipeline, OCR/importação são idempotentes e não criam documento ou texto derivado duplicado;
- mudança de pipeline gera derivado versionado, sem sobrescrever o original nem derivados anteriores;
- versão, SHA-256, resultado e vínculo entre original e derivados ficam registrados;
- falha de parsing/OCR é exibida explicitamente.

### FR-003 — Classificar documento
**Feature:** F-02  
Deve identificar ao menos: DFD, ETP, TR, edital, contrato, pesquisa de preços e outros.

**AC**
- confiança exibida;
- usuário pode corrigir classe;
- correção fica auditada.

### FR-004 — Proveniência de bloco
**Feature:** F-02  
Todo trecho extraído deve manter documento, página/seção e texto original.

**AC**
- clique em evidência abre contexto correspondente.

### FR-005 — Estados do processo
**Feature:** F-01  
O workspace percorre os estados documentais definidos em `00_PRODUCT_SPEC.md` §6 e pode retornar a estados anteriores mantendo histórico. O estado de escopo é controlado separadamente por FR-006.

**AC**
- transições ficam auditadas;
- voltar de estado não apaga versões anteriores;
- workspace que não esteja `SUPPORTED` não avança além de `DRAFT`.

### FR-006 — Gate obrigatório de escopo
**Feature:** F-01  
Antes de extração de domínio, indexação, análise, contagem ou recuperação como comparável, o sistema deve validar o workspace contra `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`.

**AC**
- dados ausentes ou ainda não confirmados mantêm `scope_status = SCOPE_VALIDATION` e nenhuma engine de domínio é executada;
- `SUPPORTED` só é produzido quando há evidência registrada e confirmação dos cinco campos canônicos: `MUNICIPAL`, `LEI_14133_2021`, `PREGAO`, `ELETRONICO` e `AQUISICAO_BENS_COMUNS`;
- esfera `FEDERAL`, `ESTADUAL` ou `DISTRITAL`, ou qualquer outro desenquadramento do perfil exclusivo, produz `OUT_OF_SCOPE` com motivo;
- PNCP/Compras.gov é tratado apenas como canal e jamais como evidência suficiente de esfera;
- IN SEGES/ME nº 81, modelos AGU e qualquer regra `REFERENCE_ONLY` não participam da decisão de `SUPPORTED`;
- `SCOPE_VALIDATION` e `OUT_OF_SCOPE` não alimentam engines, índices analíticos, contagens, corpus, denominadores nem comparáveis públicos;
- decisão, evidências, autor ou mecanismo, timestamp e versão do gate são auditados;
- revalidação após correção de metadados é permitida e preserva integralmente o histórico.

---

## 2. Modelo estruturado

### FR-010 — Extrair itens
**Feature:** F-03  
Identificar itens/lotes e sua relação com o documento.

### FR-011 — Extrair requisitos técnicos
**Feature:** F-03  
Converter requisitos em `{atributo, operador, valor, unidade}` quando possível.

### FR-012 — Extrair campos transversais
**Feature:** F-03  
Extrair quantidade, prazo, garantia, local, critério de aceitação, pagamento e obrigações.

### FR-013 — Evidência obrigatória
**Feature:** F-03  
Nenhum valor estruturado pode ser considerado `CONFIRMED` sem evidência.

### FR-014 — Revisão humana
**Feature:** F-04  
Usuário deve aceitar, editar ou rejeitar extrações.

**AC**
- valor editado mantém original;
- usuário e timestamp registrados;
- downstream usa último valor confirmado.

### FR-015 — Classificação da fonte de regra
**Feature:** F-05 / F-11  
Toda regra deve registrar `source_type`, fonte, versão, vigência e perfis aos quais é aplicável.

**AC**
- regra `NORMATIVE` só gera finding normativo quando aplicável a `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`;
- regra `REFERENCE_ONLY` pode fornecer contexto identificado como não normativo, mas não determina suporte, não gera finding normativo e não eleva severidade por suposta obrigação;
- IN SEGES/ME nº 81 e modelos AGU são `REFERENCE_ONLY` neste perfil;
- findings e relatórios exibem o `source_type` das regras utilizadas.

---

## 3. TR Quality Linter [B]

### FR-020 — Completude estrutural
**Feature:** F-05.1  
Detectar elementos esperados ausentes conforme regras `NORMATIVE` aplicáveis ao perfil ativo. Conteúdo `REFERENCE_ONLY` pode ser apresentado como orientação separada, nunca como finding normativo.

### FR-021 — Ambiguidade
**Feature:** F-05.2  
Sinalizar expressões sem interpretação operacional clara.

Ex.: “bom desempenho”, “alta qualidade”.

### FR-022 — Mensurabilidade
**Feature:** F-05.4  
Sinalizar requisito sem critério observável de cumprimento.

### FR-023 — Contradição interna
**Feature:** F-05.5  
Detectar valores conflitantes dentro do mesmo TR.

### FR-024 — Obrigação sem aceitação
**Feature:** F-05.6  
Identificar obrigações relevantes sem critério de recebimento/medição associado.

### FR-025 — Referência quebrada
**Feature:** F-05.7  
Detectar anexos/seções referenciados e ausentes.

### FR-026 — Possível restrição
**Feature:** F-05.8 / F-07  
Sinalizar requisito ou combinação com impacto significativo sobre oferta de mercado.

**AC**
- nunca classificar automaticamente como ilegal;
- mostrar impacto quantitativo e evidência;
- sem dados de F-07, o finding não pode ser `HIGH` só por suspeita qualitativa.

### FR-027 — Subjetividade
**Feature:** F-05.3  
Sinalizar juízos de valor sem critério operacional ("melhor qualidade", "tecnologia moderna", "padrão superior").

**AC**
- evidência = trecho original;
- nunca classificar automaticamente como ilegal.

---

## 4. Consistência entre documentos [C]

Todas as FR desta seção executam somente em workspace `SUPPORTED` e usam documentos ativos/utilizáveis do próprio processo. Documento/processo `SCOPE_VALIDATION` ou `OUT_OF_SCOPE` não forma par de comparação, baseline, contagem ou denominador.

### FR-030 — ETP ↔ TR
Comparar objeto, item, quantidade, prazo, garantia e requisitos.

### FR-031 — TR ↔ Edital
Comparar requisitos relevantes transferidos à fase externa.

### FR-032 — Edital ↔ Contrato
Comparar obrigações e valores relevantes.

### FR-033 — TR ↔ Contrato
Comparação direta das condições materiais da contratação.

### FR-034 — Alteração justificada
Quando houver divergência, permitir marcar alteração como intencional e registrar justificativa.

### FR-035 — Evidência bilateral
Todo finding de inconsistência deve mostrar os dois trechos conflitantes.

### FR-036 — DFD ↔ ETP
**Feature:** F-06  
Quando houver DFD, comparar objeto, quantidade e necessidade com o ETP.

**AC**
- evidência bilateral;
- ausência de DFD não gera finding de inconsistência.

---

## 5. Market Feasibility [A]

### FR-040 — Buscar candidatos
**Feature:** F-07  
Buscar produtos/soluções possivelmente compatíveis.

### FR-041 — Extrair atributos de produto
Extrair especificações relevantes com fonte.

### FR-042 — Matching por requisito
Classificar cada requisito para cada produto em:
- `PASS`
- `FAIL`
- `UNKNOWN`

### FR-043 — Compatibilidade conjunta
Calcular quantos candidatos satisfazem todos os requisitos obrigatórios.

### FR-044 — Sensibilidade
Calcular o impacto de cada requisito na redução do universo compatível.

### FR-045 — Evidência de mercado
Cada `PASS`/`FAIL` deve apontar fonte ou ser `UNKNOWN`.

### FR-046 — Incerteza
Ausência de dado não pode ser tratada como `FAIL`.

---

## 6. Histórico e obsolescência [D]

A base histórica deve ser filtrada antes da busca para conter somente processos `SUPPORTED`. Processos federais, estaduais ou distritais e demais `OUT_OF_SCOPE` não podem ser recuperados, usados em linhagem ou incluídos em contagens/denominadores.

### FR-050 — Busca histórica
Encontrar itens/TRs semanticamente semelhantes no universo municipal suportado.

### FR-051 — Similaridade
Calcular similaridade global e por requisito.

### FR-052 — Linhagem
Mostrar cadeia provável de reutilização.

### FR-053 — Mudança de mercado
Comparar compatibilidade histórica e atual.

### FR-054 — Obsolescência
Sinalizar atributos cuja prevalência caiu materialmente.

### FR-055 — Origem
Mostrar primeira ocorrência conhecida de requisito/descrição no universo `SUPPORTED`, quando recuperável, sem atribuir origem global fora desse universo.

---

## 7. Price Intelligence [A]

Contratações públicas usadas como comparáveis devem passar individualmente pelo gate do perfil; a amostra pública contém apenas processos municipais `SUPPORTED`. Registros `OUT_OF_SCOPE` são excluídos antes de estatística, contagem e denominador. Preços de fornecedores/comércio eletrônico seguem sua classificação própria de fonte e não são apresentados como contratação pública.

### FR-060 — Pesquisa comparável
Encontrar preços de itens equivalentes, registrando `scope_status`, esfera, CNPJ do órgão/entidade quando aplicável e canal de cada candidato público.

**AC**
- PNCP/Compras.gov pode ser canal de coleta, mas não prova esfera municipal;
- candidato público sem escopo validado não entra na amostra;
- exclusões por escopo ficam auditáveis e fora do denominador.

### FR-061 — Normalização
Normalizar moeda, unidade, quantidade e data.

### FR-062 — Outliers
Identificar e justificar exclusão de valores atípicos.

### FR-063 — Estatística
Calcular pelo menos mediana, média, mínimo, máximo e tamanho da amostra após os filtros de escopo e equivalência.

### FR-064 — Memória de cálculo
Gerar registro auditável das fontes e transformações.

---

## 8. Traceability [C]

### FR-070 — Grafo de requisito
Representar cada requisito ao longo de documentos.

### FR-071 — Requisito sem origem
Detectar requisito presente no TR sem fundamentação anterior localizada.

### FR-072 — Requisito perdido
Detectar requisito que desaparece em edital/contrato.

### FR-073 — Requisito modificado
Detectar alteração de valor/semântica entre fases.

### FR-074 — Cobertura de fiscalização
Detectar obrigação contratual sem verificação correspondente.

---

## 9. Findings e colaboração

### FR-080 — Finding padronizado
**Feature:** F-11  
Schema mínimo:

```json
{
  "id": "FIND-001",
  "rule_id": "RULE-...",
  "rule_source_type": "NORMATIVE",
  "category": "CONSISTENCY",
  "severity": "HIGH",
  "confidence": 0.96,
  "title": "...",
  "evidence": [],
  "status": "OPEN"
}
```

`severity` ∈ {`HIGH`, `MEDIUM`, `INFO`}.  
`status` ∈ {`OPEN`, `UNDER_REVIEW`, `RESOLVED`, `ACCEPTED_RISK`, `FALSE_POSITIVE`}.  
`category` ∈ {`STRUCTURE`, `CONSISTENCY`, `MARKET`, `HISTORY`, `PRICE`, `EXECUTION`, `COMPLIANCE`}.

### FR-081 — Workflow de finding
**Feature:** F-12  
Estados:
`OPEN`, `UNDER_REVIEW`, `RESOLVED`, `ACCEPTED_RISK`, `FALSE_POSITIVE`.

### FR-082 — Comentários
Usuários devem poder comentar e mencionar decisão.

### FR-083 — Auditoria
Toda mudança de status/valor deve ser registrada.

### FR-084 — Reprocessamento
Após correção documental, findings afetados devem ser recalculados.

---

## 10. Execução contratual

### FR-090 — Checklist de fiscalização
**Feature:** F-13  
Gerar itens verificáveis a partir de requisitos contratuais.

### FR-091 — Evidência de recebimento
Permitir anexar documento/observação à verificação.

### FR-092 — Não conformidade
Registrar requisito não atendido e vincular ao contrato.

### FR-093 — Traceback
Fiscal deve conseguir navegar da obrigação até ETP/TR/edital.

---

## 11. LLM e pipeline agêntico

As FR desta seção estão subordinadas ao FR-006: orquestradores, agentes, LLMs, ferramentas e bases de recuperação recebem somente workspace e contexto `SUPPORTED`. O filtro é aplicado antes da recuperação; instrução em prompt não substitui o controle determinístico. Fonte `REFERENCE_ONLY` deve conservar sua classificação e não pode ser transformada em conclusão normativa.

### FR-100 — Structured output
Toda chamada de LLM que afete estado deve retornar schema validado.

### FR-101 — Evidence grounding
Conclusões semânticas devem referenciar evidências fornecidas ao modelo.

### FR-102 — Agent tool isolation
Agentes só podem acessar ferramentas explicitamente registradas, com filtros de `scope_profile = MUNICIPAL_14133_PREGAO_ELETRONICO_BENS` e `scope_status = SUPPORTED` aplicados no servidor.

### FR-103 — Iteration budget
Cada tarefa agêntica deve possuir limite de passos/custo/tempo.

### FR-104 — Deterministic precedence
Quando regra determinística resolve a questão, ela tem precedência sobre inferência de LLM. O gate FR-006 não pode ser contornado ou revertido por agente/LLM.

### FR-105 — Validation pass
Finding semântico `HIGH` deve passar por validação antes de ser exibido como `HIGH`.

---

## 12. Integrações e exportação

### FR-110 — Exportar processo
**Feature:** F-15  
Exportar PDF, DOCX e JSON do workspace: dados estruturados, findings, evidências e memória de cálculo quando houver.

**AC**
- JSON reimportável no schema vigente;
- exportação não omite evidências dos findings `HIGH` e `MEDIUM`.

### FR-111 — Integrações institucionais
**Feature:** F-15  
Quando tecnicamente possível, integrar sistemas municipais de processo eletrônico, TR Digital/sistemas de compras, PNCP/Compras.gov e API institucional.

**AC**
- todo registro importado recebe canal de origem e passa pelo FR-006 antes de indexação analítica ou uso por engine;
- PNCP/Compras.gov não implica esfera federal nem municipal;
- registros federais, estaduais ou distritais são `OUT_OF_SCOPE` e nunca alimentam engines, contagens, corpus, denominadores ou comparáveis públicos;
- falha de integração é visível (NFR-002);
- ausência de um conector não bloqueia o workspace local.

---

# Requisitos não funcionais

### NFR-001 — Auditabilidade
100% dos findings `HIGH` e `MEDIUM` devem possuir evidência navegável.

### NFR-002 — Não silencioso
Falhas de parsing, extração ou integração nunca podem ser ocultadas.

### NFR-003 — Segurança
Dados do órgão devem ser isolados por tenant e protegidos em trânsito e repouso.

### NFR-004 — LGPD
Logs não devem armazenar conteúdo pessoal desnecessário.

### NFR-005 — Reprodutibilidade
O mesmo conjunto de documentos + mesma versão de regras deve permitir reproduzir o relatório.

### NFR-006 — Versionamento
Schemas, prompts e regras devem possuir versão.

### NFR-007 — Latência
Análises rápidas determinísticas: alvo < 5 s após parsing.  
Análise completa sem mercado: alvo < 2 min para processo típico.  
Pesquisa de mercado pode ser assíncrona.

### NFR-008 — Observabilidade
Registrar duração, erro, modelo, custo estimado e versão de cada tarefa.

### NFR-009 — Explainability
Usuário deve saber por que cada alerta existe e quais dados o originaram.

### NFR-010 — Falso positivo controlado
Findings `HIGH` devem ter precisão alvo ≥ 90%.

### NFR-011 — Resiliência
Falha em um módulo não deve invalidar resultados independentes.

### NFR-012 — Perfil normativo municipal
Nesta versão, regras e execução devem ser isoladas pelo único perfil aceito, `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`, sem fallback para regras federais, estaduais ou distritais. A organização por `profile` pode permitir evolução futura sem alterar o escopo aceito agora; nenhum perfil não municipal pode ser ativado ou tratado como `SUPPORTED` nesta versão.

---

# Critérios de aceite do corpus R1

Estes critérios validam o lote/corpus de avaliação R1; não são limites, cotas ou tetos de uso produtivo.

- **R1-AC-01 — Volume:** pelo menos 15 processos com `scope_status = SUPPORTED`.
- **R1-AC-02 — Diversidade institucional:** pelo menos 5 CNPJs distintos de órgãos/entidades municipais entre os processos `SUPPORTED`.
- **R1-AC-03 — Diversidade material:** pelo menos 3 categorias normalizadas de bens entre os processos `SUPPORTED`.
- **R1-AC-04 — Teto de concentração:** no máximo 5 processos `SUPPORTED` por CNPJ no corpus R1.
- **R1-AC-05 — Par documental:** cada processo possui exatamente um ETP e exatamente um TR marcados como ativos e utilizáveis; versões anteriores podem ser preservadas, mas não contam como ativas/utilizáveis.
- **R1-AC-06 — Denominador:** nenhum processo `SCOPE_VALIDATION` ou `OUT_OF_SCOPE` integra o corpus, as contagens ou o denominador de qualquer R1-AC.
- **R1-AC-07 — Aplicação:** volume, diversidade e teto por CNPJ são critérios exclusivos de composição/aceite do corpus R1 e não restringem criação, ingestão ou uso produtivo de workspaces `SUPPORTED`.

---

# Dependências mínimas de implementação

| Módulo | Requisitos principais |
|---|---|
| Ingestão e gate de escopo | FR-001–006 |
| Requirements Engine | FR-010–014 |
| TR Linter | FR-020–027 |
| Consistency | FR-030–036 |
| Market | FR-040–046 |
| Histórico | FR-050–055 |
| Preço | FR-060–064 |
| Traceability | FR-070–074 |
| Findings | FR-080–084 |
| Fiscalização | FR-090–093 |
| AI/Agents | FR-100–105 |
| Integrações | FR-110–111 |
