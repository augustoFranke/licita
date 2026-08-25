# scope.md — O que a v1 aceita e rejeita

> Objetivo deste documento: permitir que, dado qualquer processo ou documento,
> o sistema/desenvolvedor responda **inequivocamente** `SUPPORTED` ou
> `OUT_OF_SCOPE`. Nenhum "depende", nenhum caso cinza dentro da v1. Casos que
> não couberem aqui são, por definição, `OUT_OF_SCOPE`.

---

## 1. Como usar este documento

Existe uma hierarquia de escopos. Um processo só é `SUPPORTED` se **todos** os
níveis abaixo forem atendidos:

1. **Nível normativo** — qual regime jurídico a contratação segue.
2. **Nível de objeto** — o que está sendo comprado.
3. **Nível documental** — que documentos o processo contém.
4. **Nível de ente** — quem está contratando.
5. **Nível de sistema** — o que a v1 promete fazer com esses documentos.

Se qualquer um falhar → `OUT_OF_SCOPE`. A ordem de checagem é a de cima para
baixo (primeiro contrata, depois vira objeto, etc.).

---

## 2. Nível normativo — qual regime jurídico

### SUPPORTED
- **Somente Lei 14.133/2021** (Nova Lei de Licitações).
- **Perfil normativo único fixo:** Lei 14.133/2021 + **IN 81/2022** (SGD) +
  **modelo federal de TR da AGU para compras** (vigente).
- As regras de interesse são as da aquisição de bens comuns dentro desse trio.

### OUT_OF_SCOPE (rejeitado no nível normativo)
- Licitações sob **Lei 8.666/93**, Lei 10.520/02 (Pregão antigo),
  Regime **RDC**, ou qualquer lei de licitações estadual/municipal própria.
- **Contratações públicas de serviço** sem aquisição de bens.
- **Obras e serviços de engenharia** (qualquer hipótese).
- **Licitações de TIC** com regra especial (Lei 14.133 art. 123B, Decreto
  10.740/2021, etc.) — a v1 não aplica o regime especial de TIC.
- Contratações de **registro de preços** que não derivem de aquisição de bens
  comuns (o registro em si pode existir, mas o objeto central tem de ser bem
  comum).

---

## 3. Nível de objeto — o que pode ser comprado

### SUPPORTED
- **Bens comuns** conforme acepção da Lei 14.133: bens com especificações
  usuais de mercado e padrões de qualidade/desempenho normalmente definidos.
- Exemplos não exaustivos: material de escritório, mobiliário padrão, insumos,
  equipamentos padronizados, material de limpeza, itens de consumo.

### OUT_OF_SCOPE (rejeitado no nível de objeto)
- **Serviços**, ainda que com fornecimento de materiais acessórios.
- **Obras** e **serviços de engenharia**.
- **Bens que não admitem especificação objetiva** na visão da v1 (bens com
  marca exclusiva sem justificativa tabelada pela v1).
- **Itens de TI exclusivos / complexos** tratados sob regra especial de TIC.
- Contratações cujo objeto seja **predominantemente intelectual/consultoria**
  (ainda que com entregas tangíveis).

*Critério pragmático: se a descrição do objeto cabe no modelo AGU de TR para
compras de bens comuns, é SUPPORTED. Se exigir modelo de serviços, obras ou
Engenharia, é OUT_OF_SCOPE.*

---

## 4. Nível documental — que documentos o processo tem

A v1 trabalha com uma cadeia documental. Cada tipo tem perfil esperado.

### SUPPORTED (tipos aceitos)
| Tipo | Sigla | Papel na cadeia |
|---|---|---|
| Estudo Técnico Preliminar | ETP | origem da solução / especificações |
| Termo de Referência | TR | documento central que a v1 valida |
| Edital | — | veículo formal da licitação |
| Contrato | — | instrumento final / executção |

Formatos de arquivo aceitos (entrada bruta):
- **PDF** e **DOCX**.
- **PDFs escaneados (imagem)** são aceitos apenas se o OCR atingir **boa qualidade**; caso contrário → `OUT_OF_SCOPE` (R3 usa OCR como fallback).

### OUT_OF_SCOPE (documental)
- **Documentos fora da cadeia** de qualquer tipo: DFD, planilhas de necessidade, minutas,
  anexos do edital que não façam parte da cadeia acima. (Um anexo que contenha
  TR/especificações pode ser tratado como o documento-fonte do tipo
  correspondente.)
- Conjunto de **documentos de um mesmo tipo** (ex.: 2 TRs para o mesmo
  processo) — a v1 assume **1 TR, 1 ETP, 1 edital, 1 contrato por processo**.
  Mais de um de qualquer tipo → `OUT_OF_SCOPE`.
