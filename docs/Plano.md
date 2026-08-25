# Roadmap executável — v0 → v1

## Escopo fixo da v1

-  **Somente aquisição de bens comuns**, Lei 14.133/2021.
    
    - Excluir serviços, obras, engenharia e regras especiais de TIC.
        
    - Começar com um único perfil normativo: **Lei 14.133 + IN 81/2022 + modelo federal AGU para compras**.
        
    - A IN 81 é diretamente federal e não deve ser tratada como regra universal de todo município/estado.
        
    - **Entregável:** `scope.md` definindo exatamente o que o sistema aceita e rejeita.
        
    - **Gate:** dado qualquer processo, o sistema/desenvolvedor consegue responder inequivocamente `SUPPORTED` ou `OUT_OF_SCOPE`.
        
    - **Só então → R1.**
        

## R1 — Corpus real

-  Montar corpus inicial.
    
    - **Ferramentas:** PNCP; portais de transparência; Compras.gov; downloads manuais.
        
    - PNCP contém editais, anexos, contratos, atas e outros documentos de entes federais, estaduais e municipais.
        
    - **Entregável:** mínimo **30 processos reais**, de ≥5 órgãos e ≥3 categorias de bens.
        
    - Pelo menos:
        
        - 30 TRs;
            
        - 20 ETPs;
            
        - 20 editais correspondentes;
            
        - 10 contratos correspondentes.
            
    - Armazenar metadados: órgão, processo, data, objeto, URLs/fontes e relação entre documentos.
        
    - Marcar documentos explicitamente copiados/reutilizados quando identificáveis.
        
    - **Gate:** 30 processos podem ser abertos localmente e suas relações `ETP → TR → edital → contrato` estão catalogadas.
        
    - **Só então → R2.**
        

## R2 — Modelo estruturado dos dados

-  Definir a representação interna.
    
    - **Ferramentas:** Python + Pydantic/JSON Schema.
        
    - Entidades mínimas:
        
        - `Document`
            
        - `Section`
            
        - `Item`
            
        - `Requirement`
            
        - `FieldValue`
            
        - `Evidence`
            
        - `Finding`
            
    - `Requirement` precisa representar ao menos:
        
        - atributo;
            
        - operador;
            
        - valor;
            
        - unidade;
            
        - texto original;
            
        - documento;
            
        - página/seção;
            
        - item relacionado.
            
    - `FieldValue` cobre quantidade, prazo, garantia, valor, local de entrega etc.
        
    - **Entregável:** schema versionado + 5 processos convertidos manualmente para ele.
        
    - **Gate:** os campos que serão verificados na v1 podem ser representados **sem recorrer novamente ao texto livre**.
        
    - **Só então → R3.**
        

## R3 — Ingestão documental

-  Transformar documentos reais em uma representação pesquisável.
    
    - **Ferramentas:** PyMuPDF para PDF; `python-docx` para DOCX; OCR apenas como fallback; hashing para identificar arquivos.
        
    - Preservar obrigatoriamente:
        
        - documento;
            
        - página;
            
        - parágrafo/bloco;
            
        - tabela;
            
        - texto original.
            
    - **Entregável:** `document → structured blocks`.
        
    - **Gate:** em amostra manual de 10 processos, ≥95% dos trechos necessários para quantidade, especificações, prazo e garantia são recuperados corretamente.
        
    - **Só então → R4.**
        

## R4 — Golden dataset

-  Criar a verdade de referência para avaliar o sistema.
    
    - **Ferramentas:** JSONL/YAML versionado; opcionalmente Label Studio.
        
    - Anotar manualmente **10–15 processos**.
        
    - Para cada um, marcar:
        
        - itens;
            
        - quantidades;
            
        - requisitos técnicos;
            
        - prazos;
            
        - garantia;
            
        - execução;
            
        - recebimento;
            
        - medição;
            
        - pagamento;
            
        - evidência textual.
            
    - Separar documentos de treino/desenvolvimento dos documentos usados em avaliação.
        
    - **Entregável:** dataset com pelo menos **300 valores/requisitos anotados**.
        
    - **Gate:** duas leituras manuais consecutivas do dataset não revelam campos ambíguos sem uma política de anotação definida.
        
    - **Só então → R5.**
        

## R5 — Requirements Engine

