# scope.md — Perfil exclusivo do produto atual

> Perfil canônico: `PUBLICO_14133_PREGAO_ELETRONICO_BENS`.
> A restrição deste documento vale para o produto atual inteiro. Os arquivos
> `00`–`04` descrevem capacidades, mas não ampliam este perfil.

O produto cobre o ciclo documental de aquisições públicas de bens por
**Pregão Eletrônico (PE)** sob a Lei nº 14.133/2021, em **qualquer esfera**
(federal, estadual, distrital ou municipal). A fatia M0–M1 implementa
F-01–F-06, F-11 e F-12; as capacidades posteriores continuam sujeitas ao mesmo
perfil exclusivo.

---

## 1. Decisão de escopo

Um processo é `SUPPORTED` somente quando satisfaz simultaneamente:

1. **Esfera:** federal, estadual, distrital ou municipal (`F`/`E`/`D`/`M`).
   A esfera não restringe o escopo, mas é **obrigatória e fechada**: ausente ou
   desconhecida resulta em `OUT_OF_SCOPE`, pois é a prova de que a compra é de
   ente público sob o regime.
2. **Regime:** Lei nº 14.133/2021.
3. **Modalidade:** Pregão Eletrônico (`PE`).
4. **Objeto:** aquisição de bens comuns.
5. **Documentos de uma coleta nova:** cadeia completa da mesma contratação,
   exatamente um ETP, um TR, um Edital e um instrumento contratual, reabertos
   localmente e com texto utilizável. O contrato é o ponto de descoberta e deve
   trazer vínculo exato por `numeroControlePNCPCompra`.
6. **Perfil:** `PUBLICO_14133_PREGAO_ELETRONICO_BENS` registrado no catálogo.

Falha ou ambiguidade nos critérios de perfil resulta em `OUT_OF_SCOPE`. Falta,
duplicidade ou inutilidade de um elo documental de uma coleta nova impede a
publicação e fica registrada no estado com o motivo observável; isso não apaga
processos históricos já preservados. O motivo de perfil deve ser registrado,
por exemplo `FORA_DO_PERFIL` por objeto.

O controle negativo SAEMA de energia permanece fisicamente no corpus por ser
de ente público sob o regime, mas é `OUT_OF_SCOPE` / `FORA_DO_PERFIL` no
critério de objeto. Ele
não entra em R2 nem em qualquer denominador ou métrica dos elegíveis.

---

## 2. Fonte normativa e referências

### Base vinculante

- **Lei nº 14.133/2021**, exclusivamente.

Somente essa lei pode sustentar `SUPPORTED` ou o fundamento normativo de um
finding no perfil atual.

### `REFERENCE_ONLY`

- IN SEGES/ME nº 81/2022;
- modelos de TR da AGU;
- TR Digital.

Esses materiais podem auxiliar leitura, vocabulário ou comparação, mas nunca
determinam `SUPPORTED`, `OUT_OF_SCOPE`, disparo, severidade ou fundamento de
finding. Eles não são overlay ativo deste perfil.

**Limite conhecido do perfil multiesfera.** A Lei nº 14.133/2021 é norma
nacional e alcança União, Estados, DF e Municípios (CF art. 22, XXVII; art. 1º
da Lei), então a base vinculante é a mesma em qualquer esfera — e todas as
regras deste produto se fundamentam apenas em artigos dela. A Lei, porém,
remete diversos pontos a *regulamento*, e cada esfera edita o seu (decretos e
INs federais, decretos estaduais, distritais e municipais). Esse regulamento
**não é verificado por este produto em nenhuma esfera**.

A consequência muda com a ampliação: a IN SEGES/ME nº 81/2022 permanece
`REFERENCE_ONLY` aqui, mas ela *vincula* o órgão federal. Um achado "conforme"
deste produto afirma conformidade com a Lei nº 14.133/2021, nunca com o
regulamento da esfera do ente. Um overlay por esfera poderá existir no futuro
apenas quando a norma aplicável estiver expressamente identificada, versionada
e associada ao ente. Até isso ocorrer, nenhuma prática regulamentar presumida
complementa a Lei.

Empresas públicas e sociedades de economia mista seguem a Lei nº 13.303/2016 e
ficam fora por critério de regime — o filtro de amparo legal já as exclui.

PNCP e Compras.gov são **canais de publicação e obtenção de dados**, não fontes
normativas e não prova autônoma de enquadramento.

