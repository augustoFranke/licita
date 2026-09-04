# Manifesto do Golden Dataset (R4)

- **Perfil:** `PUBLICO_14133_PREGAO_ELETRONICO_BENS`
- **Política padrão:** `4-municipal-historical-ocr`; o processo policy 8 declara sua versão no manifesto JSON
- **Total de Processos:** 10 (5 `dev`, 5 `eval` provisórios)
- **Total de Itens:** 149
- **Total de Valores e Requisitos Anotados:** 392 (Meta $\ge 300$ atingida)
- **Holdout:** inválido; os cinco processos de `eval` foram expostos ao benchmark R5 e devem migrar para `dev`
- **Revisão:** leitura A concluída; novo `eval`, leitura B cega e adjudicação pendentes

## Particionamento do Dataset

| Split | Processo ID | Itens | FieldValues | Requirements | Total V+R |
|---|---|---|---|---|---|
| `eval` | `01612698000169-1-000047-2024` | 1 | 2 | 0 | 2 |
| `dev` | `13988308000139-1-000095-2024` | 1 | 4 | 1 | 5 |
| `dev` | `17749896000290-1-000055-2024` | 1 | 5 | 0 | 5 |
| `dev` | `25105255000140-1-000041-2024` | 1 | 4 | 1 | 5 |
| `eval` | `52061181000160-1-000080-2024` | 69 | 68 | 0 | 68 |
| `eval` | `90836693000140-1-000431-2026` | 2 | 10 | 70 | 80 |
| `eval` | `83026138000197-1-000126-2024` | 71 | 215 | 0 | 215 |
| `eval` | `87613022000105-1-000106-2024` | 1 | 3 | 0 | 3 |
| `dev` | `87613022000105-1-000285-2025` | 1 | 3 | 2 | 5 |
| `dev` | `88814181000130-1-000215-2024` | 1 | 4 | 0 | 4 |

## Conformidade e Imutabilidade

Todos os 20 documentos (10 ETPs e 10 TRs) tiveram seus hashes SHA-256 validados diretamente dos bytes originais em disco.
Nenhum processo ou documento é compartilhado entre `dev` e `eval`, mas o split
é provisório porque o benchmark R5 já abriu os cinco processos de `eval`. O split
ativo não contém anotações `engine_generated`; a cópia histórica excluída foi
preservada somente em `r4/data/candidates/` e não participa das métricas.
