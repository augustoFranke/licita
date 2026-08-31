# Manifesto do Golden Dataset (R4)

**Perfil:** `MUNICIPAL_14133_PREGAO_ELETRONICO_BENS`  
**Política:** `4-municipal-historical-ocr`  
**Total de Processos:** 10 (5 `dev`, 5 `eval`)  
**Total de Itens:** 192  
**Total de Valores e Requisitos Anotados:** 494 (Meta $\ge 300$ atingida)  

## Particionamento do Dataset

| Split | Processo ID | Itens | FieldValues | Requirements | Total V+R |
|---|---|---|---|---|---|
| `eval` | `01612698000169-1-000047-2024` | 1 | 2 | 0 | 2 |
| `dev` | `13988308000139-1-000095-2024` | 1 | 4 | 1 | 5 |
| `dev` | `17749896000290-1-000055-2024` | 1 | 5 | 0 | 5 |
| `dev` | `25105255000140-1-000041-2024` | 1 | 4 | 1 | 5 |
| `eval` | `52061181000160-1-000080-2024` | 69 | 68 | 0 | 68 |
| `eval` | `76017474000108-1-000118-2025` | 45 | 136 | 46 | 182 |
| `eval` | `83026138000197-1-000126-2024` | 71 | 215 | 0 | 215 |
| `eval` | `87613022000105-1-000106-2024` | 1 | 3 | 0 | 3 |
| `dev` | `87613022000105-1-000285-2025` | 1 | 3 | 2 | 5 |
| `dev` | `88814181000130-1-000215-2024` | 1 | 4 | 0 | 4 |

## Conformidade e Imutabilidade

Todos os 20 documentos (10 ETPs e 10 TRs) tiveram seus hashes SHA-256 validados diretamente dos bytes originais em disco.
Nenhum processo ou documento é compartilhado entre `dev` e `eval`.