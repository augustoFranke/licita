# Leitura B e adjudicação do golden R4

R4 só fecha depois que uma pessoa diferente de quem produziu a leitura A
auditar cegamente os dez processos do split.

## Insumos permitidos ao revisor B

- ETP e TR originais indicados em `r4/manifest.json`;
- `r4/GUIA.md` e `r4/FORMATO.md`;
- o schema `schemas/procurement_process.v0.1.0.json`.

O revisor B não deve receber os payloads de `r4/data/`, as anotações da leitura
A, os resultados da R5 nem os relatórios históricos de concordância.

## Entrega por processo

Depois da leitura cega, comparar A e B e gravar
`r4/review/<processo_id>.json` com esta forma:

```json
{
  "process_id": "CNPJ-1-SEQUENCIAL-ANO",
  "policy_version": "r4-guia-2026-09-04",
  "reviewer_a": "identificador do anotador A",
  "reviewer_b": "identificador do revisor B",
  "blind_source_review": true,
  "reviewed_at": "AAAA-MM-DD",
  "differences": [
    {
      "kind": "omission|improper_inclusion|normalization|scope|evidence|id|policy_ambiguity",
      "decision": "descrição da adjudicação"
    }
  ],
  "unresolved_policy_ambiguities": [],
  "status": "ADJUDICATED"
}
```

Os revisores precisam ser distintos, `blind_source_review` deve ser `true`, o
status final deve ser `ADJUDICATED` e ambiguidades de política precisam estar
resolvidas no guia antes do aceite. Não inventar registros vazios para fazer o
teste passar.
