# Gate da Ingestão Documental (R3)

**Resultado: PASSOU**

Verificação determinística de reabertura de âncoras (`arquivo → blocos`) executada sobre os 10 processos reais candidatos em `r4/data/candidates/` (20 documentos: 10 ETPs e 10 TRs).

Cada arquivo físico original foi reaberto a partir do disco e teve seu $\text{SHA-256}$ conferido contra o catálogo oficial `corpus/catalogo/documentos.jsonl`.

| Critério | Exigido | Obtido | Status |
|---|---|---|---|
| Processos avaliados | 10 | 10 | ✅ |
| Documentos avaliados (ETP + TR) | 20 | 20 | ✅ |
| Imutabilidade dos originais (SHA-256) | 100% | 100% | ✅ |
| Total de âncoras de evidência testadas | $\ge 50$ | 73 | ✅ |
| **Taxa Global de Reabertura de Âncoras** | $\ge 95{,}0\%$ | **100,00%** (73/73) | ✅ |
| Falhas silenciosas de parsing/OCR (`NFR-002`) | 0 | 0 | ✅ |
| Conformidade de página ($\ge 1$) e citação literal | 100% | 100% | ✅ |

---

## Detalhamento por Processo Candidato

| # | Processo ID | Total Evidências | Reabertas OK | Taxa Individual | Status |
|---|---|---|---|---|---|
| 1 | `01612698000169-1-000047-2024` | 5 | 5 | 100,00% | ✅ |
| 2 | `13988308000139-1-000095-2024` | 9 | 9 | 100,00% | ✅ |
| 3 | `17749896000290-1-000055-2024` | 9 | 9 | 100,00% | ✅ |
| 4 | `25105255000140-1-000041-2024` | 9 | 9 | 100,00% | ✅ |
| 5 | `52061181000160-1-000080-2024` | 5 | 5 | 100,00% | ✅ |
| 6 | `76017474000108-1-000118-2025` | 8 | 8 | 100,00% | ✅ |
| 7 | `83026138000197-1-000126-2024` | 6 | 6 | 100,00% | ✅ |
| 8 | `87613022000105-1-000106-2024` | 6 | 6 | 100,00% | ✅ |
| 9 | `87613022000105-1-000285-2025` | 8 | 8 | 100,00% | ✅ |
| 10 | `88814181000130-1-000215-2024` | 8 | 8 | 100,00% | ✅ |

---

## Verificação das Âncoras Navegáveis

Cada evidência aprovada cumpre cumulativamente:
1. `document_id` compatível com o documento extraído;
2. `page` física ou lógica $\ge 1$;
3. `block_id` existe na lista de blocos estruturados;
4. `quote` é substring idêntica e verificável dentro do texto bruto do bloco (`quote in block.text`).