- **Cadeia incompleta** — a v1 exige a **cadeia completa (1 ETP + 1 TR + 1 edital + 1 contrato)** como condição para `SUPPORTED`. Qualquer um desses documentos ausente → `OUT_OF_SCOPE`.

### Critério de cópia/reutilização
A v1 **marca** (não bloqueia) trechos detectavelmente copiados/reutilizados
entre os documentos do processo (ETP→TR, TR→edital, TR→contrato). Isso alimenta
os engines de consistência e lint. Não é motivo para rejeição — o registro é
automático.

---

## 5. Nível de ente — quem contrata

### SUPPORTED
- **Entes federais** que usam a IN 81 como base normativa de compras.
- Contratações que seguem o **modelo AGU federal** para TR de compras.

### OUT_OF_SCOPE
- **Estados e municípios** com norma própria de compras que divirja do perfil
  federal (como a maioria). A IN 81 é federal; não é regra universal de
  município/estado.
- Entes que usam a Lei 14.133 mas NÃO que seguem a IN 81/AGU — exigiriam uso de
  campo noutra configuração.

---

## 6. Nível funcional — o que a v1 faz (e não faz)

### A v1 aceita e faz — o fluxo completo (R1–R10)
1. Receber PDF/DOCX de ETP, TR, edital, contrato.
2. Extrair texto preservando **documento, página, bloco/parágrafo, tabela**.
3. Estruturar em **entidades** (Item, Requirement, FieldValue, Evidence...).
4. Apresentar extração para **revisão humana** (aceitar/editar/rejeitar) com audit log.
5. Rodar **Consistence Engine** atravessando ETP↔TR↔edital↔contrato.
6. Rodar **TR Linter determinístico** (Lei 14.133 + IN 81 + modelo AGU).
7. Rodar **TR Linter semântico** (expressões ambíguas, 'alta qualidade', etc.)
   → sempre como **risco/achado para revisão**, nunca como conclusão de
   "ilegal".
8. Apresentar findings, com evidência rastreável dos dois lados, navegável ao
   original.
9. **Reprocessar** após correções e **exportar relatório**.

### A v1 NÃO faz — exclusions que não dependem do objeto
- **Não decide contratação.** Não aprova/rejeita o processo em lugar de
  requisitante, compras ou jurídico.
- **Não exerce juízo de legalidade.** Sempre achado/risco, nunca veredicto.
- **Não valida adequação/razoabilidade do preço ou mercado** (thread A, pós-v1). No que toca a valores, a v1 **apenas confere consistência** do mesmo valor entre TR/edital/contrato — não opina se o preço está alto, baixo ou compatível com o mercado.
- **Não redige** fluxos de trâmite, minutas, editais. Gera relatório, não
  conteúdo normativo.
- **Não substitui revisão humana.** É um compilador/pre-flight check.
- **Não ingere histórico** (D) nem **pesquisa de mercado/preços** (A) na v1;
  esses ficam para depois do gate final.

---

## 7. Procedimento de decisão

Dado um processo, aplicado sequencialmente:

```
1. Regime jurídico = Lei 14.133 bem comum?        → não → OUT_OF_SCOPE (normativo)
2. Objeto = bem comum?                            → não → OUT_OF_SCOPE (objeto)
3. Documentos = **cadeia completa** {1 ETP, 1 TR, 1 edital, 1 contrato}, PDF/DOCX, scans só com OCR de boa qualidade?
                                                   → não → OUT_OF_SCOPE (documental)
4. Ente = federal, segue IN 81 + modelo AGU?      → não → OUT_OF_SCOPE (ente)
5. Todas OK?                                      → SUPPORTED
```

A resposta final é **sempre** uma das duas. Qualquer ambiguidade em qualquer
passo resolve automaticamente para `OUT_OF_SCOPE`.

---

## 8. Fine line — limites que precisam da regra prática e do modelo AGU

Alguns nós colocam dúvida real entre bem comum X serviços/X TIC. Quando se
limita, adota-se a regra prática:

**Predominância do esforço/trabalho.** Se o objeto envolve **execução continuada de serviço**, engenharia ou TIC → **`OUT_OF_SCOPE`** (mesmo que não haja prestação de obra). Só é `SUPPORTED` quando a contratação é majoritariamente compra de *coisa* com especificação padrão.
- **Referência ao modelo AGU de compras.** Se o TR precisa seguir o modelo de
  TR de compras (não o modelo de serviços) → SUPPORTED. Recomenda a revisão.

Quando a fronteira dependa de julgamento, o **default é rejeitar** e registrar
motivo. A regra do default fecha o ciclo: nenhum processo fica sem resposta.