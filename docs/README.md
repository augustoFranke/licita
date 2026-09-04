# TR Intelligence Platform — Specification Pack

Fonte de verdade do produto, nesta ordem:

1. O perfil exclusivo `PUBLICO_14133_PREGAO_ELETRONICO_BENS`, definido em
   [`scope.md`](scope.md), e este README
2. Os arquivos numerados `00`–`04`, sempre interpretados dentro desse perfil
3. O recorte da fatia em construção (`scope.md`, `Plano.md`)
4. Catálogos de implementação (`rules_draft.md`, `r4/`, schema)

A restrição de perfil vale para o produto atual inteiro, não apenas para M0–M1;
ela admite as esferas federal, estadual, distrital e municipal.
PE significa Pregão Eletrônico. A única base normativa vinculante do perfil é a
Lei nº 14.133/2021. Materiais de orientação de outros entes podem ser
`REFERENCE_ONLY`: não determinam `SUPPORTED` nem findings. Um overlay municipal
só poderá ser ativado no futuro se a norma local estiver expressamente
identificada. PNCP e Compras.gov são canais de acesso a dados.

`00`–`04` descrevem as capacidades do produto. Exemplos ou fluxos genéricos
neles não ampliam esfera, modalidade, regime ou objeto além do perfil
exclusivo. `scope.md` e `Plano.md` fixam o que a fatia M0–M1 já executa.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`00_PRODUCT_SPEC.md`](00_PRODUCT_SPEC.md) | Visão, features `F-*`, UX, estados |
| [`01_REQUIREMENTS.md`](01_REQUIREMENTS.md) | `FR-*`, `NFR-*`, enums canônicos |
| [`02_USER_STORIES.md`](02_USER_STORIES.md) | Histórias `US-*` por epic |
| [`03_USAGE_FLOWS.md`](03_USAGE_FLOWS.md) | Fluxos diários |
| [`04_TRACEABILITY_MATRIX.md`](04_TRACEABILITY_MATRIX.md) | Feature → FR → US → fluxo; ordem M0–M6 |
| [`scope.md`](scope.md) | Perfil exclusivo e decisão `SUPPORTED` / `OUT_OF_SCOPE` |
| [`Plano.md`](Plano.md) | R0–R10 com porta de fase (entrada / saída / fora) |
| [`TODO.md`](TODO.md) | Pendências verificadas após o fechamento da R1 |
| [`rules_draft.md`](rules_draft.md) | Catálogo determinístico F-05 (M1) |
| [`../schemas/procurement_process.v0.1.0.json`](../schemas/procurement_process.v0.1.0.json) | Payload documental fechado |
| [`../schemas/corpus_process.v0.1.0.json`](../schemas/corpus_process.v0.1.0.json) | Manifesto externo de perfil e escopo |

Vocabulário A/B/C/D, enums e mapeamento `F-03` → persistência: `01` e `04`.
Arquitetura: documento → extração → revisão humana → engine → finding → decisão.
