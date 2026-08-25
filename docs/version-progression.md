
* **v0 — Fundação / Dataset**

  * Coletar 30–50 processos reais completos.
  * Organizar DFD, ETP, TR, edital, pesquisa de preços e contrato.
  * Definir schema estruturado de requisitos.
  * Criar dataset manual de referência.
  * Implementar parser de PDF/DOCX.
  * Extrair itens, quantidades, prazos, garantia e especificações básicas.

* **v0.1 — Requirements Engine**

  * Converter descrições textuais em requisitos estruturados.
  * Normalizar unidades, operadores, atributos e categorias.
  * Associar cada requisito ao trecho/documento de origem.
  * Interface para correção manual da extração.

* **v0.2 — Consistency Engine — C**

  * Comparar ETP ↔ TR.
  * Comparar TR ↔ edital.
  * Comparar TR ↔ contrato.
  * Detectar divergências de quantidade, prazo, garantia, valores e requisitos.
  * Gerar achados com evidência e severidade.

* **v1 — TR Linter — B**

  * Detectar seções obrigatórias ausentes.
  * Detectar requisitos vagos/subjetivos.
  * Detectar requisitos não mensuráveis.
  * Detectar contradições internas.
  * Detectar critérios de aceitação/fiscalização ausentes.
  * Detectar referências/anexos inexistentes.
  * Gerar relatório de revisão do TR.

* **v1.1 — Market Matching — A**

  * Reaproveitar/evoluir o buscador de produtos.
  * Buscar produtos compatíveis com cada item.
  * Calcular percentual de mercado compatível.
  * Mostrar quais requisitos eliminam quais produtos.
  * Identificar itens sem correspondência ou com apenas uma correspondência.

* **v1.2 — Market Feasibility — A**

  * Medir nível de competitividade da especificação.
  * Detectar combinação excessivamente restritiva.
  * Identificar requisitos responsáveis pela restrição.
  * Sugerir requisitos para revisão, sem alterá-los automaticamente.
  * Produzir evidência dos produtos/modelos encontrados.

* **v2 — Histórico de Licitações — D**

  * Ingerir dados de PNCP/Compras.gov.
  * Indexar itens e descrições históricas.
  * Encontrar contratações semelhantes.
  * Detectar descrições copiadas/reutilizadas.
  * Mostrar origem provável de uma especificação.
  * Comparar versões históricas de um mesmo item.

* **v2.1 — Obsolescence Engine — D**

  * Detectar especificações antigas ainda reutilizadas.
  * Comparar requisitos históricos com mercado atual.
  * Identificar atributos que se tornaram raros ou obsoletos.
  * Sinalizar “compra do mesmo” quando isso reduz competição.
  * Mostrar evolução histórica de preço e disponibilidade.

* **v2.2 — Price Intelligence — A**

  * Buscar preços em contratações públicas semelhantes.
  * Integrar preços de mercado quando juridicamente aplicável.
  * Normalizar produtos, unidades e quantidades.
  * Detectar outliers.
  * Calcular média, mediana e faixa de preços.
  * Produzir memória de cálculo e rastreabilidade das fontes.

* **v3 — Requirement Traceability — C**

  * Construir cadeia DFD → ETP → TR → edital → contrato.
  * Identificar requisitos sem origem.
  * Identificar requisitos que desapareceram posteriormente.
  * Identificar requisitos modificados sem justificativa encontrada.
  * Vincular requisito → critério de aceitação → fiscalização.

* **v3.1 — Compliance / Risk Engine — B+C**

  * Biblioteca versionada de regras.
  * Regras determinísticas + verificações semânticas.
  * Classificação por severidade e confiança.
  * Evidência documental para cada alerta.
  * Histórico de resolução/aceite dos alertas.
  * Auditoria completa das decisões humanas.

* **v4 — Workspace Integrado ABCD**

  * Upload de processo completo.
  * Identificação automática dos documentos.
  * Dashboard único de Mercado, Qualidade, Consistência e Histórico.
  * Visualização por item e por requisito.
  * Revisão colaborativa.
  * Exportação de relatório técnico.
  * API para integração com sistemas municipais/estaduais.

* **v4.1 — Assistência à Correção**

  * Propor redações melhores para requisitos problemáticos.
  * Mostrar impacto de cada alteração no mercado.
  * Comparar versão atual ↔ proposta.
  * Nunca alterar documento sem aprovação humana.
  * Registrar justificativa de cada mudança.

* **v5 — Produto Completo**

  * ABCD totalmente integrados.
  * Análise contínua durante a elaboração do TR.
  * Inteligência histórica nacional.
  * Market feasibility e price intelligence em tempo real.
  * Rastreamento completo entre todos os documentos.
  * Compliance configurável por ente/órgão.
  * Integrações com sistemas de processo eletrônico e compras.
  * Métricas de tempo economizado, erros evitados, competição e retrabalho.
  * Painel institucional para compras, jurídico, controle interno e gestores.