-  Extrair automaticamente dados e requisitos.
    
    - **Ferramentas:** regras/regex para fatos simples + LLM com saída estruturada + Pydantic para validação.
        
    - LLM nunca pode retornar somente prosa: toda extração deve seguir schema.
        
    - Toda informação precisa conter `Evidence`.
        
    - **Entregável:** `documents → structured procurement`.
        
    - **Gate em conjunto de teste não utilizado no desenvolvimento:**
        
        - precisão ≥97% para quantidade/prazo/garantia;
            
        - recall ≥90%;
            
        - precisão ≥90% para requisitos técnicos;
            
        - **100% das extrações possuem evidência navegável até o documento original**.
            
    - **Só então → R6.**
        

## R6 — Human Review

-  Criar a primeira interface utilizável.
    
    - **Ferramentas sugeridas:** FastAPI + PostgreSQL + HTML/HTMX; evitar frontend complexo nesta fase.
        
    - **Frontend mínimo na v1:** trabalho mínimo de interface/design, apenas o suficiente para os testes e para o gate da R6 serem executados. Usar **só vanilla JS/HTML/CSS, sem framework**, por enquanto. Revisitar apenas se um caso concreto da v1 provar precisar de mais.
                
    - Usuário deve conseguir:
        
        - subir documentos;
            
        - ver campos extraídos;
            
        - clicar e ver a origem;
            
        - aceitar;
            
        - editar;
            
        - rejeitar;
            
        - registrar correção.
            
    - Toda intervenção deve ficar em audit log.
        
    - **Entregável:** primeiro aplicativo utilizável por outra pessoa.
        
    - **Gate:** alguém que não desenvolveu o sistema consegue importar um processo e corrigir toda a extração **sem editar JSON ou banco manualmente**.
        
    - **Só então → R7.**
        

## R7 — Consistency Engine

-  Implementar a thread **C**.
    
    - **Ferramentas:** Python puro para regras; RapidFuzz/normalização para equivalências; LLM somente onde equivalência semântica for inevitável.
        
    - Primeiros invariantes:
        
        - quantidade;
            
        - unidade;
            
        - prazo de entrega;
            
        - prazo contratual;
            
        - garantia;
            
        - especificações técnicas;
            
        - locais de entrega;
            
        - valores quando comparáveis.
            
    - Comparações:
        
        - ETP ↔ TR;
            
        - TR ↔ edital;
            
        - TR ↔ contrato.
            
    - Cada finding precisa mostrar os **dois trechos conflitantes**.
        
    - **Entregável:** relatório de inconsistências estruturado.
        
    - Criar também testes com inconsistências artificialmente inseridas.
        
    - **Gate:**
        
        - ≥95% das inconsistências determinísticas conhecidas detectadas;
            
        - ≤5% falsos positivos;
            
        - 100% dos findings possuem evidência dos dois lados.
            
    - **Só então → R8.**
        

## R8 — TR Linter determinístico

-  Implementar a parte objetiva da thread **B**.
    
    - A Lei 14.133 define os elementos básicos do TR e da fase preparatória; a IN 81 detalha dez grandes elementos no padrão federal.
        
    - **Fonte de regras:** Lei 14.133 + IN 81 + modelo AGU vigente.
        
    - A AGU mantém atualmente modelo de TR para compras atualizado em dezembro de 2025.
        
    - Detectar inicialmente:
        
        - seção obrigatória ausente;
            
        - quantidade ausente;
            
        - prazo ausente quando necessário;
            
        - garantia citada inconsistentemente;
            
        - recebimento não definido;
            
        - referência a anexo inexistente;
            
        - definição divergente dentro do próprio TR;
            
        - requisito sem critério relacionado quando objetivamente verificável.
            
    - Cada regra deve possuir:
        
        - `rule_id`;
            
        - descrição;
            
        - escopo;
            
        - fundamento;
            
        - severidade;
            
        - função de detecção;
            
        - testes.
            
    - **Entregável:** catálogo versionado de regras + linter.
        
    - **Gate:** 100% das regras possuem testes e nenhuma regra normativa é adicionada sem fonte explícita.
        
    - **Só então → R9.**
        

## R9 — TR Linter semântico