---

## 3. Objeto

### SUPPORTED

- Bens comuns na acepção da Lei nº 14.133/2021.
- Materiais, mobiliário, insumos, equipamentos padronizados, material de
  limpeza, consumo e bens comuns de informática, desde que a contratação seja
  aquisição de bens e não esteja submetida a regime especial incompatível.

### OUT_OF_SCOPE

- Serviços, inclusive fornecimento de energia e objetos com prestação
  continuada predominante.
- Obras e serviços de engenharia.
- Contratação predominantemente intelectual ou consultoria.
- Regime especial de TIC ou outro regime incompatível.
- Outra modalidade, regime jurídico ou objeto. Ampliar qualquer um deles
  (serviços/obras, dispensa, Lei 8.666) muda as regras de conformidade e é
  outro produto, não uma configuração deste.

O critério é a natureza do objeto e da obrigação, não a forma do modelo usado
pelo órgão. Na dúvida, registrar `OUT_OF_SCOPE` com o motivo observável.

---

## 4. Documentos, originais e OCR

Os tipos do produto permanecem `DFD`, `ETP`, `TR`, `EDITAL`, `CONTRATO`,
`PESQUISA_PRECOS` e `OUTROS`, em PDF ou DOCX. Para uma coleta nova, a
contratação só entra no corpus quando há **exatamente ETP, TR, EDITAL e
CONTRATO** utilizáveis. DFD, pesquisa de preços e outros tipos não são elos
exigidos; processos históricos que só têm ETP/TR permanecem preservados.

O original baixado é imutável e identificado pelo SHA-256 dos bytes originais.
OCR pode ser aplicado a qualquer arquivo que necessite dele e é cacheável pela
chave:

```text
SHA-256 do original + idioma + versão/configuração do OCR
```

A saída de OCR é artefato derivado auditável, ligado ao original, à chave de
cache, à ferramenta/configuração e ao momento de produção. Nunca substitui ou
altera o original. Se qualquer elo exigido permanecer ilegível ou sem texto
utilizável, a nova cadeia não é publicada e o motivo fica registrado no estado.

Política de novas coletas: `8-cadeia-completa-documentos-utilizaveis`. As políticas
históricas continuam registradas nos manifestos preservados. O manifesto de
escopo segue `schemas/corpus_process.v0.1.0.json`; o payload documental
`ProcurementProcess` permanece separado e fechado.

---

## 5. Nível funcional

### M0–M1 executa

1. Receber e extrair PDF/DOCX com âncoras de documento, página e bloco.
2. Estruturar entidades e exigir evidência.
3. Permitir revisão humana com audit log.
4. Comparar documentos disponíveis sem inventar ausência.
5. Executar o TR Linter determinístico e semântico dentro do perfil exclusivo.
6. Gerenciar findings, reprocessar e exportar relatório.

### Ainda não nesta fatia

- Mercado e preço (M2/M3).
- Histórico e obsolescência (M3).
- Rastreio completo (M4).
- Fiscalização (M5).
- Pipeline agêntico e integrações posteriores, sempre limitados ao mesmo
  perfil multiesfera enquanto este documento vigorar.

Valores monetários nesta fatia servem à consistência documental, não a juízo
de mercado.

### O produto nunca faz

- Substituir decisão administrativa, jurídica ou técnica.
- Emitir “ilegal”, “TR aprovado” ou “processo reprovado”.
- Tratar referência orientativa como norma vinculante.
- Esconder falha de parsing, extração, OCR ou integração.

---

## 6. Procedimento binário

```text
1. Esfera ∈ {F,E,D,M}?                             não → OUT_OF_SCOPE
2. Regime = Lei nº 14.133/2021?                    não → OUT_OF_SCOPE
3. Modalidade = PE (Pregão Eletrônico)?            não → OUT_OF_SCOPE
4. Objeto = aquisição de bens comuns?              não → OUT_OF_SCOPE
5. Cadeia nova = ETP + TR + Edital + Contrato, utilizáveis e vinculados? não →
   não publicar (registrar o elo faltante/inutilizável)
6. Perfil registrado é o perfil exclusivo atual?  não → OUT_OF_SCOPE
7. Todas sim?                                      sim → SUPPORTED
```

Os processos históricos sem os dois últimos elos permanecem no corpus
histórico; a etapa 5 é obrigatória apenas para novos aceites e para qualquer
promoção de um processo histórico a completo.
