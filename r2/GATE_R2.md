# Gate do modelo estruturado (R2)

**Resultado: PASSOU**

Cinco processos reais do lote
`8-cadeia-completa-documentos-utilizaveis` foram convertidos manualmente para
`ProcurementProcess`. Cada payload contém ETP, TR, Edital e Contrato. As
decisões normalizadas e suas âncoras estão em `annotations.manual.json`; o
gerador não descobre fatos.

| Critério | Exigido | Obtido | Status |
|---|---:|---:|:---:|
| Processos reais do lote policy 8 | 5 | 5 | ✅ |
| Payloads válidos no Pydantic | 5 | 5 | ✅ |
| Payloads válidos no JSON Schema | 5 | 5 | ✅ |
| Documentos por processo | ETP + TR + Edital + Contrato | 4 em cada | ✅ |
| Quantidades com unidade | 5 | 5 | ✅ |
| Requisitos técnicos | ≥1 por processo | 5 | ✅ |
| Tipos comparáveis representados | 9 `FieldType` + `Requirement` | 10/10 | ✅ |
| Hashes dos originais conferidos na geração | 20 | 20 | ✅ |
| Hashes dos artefatos no manifesto | 5 | 5 | ✅ |

Totais estruturados: 27 `FieldValue`, 5 `Requirement`, 5 `Item` e 57 âncoras
de evidência. Reprodução:

```bash
uv run python tools/build_r2_current.py
uv run pytest -q tests/test_r2_current_lot.py tests/test_r2_annotations.py tests/test_schema.py
```