-  Adicionar aquilo que regras simples não conseguem analisar.
    
    - **Ferramentas:** LLM + structured output + eval harness.
        
    - Detectar:
        
        - “alta qualidade”;
            
        - “bom desempenho”;
            
        - “tecnologia moderna”;
            
        - requisitos ambíguos;
            
        - requisitos dificilmente mensuráveis;
            
        - obrigação sem forma clara de verificar seu cumprimento;
            
        - possíveis contradições semânticas.
            
    - Nunca apresentar “ilegal” como conclusão automática; apresentar **risco/achado para revisão**.
        
    - **Entregável:** findings semânticos com trecho, categoria, explicação curta, confiança e sugestão de revisão.
        
    - **Gate:** em pelo menos 100 findings avaliados manualmente:
        
        - ≥85% dos findings classificados como relevantes;
            
        - ≥90% de precisão nos findings marcados como `HIGH`;
            
        - nenhum `HIGH` sem evidência documental.
            
    - **Só então → R10.**
        

## R10 — v1 integrada

-  Unificar tudo em um único fluxo.
    
    - Upload de ETP/TR/edital/contrato.
        
    - Classificação documental.
        
    - Parsing.
        
    - Extração estruturada.
        
    - Revisão humana.
        
    - Consistency Engine.
        
    - TR Linter determinístico.
        
    - TR Linter semântico.
        
    - Findings por severidade.
        
    - Navegação até evidências.
        
    - Reprocessamento após correções.
        
    - Exportação de relatório.
        
    - **Entregável:** **v1 utilizável de ponta a ponta**.
        
    - **Gate final da v1:**
        
        - executar 10 processos inéditos sem intervenção de desenvolvedor;
            
        - 100% dos findings rastreáveis à fonte;
            
        - precisão ≥90% para findings `HIGH`;
            
        - nenhuma perda silenciosa de documento;
            
        - em teste cronometrado com ≥5 TRs reais, reduzir em **≥30% o tempo mediano de revisão** comparado ao método manual.
            

**Somente quando esse último gate passar eu começaria A (mercado) e D (histórico).**

---

# Workflow do funcionário

|Etapa|Hoje|Com a v1|
|---|---|---|
|Necessidade/DFD|Área requisitante formaliza necessidade|**Igual**|
|ETP|Equipe pesquisa e escolhe solução|**Igual**|
|Criar TR|Abre modelo/TR anterior/TR Digital e redige/adapta|**Igual inicialmente**|
|Reutilização|Procura TR antigo e copia partes manualmente|**Ainda igual na v1; D virá depois**|
|Revisão do próprio TR|Relê documento, procura omissões e inconsistências manualmente|**Upload → Linter apresenta findings**|
|Conferir requisitos|Procura valores, prazos, quantidades e garantias manualmente|**Requirements Engine já os estrutura**|
|Conferir contra ETP|Abre dois documentos lado a lado|**ETP ↔ TR automaticamente**|
|Corrigir|Edita TR e relê|Edita → reprocessa → findings desaparecem/permanecem|
|Setor de compras|Recebe TR e faz nova revisão|Recebe TR + relatório estruturado|
|Edital|Requisitos são transferidos/adaptados|**TR ↔ edital automaticamente**|
|Jurídico/controle|Faz análise própria e eventualmente devolve|Continua responsável; recebe processo com erros mecânicos já filtrados|
|Contrato|Minuta replica obrigações do TR/editais|**TR ↔ contrato automaticamente**|
|Publicação|Processo segue para licitação|Igual|

### Mudança essencial

**Hoje:**

`redigir → reler → comparar PDFs → devolver → corrigir → reler novamente`

**v1:**

`redigir → importar → estruturar → lint → comparar → corrigir findings → validar → encaminhar`

A ferramenta não decide a contratação nem substitui quem elabora, compras ou jurídico. Ela funciona como um **compilador/pre-flight check do processo**.

### Ferramentas externas que já temos disponíveis

**Fontes normativas:** Lei 14.133, IN 81, modelos e checklists da AGU e manual do TR Digital. A própria AGU alerta que modelos precisam ser adaptados à contratação concreta, o que reforça justamente o espaço para validação automatizada.

**Dados públicos:** PNCP e Compras.gov. A API atual do Compras.gov expõe CATMAT, CATSER, contratações, resultados, contratos e pesquisa de preços; isso será especialmente valioso quando entrarmos em A/D depois da v1.

**Stack mínima que eu escolheria:** Python, FastAPI, PostgreSQL, Pydantic, PyMuPDF, python-docx, pytest, RapidFuzz e um LLM com structured output. **Sem vector DB, agentes, RAG framework ou microservices na v1**, a menos que um problema concreto prove que precisamos deles. **Frontend: vanilla JS/HTML/CSS apenas, sem framework**, o mínimo suficiente para rodar os testes.