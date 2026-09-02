"""Coleta retomável e restrita de cadeias documentais completas.

A descoberta começa no feed de contratos do PNCP. Cada contrato aponta para a
contratação vinculada; somente depois de validar o detalhe e o perfil são
consultados os anexos da contratação e do contrato para obter ETP, TR, edital e
instrumento contratual.

A fila de páginas, o cache, as decisões de política e os aceites ficam no
``EstadoColeta``. Este módulo não depende do schema SQLite: usa somente a API
pública de ``state.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import reuse
from .catalog import (
    PAPEIS_DO_LOTE,
    PAPEIS_CADEIA_COMPLETA,
    documento_id,
    escrever_json,
    escrever_jsonl,
    estatisticas,
    montar_processo,
    montar_relacoes,
    ocr_historico_utilizavel,
)
from .classify import (
    CONTRATO,
    EDITAL,
    ESFERAS_SUPORTADAS,
    ETP,
    PERFIL_SUPPORTED,
    TR,
    categoria_objeto,
    classificar_perfil_inicial,
    normalizar,
    papel_documento,
    papel_documento_contrato,
    parece_aquisicao_de_bens,
)
from .pncp import (
    ComprasGov,
    Pncp,
    PncpError,
    _IntervaloGlobal,
    partes_controle,
)
from .state import (
    CACHE_TTL_SEGUNDOS,
    CACHE_TTL_VAZIO_SEGUNDOS,
    CONCLUIDO,
    EstadoColeta,
    LimiteRequisicoes,
    RETRY,
)
from .store import baixar_documento, processo_id
from .verify import verificar


# Decisões ficam gravadas por (processo, policy_version). A versão nova separa
# a exigência de cadeia completa dos aceites históricos de ETP/TR; os registros
# antigos continuam no catálogo e podem ser promovidos quando os elos faltantes
# aparecerem.
POLICY_VERSION = "6-cadeia-completa-todas-esferas"
# Alterar este identificador sempre que a implementação, defaults ou
# interpretação das opções do OCR mudar de forma capaz de alterar o texto.
OCR_PIPELINE_VERSION = "verify-pymupdf-tesseract-v1"
#: Esferas do perfil — fonte única em ``classify.ESFERAS_SUPORTADAS``.
ESFERAS_PERMITIDAS = ESFERAS_SUPORTADAS
# Compatibilidade para chamadores que ainda importam os termos históricos. A
# coleta vigente não os consulta.
DEFAULT_TERMOS = ("Estudo Tecnico Preliminar", "ETP")
ANOS_PRIORITARIOS = (2024, 2023, 2022, 2025)
PAGINAS_POR_LOTE = 5
MARGEM_REQUISICOES_PADRAO = 15

# A estratégia vigente sempre parte deste feed. ``fonte`` continua aceito na
# API pública apenas para não quebrar scripts antigos; qualquer valor legado é
# normalizado para o mesmo fluxo de contratos e jamais ativa uma descoberta
# alternativa.
FONTE_CONTRATOS = "pncp-contratos"


@dataclass(frozen=True, slots=True)
class Caminhos:
    raiz: Path

    @property
    def estado(self) -> Path:
        return self.raiz / "estado" / "etp_tr.sqlite3"

    @property
    def documentos(self) -> Path:
        return self.raiz / "documentos"

    @property
    def catalogo(self) -> Path:
        return self.raiz / "catalogo"


@dataclass(slots=True)
class ResultadoDownload:
    aprovado: bool
    documentos: list[dict[str, Any]]
    motivo: str | None = None
    # As tentativas ficam disponíveis para auditoria do chamador, mas somente
    # ``documentos`` aprovados são publicados no aceite/catálogo.
    tentativas_documentais: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _ResultadoPagina:
    tarefa: dict[str, Any]
    registros: list[dict[str, Any]]
    total: int


# ------------------------------------------------------------------ datas/q


def _int(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _data(valor: str) -> date:
    return datetime.strptime(valor, "%Y%m%d").date()


def _data_iso(valor: object) -> date | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        # Integrações antigas podem mandar uma data ISO com lixo posterior.
        # Só o trecho de data é aceito se ele próprio for válido.
        if len(texto) >= 10:
            try:
                return datetime.strptime(texto[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
    return None


def _data_iso_estrita(valor: object) -> date | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        if len(texto) == 10:
            try:
                return datetime.strptime(texto, "%Y-%m-%d").date()
            except ValueError:
                pass
    return None


def janelas_calendario(
    data_inicial: str, data_final: str, dias: int = 31
) -> list[tuple[str, str]]:
    """Divide o período em janelas reversas para não criar páginas enormes."""
    inicio, fim = _data(data_inicial), _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    if dias < 1:
        raise ValueError("dias deve ser positivo")
    saida: list[tuple[str, str]] = []
    cursor = fim
    while cursor >= inicio:
        comeco = max(inicio, cursor - timedelta(days=dias - 1))
        saida.append((comeco.strftime("%Y-%m-%d"), cursor.strftime("%Y-%m-%d")))
        cursor = comeco - timedelta(days=1)
    return saida


def _ano_no_termo(termo: str) -> bool:
    return re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", termo) is not None


def anos_prioritarios(data_inicial: str, data_final: str) -> tuple[int, ...]:
    """Retorna os anos do intervalo na ordem histórica da busca.

    Os quatro anos de interesse do primeiro lote vêm primeiro. Caso o
    intervalo seja mais amplo, os anos restantes aparecem depois em ordem
    decrescente, sem deixar uma consulta fora do intervalo.
    """
    inicio, fim = _data(data_inicial), _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    intervalo = set(range(inicio.year, fim.year + 1))
    ordenados = [ano for ano in ANOS_PRIORITARIOS if ano in intervalo]
    ordenados.extend(sorted(intervalo.difference(ordenados), reverse=True))
    return tuple(ordenados)


def termos_historicos(
    termos: Sequence[str] = DEFAULT_TERMOS,
    data_inicial: str = "20240101",
    data_final: str = "20251231",
) -> tuple[str, ...]:
    """Inclui o ano no ``q`` e prioriza 2024, 2023, 2022 e 2025.

    Um termo que já contém um ano é preservado como consulta explícita. Os
    resultados são deduplicados sem perder a ordem.
    """
    consultas: list[str] = []
    vistos: set[str] = set()
    anos = anos_prioritarios(data_inicial, data_final)
    intervalo = set(anos)
    termos_limpos = tuple(str(termo).strip() for termo in termos if str(termo).strip())
    for ano in anos:
        for termo in termos_limpos:
            if _ano_no_termo(termo):
                encontrados = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", termo)
                if encontrados and int(encontrados[-1]) not in intervalo:
                    continue
            consulta = termo if _ano_no_termo(termo) else f"{termo} {ano}"
            if consulta not in vistos:
                vistos.add(consulta)
                consultas.append(consulta)
    return tuple(consultas)


# Aliases descritivos para consumidores que usam nomes diferentes na CLI/API.
consultas_historicas = termos_historicos
queries_historicas = termos_historicos


# --------------------------------------------------------------- normalização


def _campo(dados: Mapping[str, Any], *chaves: str) -> Any:
    for chave in chaves:
        if dados.get(chave) is not None:
            return dados[chave]
    return None


def normalizar_compra(dados: dict[str, Any], origem: str) -> dict[str, Any]:
    """Converte os formatos das APIs em metadado comum e valida a identidade.

    O ano no número ``.../AAAA`` identifica o ano da contratação e deve ser
    compatível com ``anoCompra``. A publicação pode ocorrer em ano posterior,
    portanto ``dataPublicacaoPncp`` precisa ser uma data válida, mas seu ano
    não faz parte dessa invariável.
    """
    numero_bruto = _campo(dados, "numeroControlePNCP", "numero_controle_pncp")
    if not numero_bruto:
        raise ValueError("registro sem numeroControlePNCP")
    numero = str(numero_bruto).strip()
    cnpj_por_numero, ano_por_numero, seq_por_numero = partes_controle(numero)

    orgao = dados.get("orgaoEntidade") or {}
    unidade = dados.get("unidadeOrgao") or {}
    amparo = dados.get("amparoLegal") or {}
    if not isinstance(orgao, dict):
        orgao = {}
    if not isinstance(unidade, dict):
        unidade = {}
    if not isinstance(amparo, dict):
        amparo = {}

    cnpj = _campo(
        dados,
        "orgaoEntidadeCnpj",
        "cnpj_orgao",
        "orgao_cnpj",
    ) or orgao.get("cnpj")

    ano_bruto = _campo(dados, "anoCompraPncp", "anoCompra", "ano_compra")
    if ano_bruto is None:
        ano = ano_por_numero
    else:
        ano = _int(ano_bruto)
        if ano is None:
            raise ValueError(f"ano da compra inválido para {numero!r}")
        if ano != ano_por_numero:
            raise ValueError(
                f"ano da compra ({ano}) diverge do número PNCP ({ano_por_numero})"
            )

    sequencial_bruto = _campo(
        dados,
        "sequencialCompraPncp",
        "sequencialCompra",
        "sequencial_compra",
    )
    if sequencial_bruto is None:
        sequencial = seq_por_numero
    else:
        sequencial = _int(sequencial_bruto)
        if sequencial is None:
            raise ValueError(f"sequencial da compra inválido para {numero!r}")
        if sequencial != seq_por_numero:
            raise ValueError(
                f"sequencial da compra ({sequencial}) diverge do número PNCP"
            )

    modalidade = _campo(
        dados,
        "modalidadeId",
        "modalidadeIdPncp",
        "modalidade_id",
        "modalidade_licitacao_id",
    )
    modalidade_nome = _campo(
        dados,
        "modalidadeNome",
        "modalidade_nome",
        "modalidade_licitacao_nome",
    )
    instrumento_codigo = _campo(
        dados,
        "tipoInstrumentoConvocatorioCodigo",
        "tipoInstrumentoConvocatorioCodigoPncp",
        "instrumento_convocatorio_codigo",
    )
    instrumento_nome = _campo(
        dados, "tipoInstrumentoConvocatorioNome", "instrumento_convocatorio"
    )
    amparo_codigo = _campo(
        dados, "amparoLegalCodigoPncp", "amparo_legal_codigo"
    ) or amparo.get("codigo")
    amparo_nome = _campo(dados, "amparoLegalNome", "amparo_legal_nome") or amparo.get(
        "nome"
    )
    amparo_descricao = _campo(
        dados, "amparoLegalDescricao", "amparo_legal_descricao"
    ) or amparo.get("descricao")
    objeto = _campo(dados, "objetoCompra", "objeto", "description") or ""
    data_publicacao = _campo(
        dados,
        "dataPublicacaoPncp",
        "data_publicacao_pncp",
        "createdAt",
    )
    if data_publicacao is not None:
        publicada = _data_iso_estrita(data_publicacao)
        if publicada is None:
            raise ValueError(f"data de publicação inválida para {numero!r}")

    return {
        "numero_controle_pncp": numero,
        "cnpj_orgao": str(cnpj or cnpj_por_numero),
        "ano_compra": ano,
        "sequencial_compra": sequencial,
        "orgao": _campo(
            dados, "orgaoEntidadeRazaoSocial", "orgao_nome", "orgao"
        ) or orgao.get("razaoSocial"),
        "esfera": _campo(
            dados, "orgaoEntidadeEsferaId", "esfera", "esfera_id"
        ) or orgao.get("esferaId"),
        "poder": _campo(
            dados, "orgaoEntidadePoderId", "poder", "poder_id"
        ) or orgao.get("poderId"),
        "unidade": _campo(
            dados, "unidadeOrgaoNomeUnidade", "unidade", "unidade_nome"
        ) or unidade.get("nomeUnidade"),
        "uf": _campo(dados, "unidadeOrgaoUfSigla", "uf") or unidade.get("ufSigla"),
        "municipio": _campo(
            dados, "unidadeOrgaoMunicipioNome", "municipio", "municipio_nome"
        ) or unidade.get("municipioNome"),
        "titulo": _campo(dados, "numeroCompra", "title", "titulo"),
        "objeto": str(objeto),
        "categoria_objeto": categoria_objeto(str(objeto)),
        "modalidade_id": modalidade,
        "modalidade": modalidade_nome,
        "instrumento_convocatorio_codigo": instrumento_codigo,
        "instrumento_convocatorio": instrumento_nome,
        "amparo_legal_codigo": amparo_codigo,
        "amparo_legal_nome": amparo_nome,
        "amparo_legal_descricao": amparo_descricao,
        "srp": _campo(dados, "srp"),
        "data_publicacao_pncp": data_publicacao,
        "data_inicio_proposta": _campo(
            dados, "dataAberturaPropostaPncp", "dataAberturaProposta"
        ),
        "data_fim_proposta": _campo(
            dados, "dataEncerramentoPropostaPncp", "dataEncerramentoProposta"
        ),
        "situacao": _campo(
            dados, "situacaoCompraNomePncp", "situacaoCompraNome", "situacao"
        ),
        "tem_resultado": _campo(dados, "existeResultado", "tem_resultado"),
        "valor_global": _campo(dados, "valorTotalEstimado", "valor_global"),
        "valor_total_homologado": _campo(
            dados, "valorTotalHomologado", "valor_total_homologado"
        ),
        "processo": _campo(dados, "processo"),
        "origem_descoberta": origem,
        "url_detalhe_pncp": (
            f"https://pncp.gov.br/api/consulta/v1/orgaos/{cnpj_por_numero}"
            f"/compras/{ano_por_numero}/{seq_por_numero}"
        ),
        "url_arquivos_pncp": (
            f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj_por_numero}"
            f"/compras/{ano_por_numero}/{seq_por_numero}/arquivos"
        ),
    }


def _mesclar_detalhe(base: dict[str, Any], detalhe: dict[str, Any]) -> dict[str, Any]:
    resultado = normalizar_compra(
        detalhe, base.get("origem_descoberta", "pncp_busca")
    )
    # O detalhe pode não repetir campos opcionais presentes no feed textual.
    for chave, valor in base.items():
        if resultado.get(chave) in (None, "") and valor not in (None, ""):
            resultado[chave] = valor
    resultado["origem_item_busca"] = base.get("numero_controle_pncp")
    return resultado


def _data_no_periodo(compra: dict[str, Any], inicio: str, fim: str) -> bool:
    valor = _data_iso(compra.get("data_publicacao_pncp"))
    limite_inicial = _data_iso(inicio)
    limite_final = _data_iso(fim)
    # A busca textual pode omitir a data; a confirmação oficial preencherá o
    # campo antes da lista de arquivos. Datas inválidas já foram rejeitadas na
    # normalização.
    if valor is None:
        return True
    if limite_inicial is None or limite_final is None:
        return False
    return limite_inicial <= valor <= limite_final


def _normalizar_esferas(
    esferas: set[str] | frozenset[str] | None,
) -> set[str]:
    normalizadas = set(ESFERAS_PERMITIDAS) if esferas is None else {
        str(esfera).strip().upper() for esfera in esferas if str(esfera).strip()
    }
    if not normalizadas or not normalizadas <= set(ESFERAS_PERMITIDAS):
        raise ValueError(
            f"esferas deve ser um subconjunto não vazio de "
            f"{sorted(ESFERAS_PERMITIDAS)}"
        )
    return normalizadas


def _aceitavel(
    compra: dict[str, Any],
    esferas: set[str] | frozenset[str] | None,
    *,
    preliminar: bool = False,
) -> tuple[bool, str | None]:
    # A esfera precede qualquer consulta de arquivos. Ela deixou de restringir
    # o escopo a municípios, mas continua obrigatória: sem esfera conhecida não
    # há prova de que a compra é de ente público sob o regime.
    permitidas = set(ESFERAS_PERMITIDAS) if esferas is None else {
        str(esfera).strip().upper() for esfera in esferas if str(esfera).strip()
    }
    if not permitidas or not permitidas <= set(ESFERAS_PERMITIDAS):
        return False, (
            f"filtro de esfera deve ser subconjunto de {sorted(ESFERAS_PERMITIDAS)}"
        )
    if str(compra.get("esfera") or "").strip().upper() not in permitidas:
        return False, "esfera fora das permitidas"

    instrumento = _int(compra.get("instrumento_convocatorio_codigo"))
    amparo = _int(compra.get("amparo_legal_codigo"))
    modalidade = _int(compra.get("modalidade_id"))

    if preliminar:
        # Resultados da busca textual não trazem necessariamente instrumento
        # ou amparo legal. Campos ausentes precisam ser confirmados no detalhe,
        # não convertidos antecipadamente em rejeição definitiva.
        if instrumento is not None and instrumento != 1:
            return False, "instrumento convocatório não é Edital (código 1)"
        if amparo is not None and amparo != 1:
            return False, "fora da Lei 14.133/2021, Art. 28, I"
        if modalidade is not None and modalidade != 6:
            return False, "modalidade não é Pregão Eletrônico (código 6)"
        objeto = str(compra.get("objeto") or "")
        if objeto and not parece_aquisicao_de_bens(objeto):
            return False, "objeto preliminar não é aquisição de bens comuns"
        return True, None

    if instrumento != 1:
        return False, "instrumento convocatório não é Edital (código 1)"
    if amparo != 1:
        return False, "fora da Lei 14.133/2021, Art. 28, I"

    perfil = classificar_perfil_inicial(
        esfera=compra.get("esfera"),
        amparo_legal_nome=compra.get("amparo_legal_nome"),
        modalidade_id=compra.get("modalidade_id"),
        objeto=compra.get("objeto") or "",
    )
    if perfil != PERFIL_SUPPORTED:
        return False, "fora do perfil de Pregão Eletrônico para bens comuns sob a Lei 14.133"
    return True, None


# ------------------------------------------------------------- round-robin


def _cnpj_da_compra(compra: Mapping[str, Any]) -> str:
    valor = compra.get("cnpj_orgao")
    if valor:
        return str(valor)
    try:
        return partes_controle(str(compra.get("numero_controle_pncp")))[0]
    except (TypeError, ValueError):
        return ""


def deduplicar_compras(compras: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for compra in compras:
        numero = str(compra.get("numero_controle_pncp") or "")
        if not numero or numero in vistos:
            continue
        vistos.add(numero)
        saida.append(compra)
    return saida


def round_robin_por_cnpj(compras: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Intercala órgãos: ``A,A,B`` vira ``A,B,A``."""
    filas: dict[str, deque[dict[str, Any]]] = {}
    ordem_orgaos: list[str] = []
    for compra in deduplicar_compras(compras):
        orgao = _cnpj_da_compra(compra)
        if orgao not in filas:
            filas[orgao] = deque()
            ordem_orgaos.append(orgao)
        filas[orgao].append(compra)
    saida: list[dict[str, Any]] = []
    while True:
        adicionou = False
        for orgao in ordem_orgaos:
            fila = filas[orgao]
            if fila:
                saida.append(fila.popleft())
                adicionou = True
        if not adicionou:
            break
    return saida


# Nomes usados por integrações pequenas e pelos testes de estratégia.
ordenar_round_robin = round_robin_por_cnpj
round_robin_por_orgao = round_robin_por_cnpj
intercalar_por_cnpj = round_robin_por_cnpj
ordenar_por_cnpj = round_robin_por_cnpj


def _prioridade_confirmacao(
    par: tuple[dict[str, Any], str, bool],
) -> tuple[int, int, int, int]:
    """Prioriza registros completos sem sacrificar a diversidade estável."""
    compra, _origem, detalhe = par
    return (
        0 if detalhe else 1,
        0 if _int(compra.get("modalidade_id")) == 6 else 1,
        0 if _int(compra.get("instrumento_convocatorio_codigo")) == 1 else 1,
        0 if _int(compra.get("amparo_legal_codigo")) == 1 else 1,
    )


def _round_robin_pares(
    pares: Iterable[tuple[dict[str, Any], str, bool]]
) -> list[tuple[dict[str, Any], str, bool]]:
    filas: dict[str, deque[tuple[dict[str, Any], str, bool]]] = {}
    ordem_orgaos: list[str] = []
    for par in pares:
        orgao = _cnpj_da_compra(par[0])
        if orgao not in filas:
            filas[orgao] = deque()
            ordem_orgaos.append(orgao)
        filas[orgao].append(par)
    saida: list[tuple[dict[str, Any], str, bool]] = []
    while True:
        adicionou = False
        for orgao in ordem_orgaos:
            if filas[orgao]:
                saida.append(filas[orgao].popleft())
                adicionou = True
        if not adicionou:
            return saida


# ---------------------------------------------------------- arquivos/revisões


def _ativo(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor != 0
    return str(valor).strip().lower() not in {
        "false",
        "0",
        "nao",
        "não",
        "inativo",
        "inactive",
    }


def _chave_revisao(arquivo: Mapping[str, Any]) -> tuple[str, int, str]:
    data = _data_iso(
        arquivo.get("data_publicacao_pncp")
        or arquivo.get("dataPublicacaoPncp")
    )
    return (
        data.isoformat() if data is not None else "",
        _int(
            arquivo.get("sequencial_documento")
            if arquivo.get("sequencial_documento") is not None
            else arquivo.get("sequencialDocumento")
        )
        or -1,
        str(arquivo.get("url") or arquivo.get("uri") or ""),
    )


def _escolher_mais_recente(arquivos: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    candidatos = list(arquivos)
    if not candidatos:
        return None
    return max(candidatos, key=_chave_revisao)


def _resumir_arquivo(bruto: dict[str, Any]) -> dict[str, Any]:
    titulo = str(bruto.get("titulo") or bruto.get("nome") or "")
    url = bruto.get("url") or bruto.get("uri")
    return {
        "sequencial_documento": _int(bruto.get("sequencialDocumento")),
        "titulo": titulo,
        "tipo_documento_id": bruto.get("tipoDocumentoId"),
        "tipo_documento_pncp": bruto.get("tipoDocumentoNome"),
        "papel": papel_documento(bruto.get("tipoDocumentoId"), titulo),
        "url": url,
        "data_publicacao_pncp": bruto.get("dataPublicacaoPncp"),
        "status_ativo": _ativo(bruto.get("statusAtivo")),
    }


def formar_candidato(
    compra: dict[str, Any], arquivos_brutos: Sequence[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    """Forma um candidato histórico preservando revisões ETP/TR ativas.

    A lista ``documentos_compra`` continua contendo a escolha mais recente
    para compatibilidade. ``revisoes_documentos`` guarda todas as alternativas
    e ``baixar_par`` tenta as combinações em ordem de recência.
    """
    arquivos = [
        _resumir_arquivo(a)
        for a in arquivos_brutos
        if _ativo(a.get("statusAtivo"))
    ]
    por_papel = {
        papel: sorted(
            [arquivo for arquivo in arquivos if arquivo["papel"] == papel],
            key=_chave_revisao,
            reverse=True,
        )
        for papel in (ETP, TR)
    }
    # Uma revisão sem URL continua preservada para auditoria e será tentada
    # (e descartada de forma explícita) pelo downloader; a contratação só
    # forma candidato quando há ao menos uma revisão baixável por papel.
    faltantes = [
        papel
        for papel in (ETP, TR)
        if not any(arquivo.get("url") for arquivo in por_papel[papel])
    ]
    if faltantes:
        return (
            None,
            f"documentos da contratação ausentes: {', '.join(faltantes)}",
            arquivos,
        )
    escolhidos = {
        papel: next(
            arquivo for arquivo in por_papel[papel] if arquivo.get("url")
        )
        for papel in (ETP, TR)
    }
    candidato = {
        "numero_controle_pncp": compra["numero_controle_pncp"],
        "compra": compra,
        "documentos_compra": [escolhidos[ETP], escolhidos[TR]],
        "revisoes_documentos": {
            ETP: por_papel[ETP],
            TR: por_papel[TR],
        },
        # Aliases de leitura mantêm explícito que a lista completa foi
        # preservada, sem alterar a lista de dois documentos publicada.
        "revisoes": {
            ETP: por_papel[ETP],
            TR: por_papel[TR],
        },
        "documentos_compra_todas": [*por_papel[ETP], *por_papel[TR]],
        "contratos": [],
    }
    return candidato, None, arquivos


def _resumir_arquivo_contrato(bruto: dict[str, Any]) -> dict[str, Any]:
    """Normaliza um anexo publicado no recurso de contrato.

    Diferentemente dos anexos da contratação, esses registros normalmente não
    trazem ``tipoDocumentoId``. O nome do tipo é a fonte autoritativa para
    separar o instrumento inicial de empenhos, aditivos e apostilamentos.
    """
    titulo = str(bruto.get("titulo") or bruto.get("nome") or "")
    return {
        "sequencial_documento": _int(
            bruto.get("sequencialDocumento")
            if bruto.get("sequencialDocumento") is not None
            else bruto.get("sequencial_documento")
        ),
        "titulo": titulo,
        "tipo_documento_id": bruto.get("tipoDocumentoId"),
        "tipo_documento_pncp": bruto.get("tipoDocumentoNome"),
        "papel": papel_documento_contrato(
            bruto.get("tipoDocumentoNome"), titulo, bruto.get("tipoDocumentoId")
        ),
        "url": bruto.get("url") or bruto.get("uri"),
        "data_publicacao_pncp": bruto.get("dataPublicacaoPncp"),
        "status_ativo": _ativo(bruto.get("statusAtivo")),
    }


def _normalizar_contrato(
    dados: Mapping[str, Any], compra: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Converte um registro do feed de contratos para o catálogo comum.

    O vínculo é validado antes de qualquer consulta de anexos: um contrato que
    aponta para outra contratação nunca pode ser associado por proximidade de
    órgão, ano ou título.
    """
    if not isinstance(dados, Mapping):
        raise ValueError("registro de contrato inválido")
    numero_compra = _campo(
        dados,
        "numeroControlePNCPCompra",
        "numeroControlePncpCompra",
        "numero_controle_pncp_compra",
    )
    numero_compra = str(numero_compra or "").strip()
    if not numero_compra:
        raise ValueError("contrato sem numeroControlePncpCompra")
    if compra is not None:
        compra_numero = str(compra.get("numero_controle_pncp") or "").strip()
        if not compra_numero or compra_numero != numero_compra:
            raise ValueError("contrato sem vínculo exato com a contratação")
    try:
        cnpj_compra, ano_compra, _seq_compra = partes_controle(numero_compra)
    except ValueError as erro:
        raise ValueError(f"vínculo de compra inválido: {erro}") from erro

    numero = _campo(
        dados,
        "numeroControlePNCP",
        "numeroControlePncp",
        "numero_controle_pncp",
        "numeroContratoPncp",
    )
    numero = str(numero or "").strip()
    if not numero:
        raise ValueError("contrato sem numeroControlePNCP")
    try:
        cnpj, ano, sequencial = partes_controle(numero)
    except ValueError as erro:
        raise ValueError(f"número do contrato inválido: {erro}") from erro

    orgao = dados.get("orgaoEntidade") or {}
    unidade = dados.get("unidadeOrgao") or {}
    if not isinstance(orgao, Mapping):
        orgao = {}
    if not isinstance(unidade, Mapping):
        unidade = {}
    cnpj_orgao = str(
        _campo(dados, "orgaoEntidadeCnpj", "cnpj_orgao")
        or orgao.get("cnpj")
        or cnpj
        or cnpj_compra
    )
    tipo = dados.get("tipoContrato")
    if isinstance(tipo, Mapping):
        tipo_id = _campo(tipo, "id", "codigo")
        tipo_nome = _campo(tipo, "nome", "descricao")
    else:
        tipo_id = _campo(dados, "tipoContratoId", "tipo_contrato_id")
        tipo_nome = tipo or _campo(
            dados, "tipoContratoNome", "tipo_contrato_nome"
        )
    contrato = {
        "numero_controle_pncp": numero,
        "numero_controle_pncp_compra": numero_compra,
        "numero_contrato": _campo(
            dados,
            "numeroContratoEmpenho",
            "numeroContrato",
            "numero_contrato",
        ),
        "cnpj_orgao": cnpj_orgao,
        "ano_contrato": _int(
            _campo(dados, "anoContrato", "ano_contrato")
        )
        or ano,
        "sequencial_contrato": _int(
            _campo(dados, "sequencialContrato", "sequencial_contrato")
        )
        or sequencial,
        "processo": _campo(
            dados, "processo", "processoAdministrativo", "processo_administrativo"
        ),
        "categoria_processo": _campo(
            dados, "categoriaProcesso", "categoria_processo"
        ),
        "tipo_contrato": tipo_nome,
        "tipo_contrato_id": tipo_id,
        "fornecedor": _campo(
            dados, "nomeRazaoSocialFornecedor", "fornecedor", "fornecedor_nome"
        ),
        "ni_fornecedor": _campo(
            dados, "niFornecedor", "ni_fornecedor", "fornecedorNi"
        ),
        "data_assinatura": _campo(dados, "dataAssinatura", "data_assinatura"),
        "data_atualizacao_global": _campo(
            dados, "dataAtualizacaoGlobal", "data_atualizacao_global"
        ),
        "numero_retificacao": _campo(
            dados, "numeroRetificacao", "numero_retificacao"
        ),
        "vigencia_inicio": _campo(
            dados, "dataVigenciaInicio", "vigencia_inicio"
        ),
        "vigencia_fim": _campo(dados, "dataVigenciaFim", "vigencia_fim"),
        "valor_global": _campo(dados, "valorGlobal", "valor_global"),
        "objeto": _campo(dados, "objetoContrato", "objeto", "objeto_contrato"),
        "fonte": "pncp",
        "criterio_vinculo": "numeroControlePncpCompra",
        "url_arquivos_pncp": (
            f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}"
            f"/contratos/{ano}/{sequencial}/arquivos"
        ),
        # O registro cru é útil para auditoria/reprocessamento, mas continua
        # dentro de JSON e nunca é usado para construir caminhos locais.
        "registro_feed": dict(dados),
    }
    if contrato["numero_controle_pncp_compra"] != numero_compra:
        raise ValueError("contrato sem vínculo exato com a contratação")
    return contrato


def formar_candidato_cadeia(
    compra: dict[str, Any],
    arquivos_compra_brutos: Sequence[dict[str, Any]],
    contrato: Mapping[str, Any],
    arquivos_contrato_brutos: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    """Forma uma cadeia candidata com ETP, TR, edital e instrumento.

    ETP/TR continuam usando exatamente a classificação e a ordenação de
    revisões do caminho histórico. O edital usa o mesmo mecanismo, enquanto o
    contrato é classificado pelo tipo do anexo contratual.
    """
    arquivos_compra = [
        _resumir_arquivo(a)
        for a in arquivos_compra_brutos
        if _ativo(a.get("statusAtivo"))
    ]
    arquivos_contrato = [
        _resumir_arquivo_contrato(a)
        for a in arquivos_contrato_brutos
        if _ativo(a.get("statusAtivo"))
    ]
    por_papel: dict[str, list[dict[str, Any]]] = {
        papel: sorted(
            [a for a in arquivos_compra if a.get("papel") == papel],
            key=_chave_revisao,
            reverse=True,
        )
        for papel in (ETP, TR, EDITAL)
    }
    por_papel[CONTRATO] = sorted(
        [a for a in arquivos_contrato if a.get("papel") == CONTRATO],
        key=_chave_revisao,
        reverse=True,
    )
    faltantes = [
        papel
        for papel in PAPEIS_CADEIA_COMPLETA
        if not any(a.get("url") for a in por_papel[papel])
    ]
    todos = [*arquivos_compra, *arquivos_contrato]
    if faltantes:
        return (
            None,
            "documentos da cadeia ausentes: " + ", ".join(faltantes),
            todos,
        )
    escolhidos = {
        papel: next(a for a in por_papel[papel] if a.get("url"))
        for papel in PAPEIS_CADEIA_COMPLETA
    }
    contrato_normalizado = _normalizar_contrato(contrato, compra)
    candidato = {
        "numero_controle_pncp": compra["numero_controle_pncp"],
        "compra": compra,
        "contrato": contrato_normalizado,
        "contratos": [contrato_normalizado],
        "documentos_compra": [
            escolhidos[ETP],
            escolhidos[TR],
            escolhidos[EDITAL],
        ],
        "documento_contrato": escolhidos[CONTRATO],
        "documentos_cadeia": [
            escolhidos[ETP],
            escolhidos[TR],
            escolhidos[EDITAL],
            escolhidos[CONTRATO],
        ],
        "revisoes_documentos": {
            ETP: por_papel[ETP],
            TR: por_papel[TR],
            EDITAL: por_papel[EDITAL],
            CONTRATO: por_papel[CONTRATO],
        },
        "revisoes": {
            ETP: por_papel[ETP],
            TR: por_papel[TR],
            EDITAL: por_papel[EDITAL],
            CONTRATO: por_papel[CONTRATO],
        },
        "documentos_compra_todas": [
            *por_papel[ETP],
            *por_papel[TR],
            *por_papel[EDITAL],
        ],
        "documentos_contrato_todas": por_papel[CONTRATO],
        "cadeia_completa_exigida": True,
    }
    return candidato, None, todos


# Nome público curto para integrações que tratam compras e contratos com o
# mesmo vocabulário dos demais normalizadores.
normalizar_contrato = _normalizar_contrato


def _revisoes_do_candidato(
    candidato: Mapping[str, Any], papel: str
) -> list[dict[str, Any]]:
    for nome in (
        "revisoes_documentos",
        "documentos_compra_revisoes",
        "revisoes",
        "documentos_compra_todas",
    ):
        revisoes = candidato.get(nome)
        if isinstance(revisoes, Mapping):
            valor = revisoes.get(papel)
            if isinstance(valor, Sequence) and not isinstance(valor, (str, bytes)):
                return [
                    dict(item)
                    for item in valor
                    if isinstance(item, Mapping)
                ]
        elif isinstance(revisoes, Sequence) and not isinstance(revisoes, (str, bytes)):
            filtradas = [
                dict(item)
                for item in revisoes
                if isinstance(item, Mapping) and item.get("papel") == papel
            ]
            if filtradas:
                return filtradas
    valor = candidato.get("documentos_compra")
    if isinstance(valor, Sequence) and not isinstance(valor, (str, bytes)):
        encontrados = [
            dict(item)
            for item in valor
            if isinstance(item, Mapping) and item.get("papel") == papel
        ]
        if encontrados:
            return encontrados
    if papel == CONTRATO:
        valor = candidato.get("documento_contrato")
        if isinstance(valor, Mapping) and valor.get("papel") == papel:
            return [dict(valor)]
    cadeia = candidato.get("documentos_cadeia")
    if isinstance(cadeia, Sequence) and not isinstance(cadeia, (str, bytes)):
        return [
            dict(item)
            for item in cadeia
            if isinstance(item, Mapping) and item.get("papel") == papel
        ]
    return []


def _configuracao_ocr_normalizada(
    idioma_ocr: str,
    opcoes_ocr: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Normaliza opções executadas e a configuração usada na chave do cache."""
    opcoes = dict(opcoes_ocr or {})
    opcoes.setdefault("ocr", True)
    opcoes.setdefault("idioma", idioma_ocr)
    idioma = str(opcoes.get("idioma") or "").strip().lower()
    if not idioma:
        raise ValueError("idioma OCR não pode ser vazio")
    opcoes["idioma"] = idioma
    try:
        # O round-trip torna tuplas/listas e a ordem de mappings equivalentes,
        # além de rejeitar objetos e números não representáveis em JSON.
        opcoes_normalizadas = json.loads(
            json.dumps(
                opcoes,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError, json.JSONDecodeError) as erro:
        raise ValueError("opções OCR devem ser JSON válido") from erro
    if not isinstance(opcoes_normalizadas, dict):
        raise ValueError("opções OCR devem formar um objeto")
    configuracao = {
        "pipeline_version": OCR_PIPELINE_VERSION,
        "opcoes_ocr": opcoes_normalizadas,
    }
    return idioma, opcoes_normalizadas, configuracao


def _chamar_verificar(
    caminho: Path,
    *,
    ocr: bool = False,
    idioma_ocr: str = "por",
    opcoes_ocr: Mapping[str, Any] | None = None,
) -> Any:
    if not ocr:
        # Mantém a chamada antiga simples para doubles e para a garantia de
        # que a coleta normal jamais procura o Tesseract.
        return verificar(caminho)
    opcoes = dict(opcoes_ocr or {})
    opcoes.setdefault("ocr", True)
    opcoes.setdefault("idioma", idioma_ocr)
    return verificar(caminho, **opcoes)


def _atributo(resultado: Any, nome: str, padrao: Any = None) -> Any:
    if isinstance(resultado, Mapping):
        return resultado.get(nome, padrao)
    return getattr(resultado, nome, padrao)


def _metadados_verificacao(resultado: Any) -> dict[str, Any]:
    ocr_meta = _atributo(resultado, "ocr", {})
    if callable(ocr_meta):
        ocr_meta = ocr_meta()
    if not isinstance(ocr_meta, Mapping):
        ocr_meta = {}
    ocr_dict = dict(ocr_meta)
    try:
        caracteres = int(_atributo(resultado, "caracteres", 0) or 0)
    except (TypeError, ValueError):
        caracteres = 0
    ocr_solicitado = bool(
        _atributo(resultado, "ocr_solicitado", False)
        or ocr_dict.get("solicitado", False)
    )
    ocr_usado = bool(
        _atributo(resultado, "ocr_usado", False)
        or ocr_dict.get("usado", False)
    )
    ocr_motor = _atributo(resultado, "ocr_motor") or ocr_dict.get("motor")
    ocr_idioma = _atributo(resultado, "ocr_idioma") or ocr_dict.get("idioma")
    paginas_ocr = list(_atributo(resultado, "paginas_ocr", ()) or ())
    paginas_tentadas = list(
        _atributo(resultado, "paginas_ocr_tentadas", ()) or ()
    )
    confianca = _atributo(resultado, "ocr_confianca_media")
    erros_ocr = list(_atributo(resultado, "ocr_erros", ()) or ())
    # Doubles antigos podem expor somente os campos planos. Complete o bloco
    # sem apagar os metadados mais ricos fornecidos por verify.py.
    ocr_dict.setdefault("solicitado", ocr_solicitado)
    ocr_dict.setdefault("usado", ocr_usado)
    ocr_dict.setdefault("motor", ocr_motor)
    ocr_dict.setdefault("idioma", ocr_idioma)
    ocr_dict.setdefault("paginas", paginas_ocr)
    ocr_dict.setdefault("paginas_tentadas", paginas_tentadas)
    ocr_dict.setdefault("confianca_media", confianca)
    ocr_dict.setdefault("erros", erros_ocr)
    # Os campos planos facilitam consultas sem perder o bloco produzido pelo
    # módulo verify.py.
    return {
        "abriu": bool(_atributo(resultado, "abriu", False)),
        "paginas": _atributo(resultado, "paginas"),
        "caracteres": caracteres,
        "precisa_ocr": bool(_atributo(resultado, "precisa_ocr", False)),
        "erro": _atributo(resultado, "erro"),
        "ocr": ocr_dict,
        "ocr_solicitado": ocr_solicitado,
        "ocr_usado": ocr_usado,
        "ocr_motor": ocr_motor,
        "ocr_idioma": ocr_idioma,
        "paginas_ocr": paginas_ocr,
        "paginas_ocr_tentadas": paginas_tentadas,
        "ocr_confianca_media": confianca,
        "ocr_erros": erros_ocr,
        "texto_original": _atributo(resultado, "texto_original", "") or "",
    }


def _registrar_documento(
    identificador: str,
    processo: str,
    numero_origem: str,
    arquivo: dict[str, Any],
    baixado: Any,
    raiz: Path,
    *,
    estado: EstadoColeta | None = None,
    ocr: bool = False,
    idioma_ocr: str = "por",
    usar_ocr: bool | None = None,
    idioma: str | None = None,
    opcoes_ocr: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if usar_ocr is not None:
        ocr = usar_ocr
    if idioma is not None:
        idioma_ocr = idioma
    caminho = Path(baixado.caminho)
    digesto = str(getattr(baixado, "sha256", ""))
    cache_hit = False
    cache_chave: str | None = None
    configuracao_cache: dict[str, Any] | None = None
    idioma_cache = str(idioma_ocr).strip().lower()
    opcoes_normalizadas = dict(opcoes_ocr or {})
    resultado: Any = None
    verificacao: dict[str, Any]
    texto = ""

    if ocr:
        idioma_cache, opcoes_normalizadas, configuracao_cache = (
            _configuracao_ocr_normalizada(idioma_ocr, opcoes_ocr)
        )
        cache: dict[str, Any] | None = None
        if estado is not None:
            try:
                cache_chave = estado.chave_resultado_ocr(
                    digesto,
                    idioma_cache,
                    OCR_PIPELINE_VERSION,
                    configuracao_cache,
                )
                cache = estado.obter_resultado_ocr(
                    digesto,
                    idioma_cache,
                    OCR_PIPELINE_VERSION,
                    configuracao_cache,
                )
            except ValueError:
                # O hash continua registrado como veio do store, mas uma
                # identidade inválida jamais entra no cache permanente.
                cache_chave = None
                cache = None
        if cache is not None:
            verificacao_cache = cache.get("verificacao")
            texto_cache = cache.get("texto")
            cache_utilizavel = bool(
                isinstance(verificacao_cache, Mapping)
                and isinstance(verificacao_cache.get("ocr"), Mapping)
                and isinstance(texto_cache, str)
                and texto_cache.strip()
                and verificacao_cache.get("ocr_usado")
                and not verificacao_cache.get("precisa_ocr")
            )
            if cache_utilizavel:
                # O texto é derivado, mas o contêiner original ainda precisa
                # abrir nesta execução. Esta chamada nunca solicita OCR.
                verificacao_original = _chamar_verificar(caminho)
                if bool(_atributo(verificacao_original, "abriu", False)):
                    verificacao = dict(verificacao_cache)
                    verificacao["abriu"] = True
                    paginas = _atributo(verificacao_original, "paginas")
                    if paginas is not None:
                        verificacao["paginas"] = paginas
                    verificacao["erro"] = None
                    texto = texto_cache
                    cache_hit = True
        if not cache_hit:
            resultado = _chamar_verificar(
                caminho,
                ocr=True,
                idioma_ocr=idioma_cache,
                opcoes_ocr=opcoes_normalizadas,
            )
            verificacao = _metadados_verificacao(resultado)
            texto = _atributo(resultado, "texto", "") or ""
        verificacao["ocr_solicitado"] = True
        verificacao["ocr"]["solicitado"] = True
        verificacao["ocr_idioma"] = verificacao.get("ocr_idioma") or idioma_cache
        verificacao["ocr"].setdefault("idioma", idioma_cache)
    else:
        resultado = _chamar_verificar(caminho)
        verificacao = _metadados_verificacao(resultado)
        texto = _atributo(resultado, "texto", "") or ""

    try:
        arquivo_relativo = str(caminho.resolve().relative_to(Path(raiz).resolve()))
    except ValueError:
        arquivo_relativo = str(caminho)
    texto_sha256 = (
        hashlib.sha256(texto.encode("utf-8")).hexdigest()
        if verificacao.get("ocr_usado") and texto
        else None
    )
    cache_meta = {
        "chave": cache_chave,
        "sha256_original": digesto if ocr else None,
        "idioma": idioma_cache if ocr else None,
        "pipeline_version": OCR_PIPELINE_VERSION if ocr else None,
        "configuracao": configuracao_cache,
        "cache_hit": cache_hit,
        "texto_sha256": texto_sha256,
    }
    if ocr:
        verificacao["ocr_cache"] = cache_meta
    registro = {
        "documento_id": identificador,
        "processo_id": processo,
        "papel": arquivo["papel"],
        "titulo": arquivo.get("titulo") or "",
        "tipo_documento_pncp": arquivo.get("tipo_documento_pncp"),
        "tipo_documento_id": arquivo.get("tipo_documento_id"),
        "origem": "pncp",
        "numero_controle_pncp_origem": numero_origem,
        "url_fonte": arquivo.get("url"),
        "data_publicacao_pncp": arquivo.get("data_publicacao_pncp"),
        "arquivo": arquivo_relativo,
        "nome_original_pncp": getattr(baixado, "nome_original", None),
        # ``sha256`` sempre é o hash do arquivo original baixado. OCR só
        # produz texto derivado e jamais substitui esse conteúdo.
        "sha256": digesto,
        "sha256_original": digesto,
        "hash_original": digesto,
        "bytes": getattr(baixado, "bytes", None),
        "extensao": getattr(baixado, "extensao", None),
        "content_type": getattr(baixado, "content_type", None),
        "verificacao": verificacao,
        "_texto": texto,
    }
    if ocr:
        registro["ocr_cache"] = cache_meta

    if (
        ocr
        and not cache_hit
        and estado is not None
        and cache_chave is not None
        and verificacao.get("ocr_usado")
        and texto.strip()
        and _documento_utilizavel(registro)
    ):
        estado.salvar_resultado_ocr(
            digesto,
            idioma_cache,
            OCR_PIPELINE_VERSION,
            configuracao_cache or {},
            {"texto": texto, "verificacao": verificacao},
        )
        cache_meta["armazenado"] = True
    return registro


def _documento_utilizavel(documento: Mapping[str, Any]) -> bool:
    verificacao_bruta = documento.get("verificacao")
    verificacao = (
        verificacao_bruta if isinstance(verificacao_bruta, Mapping) else {}
    )
    try:
        caracteres = int(
            verificacao.get("caracteres", documento.get("caracteres", 0)) or 0
        )
    except (TypeError, ValueError):
        caracteres = 0
    return bool(
        verificacao.get("abriu", documento.get("abriu"))
        and caracteres > 0
        and not verificacao.get(
            "precisa_ocr", documento.get("precisa_ocr", False)
        )
    )


def baixar_par(
    pncp: Pncp,
    candidato: dict[str, Any],
    caminhos: Caminhos,
    *,
    estado: EstadoColeta | None = None,
    ocr: bool = False,
    idioma_ocr: str = "por",
    usar_ocr: bool | None = None,
    idioma: str | None = None,
    opcoes_ocr: Mapping[str, Any] | None = None,
) -> ResultadoDownload:
    """Baixa e valida exatamente um ETP e um TR.

    Todas as revisões ativas são consideradas. A revisão mais recente é
    tentada primeiro; uma falha local de ETP/TR abre espaço para a próxima
    revisão, sem publicar as tentativas descartadas.
    """
    if usar_ocr is not None:
        ocr = usar_ocr
    if idioma is not None:
        idioma_ocr = idioma
    numero = candidato["numero_controle_pncp"]
    pid = processo_id(numero)
    destino = caminhos.documentos / pid
    documentos_tentados: list[dict[str, Any]] = []
    avaliados: dict[tuple[Any, ...], tuple[dict[str, Any] | None, str | None]] = {}
    # O nome físico do store não contém a URL. Se duas revisões compartilham
    # o mesmo papel/sequencial/título, a segunda precisa forçar a rede para
    # não validar acidentalmente o arquivo da primeira.
    bases_visitadas: set[tuple[Any, ...]] = set()
    falhas_api: list[str] = []

    revisoes = {
        ETP: _revisoes_do_candidato(candidato, ETP),
        TR: _revisoes_do_candidato(candidato, TR),
    }
    for papel in (ETP, TR):
        revisoes[papel].sort(key=_chave_revisao, reverse=True)

    def chave_arquivo(arquivo: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            arquivo.get("papel"),
            arquivo.get("sequencial_documento"),
            arquivo.get("url"),
            arquivo.get("titulo"),
        )

    def avaliar(arquivo: dict[str, Any], ordem: int) -> dict[str, Any] | None:
        chave = chave_arquivo(arquivo)
        if chave in avaliados:
            registro, _motivo = avaliados[chave]
            return registro
        url = arquivo.get("url")
        if not url:
            avaliados[chave] = (None, "URL ausente")
            return None
        base_fisica = (
            arquivo.get("papel"),
            arquivo.get("sequencial_documento"),
            arquivo.get("titulo"),
        )
        forcar_rede = base_fisica in bases_visitadas
        bases_visitadas.add(base_fisica)
        try:
            argumentos_download = (
                pncp,
                str(url),
                destino,
                str(arquivo["papel"]),
                arquivo.get("sequencial_documento"),
                str(arquivo.get("titulo") or ""),
            )
            if forcar_rede:
                try:
                    baixado = baixar_documento(
                        *argumentos_download,
                        reaproveitar=False,
                    )
                except TypeError as erro_tipo:
                    # Doubles/consumidores antigos ainda expõem os seis
                    # argumentos posicionais da função pública.
                    if "reaproveitar" not in str(erro_tipo):
                        raise
                    baixado = baixar_documento(*argumentos_download)
            else:
                baixado = baixar_documento(*argumentos_download)
        except LimiteRequisicoes:
            raise
        except RuntimeError as erro:
            # PncpError é o tipo normal; RuntimeError também cobre doubles
            # antigos que sinalizam a falha do transporte sem o tipo PNCP.
            mensagem = f"falha de API no {arquivo['papel']}: {erro}"
            falhas_api.append(mensagem)
            avaliados[chave] = (None, mensagem)
            return None
        if baixado is None:
            mensagem = f"arquivo {arquivo['papel']} ausente no download"
            avaliados[chave] = (None, mensagem)
            return None
        registro = _registrar_documento(
            documento_id(
                pid,
                arquivo["papel"],
                arquivo.get("sequencial_documento"),
                ordem,
            ),
            pid,
            numero,
            arquivo,
            baixado,
            caminhos.raiz,
            estado=estado,
            ocr=ocr,
            idioma_ocr=idioma_ocr,
            opcoes_ocr=opcoes_ocr,
        )
        documentos_tentados.append(registro)
        if not _documento_utilizavel(registro):
            verificacao = registro["verificacao"]
            if not verificacao.get("abriu"):
                motivo = (
                    f"{arquivo['papel']} não abre: "
                    f"{verificacao.get('erro') or 'erro desconhecido'}"
                )
            else:
                motivo = f"{arquivo['papel']} sem texto utilizável após download"
            avaliados[chave] = (None, motivo)
            return None
        avaliados[chave] = (registro, None)
        return registro

    # A ordem aninhada evita baixar TRs enquanto o ETP mais recente ainda é
    # inválido e, ao mesmo tempo, testa um TR anterior quando necessário.
    for arquivo_etp in revisoes[ETP]:
        documento_etp = avaliar(arquivo_etp, 1)
        if documento_etp is None:
            continue
        for arquivo_tr in revisoes[TR]:
            documento_tr = avaliar(arquivo_tr, 2)
            if documento_tr is None:
                continue
            return ResultadoDownload(
                True,
                [documento_etp, documento_tr],
                tentativas_documentais=documentos_tentados,
            )

    if falhas_api:
        motivo = "falha de API em documentos: " + "; ".join(falhas_api)
    else:
        motivos = [
            motivo
            for _registro, motivo in avaliados.values()
            if motivo and not motivo.startswith("falha de API")
        ]
        motivo = (
            "documentos ETP/TR não utilizáveis após download"
            + (f": {motivos[-1]}" if motivos else "")
        )
    return ResultadoDownload(
        False,
        documentos_tentados,
        motivo,
        documentos_tentados,
    )


def baixar_cadeia_completa(
    pncp: Pncp,
    candidato: Mapping[str, Any],
    caminhos: Caminhos,
    *,
    estado: EstadoColeta | None = None,
    ocr: bool = False,
    idioma_ocr: str = "por",
    usar_ocr: bool | None = None,
    idioma: str | None = None,
    opcoes_ocr: Mapping[str, Any] | None = None,
) -> ResultadoDownload:
    """Baixa exatamente ETP, TR, edital e instrumento contratual.

    Cada papel pode ter revisões ativas; a mais recente é tentada primeiro e
    uma revisão anterior só é usada quando a atual não é utilizável. O aceite
    só é retornado depois de os quatro papéis passarem pela verificação local.
    Os arquivos individuais continuam sendo gravados pelo store com replace
    atômico; nenhum catálogo/aceite é escrito por esta função em caso parcial.
    """
    if usar_ocr is not None:
        ocr = usar_ocr
    if idioma is not None:
        idioma_ocr = idioma
    try:
        numero = str(candidato["numero_controle_pncp"])
        pid = processo_id(numero)
    except (KeyError, TypeError, ValueError) as erro:
        return ResultadoDownload(False, [], f"candidato sem número PNCP: {erro}", [])

    destino = caminhos.documentos / pid
    tentativas: list[dict[str, Any]] = []
    escolhidos: list[dict[str, Any]] = []
    falhas_api: list[str] = []

    def chave(arquivo: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            arquivo.get("papel"),
            arquivo.get("sequencial_documento"),
            arquivo.get("url"),
            arquivo.get("titulo"),
        )

    vistos: set[tuple[Any, ...]] = set()
    bases_visitadas: set[tuple[Any, ...]] = set()
    for ordem, papel in enumerate(PAPEIS_CADEIA_COMPLETA, start=1):
        revisoes = _revisoes_do_candidato(candidato, papel)
        revisoes.sort(key=_chave_revisao, reverse=True)
        # Candidatos montados por consumidores simples podem trazer somente
        # ``documentos_cadeia``; uma ausência aqui vira motivo explícito.
        if not revisoes:
            return ResultadoDownload(
                False,
                tentativas,
                f"documento obrigatório ausente: {papel}",
                tentativas,
            )
        documento_utilizavel: dict[str, Any] | None = None
        motivos: list[str] = []
        for arquivo in revisoes:
            arquivo = dict(arquivo)
            identidade = chave(arquivo)
            if identidade in vistos:
                continue
            vistos.add(identidade)
            url = arquivo.get("url") or arquivo.get("uri")
            if not url:
                motivos.append(f"{papel}: URL ausente")
                continue
            base_fisica = (
                papel,
                _int(arquivo.get("sequencial_documento")),
                str(arquivo.get("titulo") or ""),
            )
            forcar_rede = base_fisica in bases_visitadas
            bases_visitadas.add(base_fisica)
            try:
                argumentos_download = (
                    pncp,
                    str(url),
                    destino,
                    papel,
                    _int(arquivo.get("sequencial_documento")),
                    str(arquivo.get("titulo") or ""),
                )
                if forcar_rede:
                    try:
                        baixado = baixar_documento(
                            *argumentos_download, reaproveitar=False
                        )
                    except TypeError as erro_tipo:
                        # Doubles/consumidores antigos ainda expõem somente os
                        # seis argumentos posicionais da função pública.
                        if "reaproveitar" not in str(erro_tipo):
                            raise
                        baixado = baixar_documento(*argumentos_download)
                else:
                    baixado = baixar_documento(*argumentos_download)
            except LimiteRequisicoes:
                raise
            except (RuntimeError, ValueError, OSError) as erro:
                if isinstance(erro, RuntimeError):
                    mensagem = f"falha de API no {papel}: {erro}"
                    falhas_api.append(mensagem)
                else:
                    mensagem = f"falha ao baixar {papel}: {erro}"
                motivos.append(mensagem)
                continue
            if baixado is None:
                motivos.append(f"{papel}: arquivo ausente no download")
                continue
            try:
                registro = _registrar_documento(
                    documento_id(
                        pid, papel, arquivo.get("sequencial_documento"), ordem
                    ),
                    pid,
                    numero,
                    arquivo,
                    baixado,
                    caminhos.raiz,
                    estado=estado,
                    ocr=ocr,
                    idioma_ocr=idioma_ocr,
                    opcoes_ocr=opcoes_ocr,
                )
            except (RuntimeError, ValueError, OSError) as erro:
                motivos.append(f"falha ao verificar {papel}: {erro}")
                continue
            tentativas.append(registro)
            if _documento_utilizavel(registro):
                documento_utilizavel = registro
                break
            verificacao = registro.get("verificacao") or {}
            if not verificacao.get("abriu"):
                motivos.append(
                    f"{papel} não abre: {verificacao.get('erro') or 'erro desconhecido'}"
                )
            else:
                motivos.append(f"{papel} sem texto utilizável após download")
        if documento_utilizavel is None:
            detalhe = motivos[-1] if motivos else f"{papel} sem revisão utilizável"
            if falhas_api and all(m.startswith("falha de API") for m in motivos):
                detalhe = "; ".join(motivos)
            return ResultadoDownload(
                False,
                tentativas,
                f"cadeia incompleta: {detalhe}",
                tentativas,
            )
        escolhidos.append(documento_utilizavel)

    # A ordem é parte do contrato: ETP, TR, EDITAL, CONTRATO. Uma revisão não
    # pode fazer o resultado conter dois documentos do mesmo papel.
    if len(escolhidos) != len(PAPEIS_CADEIA_COMPLETA) or {
        d.get("papel") for d in escolhidos
    } != set(PAPEIS_CADEIA_COMPLETA):
        return ResultadoDownload(
            False,
            tentativas,
            "cadeia incompleta após verificação dos quatro papéis",
            tentativas,
        )
    return ResultadoDownload(True, escolhidos, None, tentativas)


# --------------------------------------------------------- revalidação/policy


def _revalidar_aceito(
    candidato: dict[str, Any],
    documentos: Sequence[dict[str, Any]],
    raiz: Path,
    *,
    ocr: bool = False,
    idioma_ocr: str = "por",
    opcoes_ocr: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Revalida um aceite antigo só em disco, sem chamar o PNCP."""
    por_papel: dict[str, list[dict[str, Any]]] = {
        papel: [] for papel in PAPEIS_CADEIA_COMPLETA
    }
    for documento in documentos:
        papel = documento.get("papel")
        if papel not in por_papel:
            # Tipos auxiliares não fazem parte da cadeia material publicada.
            continue
        por_papel[papel].append(documento)
    if any(len(por_papel[papel]) != 1 for papel in (ETP, TR)):
        return None

    def revalidar_documento(original_bruto: Mapping[str, Any]) -> dict[str, Any] | None:
        original = dict(original_bruto)
        relativo = original.get("arquivo")
        if not relativo:
            return None
        caminho = Path(str(relativo))
        if not caminho.is_absolute():
            caminho = raiz / caminho
        try:
            conteudo = caminho.read_bytes()
        except (OSError, ValueError):
            return None
        hash_original = original.get("sha256_original") or original.get(
            "hash_original"
        )
        esperado = hash_original or original.get("sha256") or original.get("hash")
        digesto = hashlib.sha256(conteudo).hexdigest()
        if not esperado or digesto != str(esperado):
            return None
        bytes_esperados = original.get("bytes")
        if bytes_esperados is not None:
            try:
                if int(bytes_esperados) != len(conteudo):
                    return None
            except (TypeError, ValueError):
                return None
        resultado = _chamar_verificar(
            caminho,
            ocr=ocr,
            idioma_ocr=idioma_ocr,
            opcoes_ocr=opcoes_ocr,
        )
        registro = dict(original)
        registro["sha256"] = digesto
        registro["sha256_original"] = digesto
        registro["hash_original"] = digesto
        registro["bytes"] = len(conteudo)

        # O OCR histórico é texto derivado; o arquivo original permanece
        # intocado. Quando seu hash original confere e o contêiner ainda abre,
        # preserve tanto o texto quanto os metadados que provaram o uso do OCR.
        abriu = bool(_atributo(resultado, "abriu", False))
        ocr_historico = bool(
            hash_original
            and ocr_historico_utilizavel(original, abriu=abriu)
        )
        if not ocr_historico:
            registro["verificacao"] = _metadados_verificacao(resultado)
            registro["_texto"] = _atributo(resultado, "texto", "") or ""
            if not _documento_utilizavel(registro):
                return None
        return registro

    novos: list[dict[str, Any]] = []
    for papel in (ETP, TR):
        registro = revalidar_documento(por_papel[papel][0])
        if registro is None:
            return None
        novos.append(registro)

    # Promoções históricas podem já ter gravado edital/contrato no aceite.
    # Revalidamos e preservamos no máximo a revisão ativa de cada papel, sem
    # deixar um elo opcional ilegível impedir a continuidade do par histórico.
    for papel in (EDITAL, CONTRATO):
        if not por_papel[papel]:
            continue
        registro = revalidar_documento(
            max(por_papel[papel], key=_chave_revisao)
        )
        if registro is not None:
            novos.append(registro)

    # O aceite migrado mantém o candidato original; a verificação física de
    # cada elo preservado é atualizada. Isso mantém promoções legadas e URLs/
    # revisões mesmo quando o registro antigo não tinha o formato mais novo.
    novo_candidato = dict(candidato)
    return novo_candidato, novos


def _migrar_aceitos_legados(
    estado: EstadoColeta,
    raiz: Path,
    *,
    ocr: bool = False,
    idioma_ocr: str = "por",
    opcoes_ocr: Mapping[str, Any] | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Migra o melhor aceite legado de cada processo sem perder elos.

    Um mesmo processo pode existir em várias políticas históricas. Escolher a
    primeira linha de ``aceitos(None)`` descartaria uma promoção posterior
    (por exemplo, o EDITAL adicionado em uma policy mais nova). Agrupamos por
    processo, preferimos a opção com mais papéis e, em caso de empate, a última
    linha persistida; elos opcionais ausentes nessa opção são herdados da
    opção histórica mais recente que os contenha.
    """
    # Só pule um número que já tenha um aceite vigente realmente completo.
    # Uma linha v6 parcial pode coexistir com a linha histórica que contém
    # edital/contrato; tratá-la como ativa faria a migração perder esses elos
    # e impediria a promoção posterior sem novo download.
    ativos = {
        str(candidato.get("numero_controle_pncp") or "")
        for candidato, documentos in estado.aceitos()
        if _documentos_formam_cadeia_completa(documentos)
        and _candidato_tem_vinculo_contrato(candidato)
    }
    por_numero: dict[
        str, list[tuple[int, dict[str, Any], list[dict[str, Any]]]]
    ] = {}
    for indice, (candidato, documentos) in enumerate(estado.aceitos(None)):
        numero = str(candidato.get("numero_controle_pncp") or "")
        if not numero:
            continue
        por_numero.setdefault(numero, []).append(
            (indice, candidato, list(documentos))
        )

    migrados = 0
    for numero, opcoes in por_numero.items():
        if numero in ativos:
            continue
        _indice, candidato, documentos = max(
            opcoes,
            key=lambda item: (
                sum(
                    1
                    for documento in item[2]
                    if documento.get("papel") in PAPEIS_CADEIA_COMPLETA
                ),
                len(item[2]),
                item[0],
            ),
        )
        # Uma promoção opcional pode ter sido gravada numa policy diferente da
        # opção escolhida. Preserve esse elo, sem multiplicar ETP/TR (o helper
        # de revalidação exige exatamente um de cada papel obrigatório).
        documentos = list(documentos)
        papeis_presentes = {str(d.get("papel") or "") for d in documentos}
        for papel in (EDITAL, CONTRATO):
            if papel in papeis_presentes:
                continue
            for _indice, _candidato, documentos_alternativos in reversed(opcoes):
                candidatos_papel = [
                    documento
                    for documento in documentos_alternativos
                    if documento.get("papel") == papel
                ]
                if candidatos_papel:
                    documentos.append(
                        max(candidatos_papel, key=_chave_revisao)
                    )
                    break
        candidato = dict(candidato)
        contratos_candidato = candidato.get("contratos")
        tem_contrato_candidato = isinstance(contratos_candidato, Sequence) and any(
            isinstance(item, Mapping) for item in contratos_candidato
        )
        if not tem_contrato_candidato:
            for _indice, candidato_alternativo, _documentos_alternativos in reversed(
                opcoes
            ):
                contratos_alternativos = candidato_alternativo.get("contratos")
                if isinstance(contratos_alternativos, Sequence) and any(
                    isinstance(item, Mapping) for item in contratos_alternativos
                ):
                    candidato["contratos"] = [
                        dict(item)
                        for item in contratos_alternativos
                        if isinstance(item, Mapping)
                    ]
                    contrato_alternativo = candidato_alternativo.get("contrato")
                    if isinstance(contrato_alternativo, Mapping):
                        candidato["contrato"] = dict(contrato_alternativo)
                    break
        compra = candidato.get("compra")
        if not isinstance(compra, dict):
            compra = candidato
        aceitavel, _motivo = _aceitavel(compra, None, preliminar=False)
        if not aceitavel:
            # Aceite fora do perfil atual continua auditável no estado, porém
            # nunca migra para a política vigente.
            continue
        revalidado = _revalidar_aceito(
            candidato,
            documentos,
            raiz,
            ocr=ocr,
            idioma_ocr=idioma_ocr,
            opcoes_ocr=opcoes_ocr,
        )
        if revalidado is None:
            continue
        novo_candidato, novos_documentos = revalidado
        compra = novo_candidato.get("compra")
        if not isinstance(compra, dict):
            compra = candidato
        estado.salvar_aceito(novo_candidato, novos_documentos)
        estado.salvar_inspecao(
            numero,
            compra,
            status="ACEITO",
            arquivos=novos_documentos,
            candidato=novo_candidato,
        )
        ativos.add(numero)
        migrados += 1
        log(f"  revalidado sem download {numero}")
    return migrados


# ---------------------------------------------------------------- cache/API


def _cache_resposta(
    estado: EstadoColeta,
    fonte: str,
    parametros: dict[str, Any],
    chamar: Callable[[], Any],
) -> Any:
    """Lê/grava cache pelos métodos públicos, incluindo respostas vazias."""
    chave = estado.chave_resposta(fonte, parametros)
    anterior = estado.resposta(chave)
    if anterior is not None:
        return anterior
    payload = chamar()
    # EstadoColeta escolhe TTL curto para payload vazio e longo para payload
    # positivo; não transforme exceção de API em cache vazio.
    estado.salvar_resposta(chave, payload)
    return payload


def _desempacotar_pagina(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if isinstance(payload, (tuple, list)) and len(payload) == 2:
        registros, total = payload
    elif isinstance(payload, Mapping):
        registros = payload.get("items", payload.get("resultado", payload.get("data")))
        total = payload.get("total", payload.get("totalPaginas"))
    else:
        raise PncpError("resposta paginada inválida")
    if not isinstance(registros, list) or not all(
        isinstance(registro, dict) for registro in registros
    ):
        raise PncpError("resposta paginada sem lista de registros válida")
    if not isinstance(total, int) or total < 0:
        raise PncpError("resposta paginada sem total válido")
    return registros, total


def _parametros_tarefa(tarefa: Mapping[str, Any]) -> dict[str, Any]:
    parametros = tarefa.get("parametros")
    if isinstance(parametros, Mapping):
        return dict(parametros)
    parametros_json = tarefa.get("parametros_json")
    if parametros_json:
        try:
            carregados = json.loads(str(parametros_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            carregados = {}
        if isinstance(carregados, Mapping):
            return dict(carregados)
    return {}


def _criar_tarefa_pagina(
    estado: EstadoColeta,
    fonte: str,
    base: Mapping[str, Any],
    pagina: int,
    tamanho: int,
) -> dict[str, Any]:
    parametros = dict(base)
    parametros["pagina"] = pagina
    parametros["tamanho"] = tamanho
    return estado.criar_tarefa_paginacao(
        fonte,
        parametros,
        pagina,
        tamanho_pagina=tamanho,
    )


def _buscar_pagina_tarefa(
    estado: EstadoColeta,
    tarefa: Mapping[str, Any],
    pncp: Pncp,
    compras: ComprasGov,
) -> Any:
    fonte = str(tarefa.get("fonte") or "")
    parametros = _parametros_tarefa(tarefa)
    pagina = _int(tarefa.get("pagina")) or _int(parametros.get("pagina")) or 1
    tamanho = (
        _int(tarefa.get("tamanho_pagina"))
        or _int(parametros.get("tamanho"))
        or 500
    )

    def chamar() -> Any:
        if fonte in {"pncp-contratos", "pncp-feed-contratos"}:
            inicio = str(parametros.get("inicio") or "").replace("-", "")
            fim = str(parametros.get("fim") or "").replace("-", "")
            return pncp.pagina_contratos_publicados(
                inicio,
                fim,
                pagina=pagina,
                tamanho_pagina=(min(500, max(1, tamanho)) if tamanho else None),
            )
        if fonte == "pncp-busca":
            termo = parametros.get("termo", parametros.get("q"))
            if not termo:
                raise PncpError("tarefa de busca sem termo")
            return pncp.busca_portal(
                str(termo), pagina=pagina, tamanho_pagina=min(50, tamanho)
            )
        if fonte == "compras-gov":
            inicio = str(parametros.get("inicio") or "")
            fim = str(parametros.get("fim") or "")
            return compras.pagina_contratacoes(
                inicio,
                fim,
                pagina=pagina,
                tamanho_pagina=min(500, max(10, tamanho)),
            )
        if fonte == "pncp-feed":
            inicio = str(parametros.get("inicio") or "").replace("-", "")
            fim = str(parametros.get("fim") or "").replace("-", "")
            return pncp.pagina_contratacoes_publicadas(
                inicio,
                fim,
                pagina=pagina,
                modalidade=6,
                tamanho_pagina=min(500, max(1, tamanho)),
            )
        raise PncpError(f"fonte de paginação desconhecida: {fonte}")

    return _cache_resposta(estado, fonte, parametros, chamar)


def _arquivos_com_cache(
    estado: EstadoColeta, pncp: Pncp, compra: dict[str, Any]
) -> list[dict[str, Any]]:
    cnpj, ano, seq = partes_controle(compra["numero_controle_pncp"])
    payload = _cache_resposta(
        estado,
        "pncp-arquivos",
        {"numero": compra["numero_controle_pncp"]},
        lambda: pncp.arquivos_compra(cnpj, ano, seq),
    )
    if not isinstance(payload, list):
        raise PncpError("lista de arquivos da contratação inválida")
    return payload


def _detalhe_com_cache(
    estado: EstadoColeta, pncp: Pncp, numero: str
) -> dict[str, Any]:
    """Obtém o detalhe da contratação uma vez por número e por TTL."""
    cnpj, ano, seq = partes_controle(numero)
    payload = _cache_resposta(
        estado,
        "pncp-detalhe-compra",
        {"numero": numero},
        lambda: pncp.detalhe_compra(cnpj, ano, seq),
    )
    if not isinstance(payload, dict):
        raise PncpError("detalhe de contratação inválido")
    return payload


def _arquivos_contrato_com_cache(
    estado: EstadoColeta, pncp: Pncp, contrato: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Consulta os anexos do instrumento uma única vez por contrato."""
    numero = str(contrato.get("numero_controle_pncp") or "")
    if not numero:
        raise PncpError("contrato sem número para listar arquivos")
    cnpj, ano, seq = partes_controle(numero)
    payload = _cache_resposta(
        estado,
        "pncp-arquivos-contrato",
        {"numero": numero},
        lambda: pncp.arquivos_contrato(cnpj, ano, seq),
    )
    if not isinstance(payload, list):
        raise PncpError("lista de arquivos do contrato inválida")
    return payload


# ------------------------------------------------------------- confirmação


def _datas_para_confirmacao(compra: Mapping[str, Any]) -> tuple[str, str]:
    publicada = _data_iso(compra.get("data_publicacao_pncp"))
    if publicada is not None:
        texto = publicada.isoformat()
        return texto, texto
    try:
        ano = partes_controle(str(compra["numero_controle_pncp"]))[1]
    except (KeyError, TypeError, ValueError) as erro:
        raise PncpError("candidato da busca sem ano utilizável") from erro
    return f"{ano:04d}-01-01", f"{ano:04d}-12-31"


def _confirmar_busca_no_pncp(
    estado: EstadoColeta,
    pncp: Pncp,
    compra: dict[str, Any],
) -> dict[str, Any]:
    """Confirma a busca no feed PNCP paginado, antes de listar arquivos."""
    data_inicio, data_fim = _datas_para_confirmacao(compra)
    cnpj = str(compra.get("cnpj_orgao") or "")
    data = data_inicio.replace("-", "")
    data_final = data_fim.replace("-", "")
    pagina = 1
    while pagina <= 1000:
        parametros = {
            "data": data,
            "data_final": data_final,
            "cnpj": cnpj,
            "pagina": pagina,
            "tamanho": 50,
        }
        resposta = _cache_resposta(
            estado,
            "pncp-confirmacao-feed",
            {"numero": compra["numero_controle_pncp"], **parametros},
            lambda pagina=pagina: pncp.pagina_contratacoes_publicadas(
                data,
                data_final,
                pagina=pagina,
                modalidade=6,
                cnpj=cnpj or None,
                tamanho_pagina=50,
            ),
        )
        registros, total = _desempacotar_pagina(resposta)
        for registro in registros:
            numero = _campo(registro, "numeroControlePNCP", "numero_controle_pncp")
            if str(numero or "") == compra["numero_controle_pncp"]:
                try:
                    confirmado = normalizar_compra(
                        registro, "pncp_busca+pncp_confirmacao"
                    )
                except ValueError as erro:
                    raise PncpError(f"confirmação PNCP inconsistente: {erro}") from erro
                for chave, valor in compra.items():
                    if confirmado.get(chave) in (None, "") and valor not in (None, ""):
                        confirmado[chave] = valor
                return confirmado
        if pagina >= total or not registros:
            break
        pagina += 1
    raise PncpError(
        f"compra não retornada pela confirmação do feed PNCP: "
        f"{compra['numero_controle_pncp']}"
    )


def _confirmar_busca_no_compras(
    estado: EstadoColeta,
    compras: ComprasGov,
    compra: dict[str, Any],
) -> dict[str, Any]:
    """Fallback de confirmação no feed paginado do Compras.gov.br."""
    data, data_final = _datas_para_confirmacao(compra)
    cnpj = str(compra.get("cnpj_orgao") or "")
    pagina = 1
    while pagina <= 1000:
        resposta = _cache_resposta(
            estado,
            "compras-confirmacao",
            {
                "numero": compra["numero_controle_pncp"],
                "data": data,
                "data_final": data_final,
                "cnpj": cnpj,
                "pagina": pagina,
                "tamanho": 10,
            },
            lambda pagina=pagina: compras.pagina_contratacoes(
                data,
                data_final,
                pagina=pagina,
                tamanho_pagina=10,
                cnpj=cnpj or None,
            ),
        )
        registros, total = _desempacotar_pagina(resposta)
        for registro in registros:
            numero = _campo(registro, "numeroControlePNCP", "numero_controle_pncp")
            if str(numero or "") == compra["numero_controle_pncp"]:
                try:
                    confirmado = normalizar_compra(
                        registro, "pncp_busca+compras_confirmacao"
                    )
                except ValueError as erro:
                    raise PncpError(
                        f"confirmação Compras.gov.br inconsistente: {erro}"
                    ) from erro
                for chave, valor in compra.items():
                    if confirmado.get(chave) in (None, "") and valor not in (None, ""):
                        confirmado[chave] = valor
                return confirmado
        if pagina >= total or not registros:
            break
        pagina += 1
    raise PncpError(
        f"compra não retornada pela confirmação Compras.gov.br: "
        f"{compra['numero_controle_pncp']}"
    )


def _reaproveitar_inspecao(estado: EstadoColeta, numero: str) -> bool:
    status = estado.status_inspecao(numero)
    return status in {
        "SEM_PAR_ETP_TR",
        # Inspeções antigas de par continuam reutilizáveis; uma inspeção nova
        # sem cadeia deve ser reavaliada em retomadas futuras, pois o órgão
        # pode publicar o elo que faltava.
        "FORA_DO_ESCOPO",
        "LIMITE_ORGAO",
        "DOWNLOAD_REPROVADO",
    }


def _documentos_formam_cadeia_completa(
    documentos: Sequence[Mapping[str, Any]],
) -> bool:
    """Verdadeiro somente para um documento utilizável de cada elo exigido."""
    papeis = [str(documento.get("papel") or "") for documento in documentos]
    return (
        len(documentos) == len(PAPEIS_CADEIA_COMPLETA)
        and len(set(papeis)) == len(PAPEIS_CADEIA_COMPLETA)
        and set(papeis) == set(PAPEIS_CADEIA_COMPLETA)
        and all(_documento_utilizavel(documento) for documento in documentos)
    )


def _candidato_tem_vinculo_contrato(candidato: Mapping[str, Any]) -> bool:
    """Confere o vínculo exato exigido para considerar um aceite completo."""
    numero_compra = str(candidato.get("numero_controle_pncp") or "").strip()
    contratos = candidato.get("contratos")
    if not isinstance(contratos, Sequence) or isinstance(contratos, (str, bytes)):
        contrato = candidato.get("contrato")
        contratos = [contrato] if isinstance(contrato, Mapping) else []
    return any(
        isinstance(contrato, Mapping)
        and str(contrato.get("numero_controle_pncp_compra") or "").strip()
        == numero_compra
        and contrato.get("criterio_vinculo") == "numeroControlePncpCompra"
        for contrato in contratos
    )


def _aceitos_no_perfil(
    aceitos: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Aceites que ainda satisfazem o perfil vigente, em qualquer esfera."""
    resultado: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for candidato, documentos in aceitos:
        compra = candidato.get("compra")
        if not isinstance(compra, dict):
            compra = candidato
        aceitavel, _motivo = _aceitavel(compra, None, preliminar=False)
        if aceitavel:
            resultado.append((candidato, documentos))
    return resultado


def _aceitos_completos(
    aceitos: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    esferas: set[str] | frozenset[str] | None = None,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Aceites do perfil que podem contar para o alvo novo.

    Aceites históricos de apenas ETP/TR permanecem visíveis no catálogo, mas
    não satisfazem o alvo da coleta por cadeias completas.
    """
    resultado: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    permitidas = None if esferas is None else set(esferas)
    for candidato, documentos in aceitos:
        compra = candidato.get("compra")
        if not isinstance(compra, dict):
            compra = candidato
        aceitavel, _motivo = _aceitavel(compra, permitidas, preliminar=False)
        if (
            aceitavel
            and _documentos_formam_cadeia_completa(documentos)
            and _candidato_tem_vinculo_contrato(candidato)
        ):
            resultado.append((candidato, documentos))
    return resultado


def _contagens_orgaos(
    aceitos: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]]
) -> Counter[str]:
    return Counter(_cnpj_da_compra(c.get("compra", {})) for c, _ in aceitos)


def _contagens_tentativas_documentais(estado: EstadoColeta) -> Counter[str]:
    """Conta rejeições documentais persistidas, ignorando ERRO_API."""
    contagens: Counter[str] = Counter()
    for reprovado in estado.reprovados():
        numero = str(reprovado.get("numero_controle_pncp") or "")
        if estado.status_inspecao(numero) != "DOWNLOAD_REPROVADO":
            continue
        inspecao = estado.inspecao(numero)
        compra = inspecao.get("compra") if inspecao else None
        if not isinstance(compra, dict):
            compra = {}
        orgao = _cnpj_da_compra(compra)
        if not orgao:
            try:
                orgao = partes_controle(numero)[0]
            except ValueError:
                orgao = ""
        contagens[orgao] += 1
    return contagens


# -------------------------------------------------------------- catálogo/stats


def _estatisticas_tarefas(
    estado: EstadoColeta, *, fonte: str | None = None
) -> dict[str, Any]:
    """Resume a fila da fonte ativa, sem misturar tarefas históricas."""
    tarefas_todas = estado.listar_tarefas_paginacao()
    tarefas = (
        tarefas_todas
        if fonte is None
        else [
            tarefa
            for tarefa in tarefas_todas
            if str(tarefa.get("fonte") or "") == str(fonte)
        ]
    )
    por_status = Counter(str(tarefa.get("status")) for tarefa in tarefas)
    retry = [
        {
            "fonte": tarefa.get("fonte"),
            "pagina": tarefa.get("pagina"),
            "erro": tarefa.get("erro"),
            "tentativas": tarefa.get("tentativas"),
        }
        for tarefa in tarefas
        if tarefa.get("status") == RETRY
    ]
    incompleta = bool(
        por_status.get("PENDENTE", 0)
        or por_status.get(RETRY, 0)
    )
    return {
        "tarefas_paginacao": len(tarefas),
        "paginas_concluidas": por_status.get(CONCLUIDO, 0),
        "paginas_pendentes": por_status.get("PENDENTE", 0),
        "paginas_retry": por_status.get(RETRY, 0),
        "erros_paginas": retry,
        "cobertura_incompleta": incompleta,
        "cobertura_paginas_incompleta": incompleta,
    }


def _controles_catalogados(
    caminhos: Caminhos,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Preserva controles negativos entre recatalogações.

    Controles não são aceites da policy ativa e jamais contam para o alvo, mas
    precisam continuar fisicamente auditáveis no manifesto externo.
    """
    caminho_processos = caminhos.catalogo / "processos.json"
    if not caminho_processos.exists():
        return [], [], []
    anteriores = json.loads(caminho_processos.read_text(encoding="utf-8"))
    controles = [
        dict(processo)
        for processo in anteriores
        if processo.get("scope_status") == "OUT_OF_SCOPE"
        and (processo.get("orgao") or {}).get("esfera") == "M"
    ]
    ids = {str(processo.get("processo_id") or "") for processo in controles}
    ids.discard("")

    documentos: list[dict[str, Any]] = []
    caminho_documentos = caminhos.catalogo / "documentos.jsonl"
    if caminho_documentos.exists():
        for linha in caminho_documentos.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                documento = json.loads(linha)
                if str(documento.get("processo_id") or "") in ids:
                    documentos.append(documento)

    relacoes: list[dict[str, Any]] = []
    caminho_relacoes = caminhos.catalogo / "relacoes.json"
    if caminho_relacoes.exists():
        payload = json.loads(caminho_relacoes.read_text(encoding="utf-8"))
        relacoes = [
            dict(relacao)
            for relacao in payload.get("cadeia", [])
            if str(relacao.get("processo_id") or "") in ids
        ]
    return controles, documentos, relacoes


def _catalogar(
    caminhos: Caminhos,
    estado: EstadoColeta,
    *,
    alvo: int,
    fonte: str,
    log: Callable[[str], None],
    cobertura_incompleta: bool | None = None,
) -> dict[str, Any]:
    aceitos = _aceitos_no_perfil(estado.aceitos())
    # Catálogos anteriores são históricos e não podem desaparecer quando a
    # policy nova passa a publicar somente cadeias completas. Eles são
    # substituídos apenas se o mesmo processo tiver um aceite novo.
    processos_anteriores: list[dict[str, Any]] = []
    documentos_anteriores: list[dict[str, Any]] = []
    relacoes_anteriores: list[dict[str, Any]] = []
    caminho_processos = caminhos.catalogo / "processos.json"
    if caminho_processos.exists():
        try:
            bruto_processos = json.loads(caminho_processos.read_text(encoding="utf-8"))
            processos_anteriores = list(
                bruto_processos.get("processos", [])
                if isinstance(bruto_processos, dict)
                else bruto_processos
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            processos_anteriores = []
    caminho_documentos = caminhos.catalogo / "documentos.jsonl"
    if caminho_documentos.exists():
        try:
            documentos_anteriores = [
                json.loads(linha)
                for linha in caminho_documentos.read_text(encoding="utf-8").splitlines()
                if linha.strip()
            ]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            documentos_anteriores = []
    caminho_relacoes = caminhos.catalogo / "relacoes.json"
    if caminho_relacoes.exists():
        try:
            bruto_relacoes = json.loads(caminho_relacoes.read_text(encoding="utf-8"))
            if isinstance(bruto_relacoes, dict):
                relacoes_anteriores = list(bruto_relacoes.get("cadeia", []))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            relacoes_anteriores = []
    processos: list[dict[str, Any]] = []
    documentos_com_texto: list[dict[str, Any]] = []
    relacoes: list[dict[str, Any]] = []

    for candidato, documentos in aceitos:
        compra_candidata = candidato.get("compra")
        if not isinstance(compra_candidata, dict):
            compra_candidata = candidato
        aceitavel, _motivo = _aceitavel(
            compra_candidata, None, preliminar=False
        )
        if not aceitavel:
            # Proteção contra aceite injetado: o catálogo aprovado só publica
            # o que satisfaz o perfil vigente.
            continue
        documentos_par = [
            dict(documento)
            for documento in documentos
            if documento.get("papel") in PAPEIS_DO_LOTE
        ]
        if not documentos_par:
            continue
        pid = processo_id(candidato["numero_controle_pncp"])
        documentos_locais: list[dict[str, Any]] = []
        for documento in documentos_par:
            registro = dict(documento)
            caminho = caminhos.raiz / registro["arquivo"]
            resultado = verificar(caminho)
            texto_salvo = registro.get("_texto")
            ocr_usado = bool(
                (registro.get("verificacao") or {}).get("ocr_usado")
                or ((registro.get("verificacao") or {}).get("ocr") or {}).get("usado")
            )
            # Não execute OCR novamente só para catalogar. O texto efetivo
            # produzido na coleta é a fonte persistida; a abertura normal ainda
            # confere se o arquivo continua acessível.
            registro["_texto"] = (
                texto_salvo
                if ocr_usado and texto_salvo is not None
                else resultado.texto
            )
            documentos_locais.append(registro)
        extras = {"fonte": fonte}
        extras_candidato = candidato.get("extras")
        if isinstance(extras_candidato, Mapping):
            extras.update(extras_candidato)
        contratos = candidato.get("contratos")
        if not isinstance(contratos, Sequence) or isinstance(contratos, (str, bytes)):
            contrato_unico = candidato.get("contrato")
            contratos = [contrato_unico] if isinstance(contrato_unico, Mapping) else []
        contratos_validos = [
            dict(contrato) for contrato in contratos if isinstance(contrato, Mapping)
        ]
        if contratos_validos and not extras.get("processo_administrativo"):
            extras["processo_administrativo"] = contratos_validos[0].get("processo")
            extras["processo_administrativo_fonte"] = "contrato_pncp"
        processo = montar_processo(
            candidato["compra"], extras, documentos_locais, contratos_validos
        )
        cadeia_completa = (
            _documentos_formam_cadeia_completa(documentos_locais)
            and _candidato_tem_vinculo_contrato(candidato)
        )
        if not cadeia_completa:
            # Quatro arquivos sem o metadado que prova o elo contrato→compra
            # não podem ser rotulados como cadeia nova/completa. O gate ainda
            # pode apontar um histórico malformado, mas a publicação e as
            # estatísticas permanecem conservadoras.
            processo["escopo_documental"]["cadeia_completa"] = False
        if cadeia_completa:
            # A aceitação vigente é a única forma de publicar uma cadeia nova.
            # Aceites de ETP/TR migrados para a policy atual continuam
            # históricos e não podem ganhar artificialmente a versão nova.
            processo["policy_version"] = estado.policy_version
            processo["collection_policy_version"] = estado.policy_version
        else:
            # O catálogo histórico pode conter aceites antigos que foram
            # revalidados sem download. Preserve sua origem documental para que
            # o gate aplique a regra de compatibilidade (ETP/TR) e não a nova.
            politica_historica = str(
                candidato.get("collection_policy_version")
                or candidato.get("policy_version")
                or "4-municipal-historical-ocr"
            ).strip() or "4-municipal-historical-ocr"
            processo["policy_version"] = politica_historica
            processo["collection_policy_version"] = politica_historica
        processos.append(processo)
        relacoes.extend(montar_relacoes(pid, processo["cadeia"]))
        documentos_com_texto.extend(documentos_locais)
        escrever_json(caminhos.documentos / pid / "metadata.json", processo)

    ids_ativos = {str(processo.get("processo_id") or "") for processo in processos}
    ids_historicos = {
        str(processo.get("processo_id") or "")
        for processo in processos_anteriores
        if str(processo.get("processo_id") or "") not in ids_ativos
    }
    processos.extend(
        processo
        for processo in processos_anteriores
        if str(processo.get("processo_id") or "") in ids_historicos
    )
    documentos_com_texto.extend(
        documento
        for documento in documentos_anteriores
        if str(documento.get("processo_id") or "") in ids_historicos
    )
    relacoes.extend(
        relacao
        for relacao in relacoes_anteriores
        if str(relacao.get("processo_id") or "") in ids_historicos
    )

    marcas = reuse.detectar(
        [
            reuse.DocumentoTexto(
                d["documento_id"],
                d["processo_id"],
                d["papel"],
                d["sha256"],
                d.get("_texto", ""),
            )
            for d in documentos_com_texto
        ]
    )
    por_documento: dict[str, list[dict[str, Any]]] = {}
    for marca in marcas:
        entrada = {
            "tipo": marca.tipo,
            "com": marca.outro_documento_id,
            "mesmo_processo": marca.mesmo_processo,
            "jaccard": marca.jaccard,
            "contencao": marca.contencao,
            "detalhe": marca.detalhe,
        }
        por_documento.setdefault(marca.documento_id, []).append(entrada)
        por_documento.setdefault(marca.outro_documento_id, []).append(
            {**entrada, "com": marca.documento_id}
        )

    documentos_publicos: list[dict[str, Any]] = []
    for documento in documentos_com_texto:
        publico = {k: v for k, v in documento.items() if k != "_texto"}
        publico["reuso"] = por_documento.get(documento["documento_id"], [])
        documentos_publicos.append(publico)

    escrever_json(caminhos.catalogo / "processos.json", processos)
    escrever_jsonl(caminhos.catalogo / "documentos.jsonl", documentos_publicos)
    escrever_json(
        caminhos.catalogo / "relacoes.json",
        {
            "cadeia": relacoes,
            "reuso": [
                {
                    "documento_id": m.documento_id,
                    "outro_documento_id": m.outro_documento_id,
                    "tipo": m.tipo,
                    "mesmo_processo": m.mesmo_processo,
                    "jaccard": m.jaccard,
                    "contencao": m.contencao,
                    "detalhe": m.detalhe,
                }
                for m in marcas
            ],
            "resumo_reuso": reuse.resumir(marcas),
        },
    )
    escrever_json(
        caminhos.catalogo / "processos_reprovados.json",
        {"processos": estado.reprovados(), "documentos": []},
    )

    resumo = estatisticas(processos, documentos_publicos)
    tarefas_stats = _estatisticas_tarefas(estado, fonte=fonte)
    if cobertura_incompleta:
        tarefas_stats["cobertura_incompleta"] = True
        tarefas_stats["cobertura_paginas_incompleta"] = True
    resumo.update(
        {
            "estrategia": "pncp_contratos_para_cadeia_completa",
            "alvo_processos": alvo,
            "fonte_preferencial": fonte,
            "policy_version": estado.policy_version,
            "requisicoes_hoje_utc": estado.requisicoes_hoje(),
            "limite_requisicoes_dia_utc": estado.max_requisicoes_dia,
            "margem_requisicoes": estado.margem_requisicoes,
            "editais_baixados": resumo.get("processos_com_edital", 0),
            "contratos_consultados": resumo.get("processos_com_contrato", 0),
            "marcas_de_reuso": reuse.resumir(marcas),
            **tarefas_stats,
        }
    )
    escrever_json(caminhos.catalogo / "estatisticas.json", resumo)
    log(json.dumps(resumo, ensure_ascii=False, indent=2))
    return resumo


# ------------------------------------------------------------------- coletor


# ---------------------------------------------------------- coleta vigente


def _numero_compra_do_contrato(registro: Mapping[str, Any]) -> str:
    valor = _campo(
        registro,
        "numeroControlePNCPCompra",
        "numeroControlePncpCompra",
        "numero_controle_pncp_compra",
    )
    return str(valor or "").strip()


def _identidade_contrato_feed(registro: Mapping[str, Any]) -> str:
    """Devolve uma identidade estável para deduplicar um contrato do feed."""
    valor = _campo(
        registro,
        "numeroControlePNCP",
        "numeroControlePncp",
        "numero_controle_pncp",
        "numeroContratoPncp",
    )
    if valor:
        return str(valor).strip()
    # Um registro sem id será rejeitado pelo normalizador, mas uma
    # representação estável evita repetir a mesma rejeição quando o feed
    # trouxer a linha duplicada.
    return json.dumps(dict(registro), ensure_ascii=False, sort_keys=True)


def _contrato_inicial(registro: Mapping[str, Any]) -> bool:
    tipo = registro.get("tipoContrato")
    if isinstance(tipo, Mapping):
        tipo_id = _campo(tipo, "id", "codigo")
        tipo_nome = _campo(tipo, "nome", "descricao")
    else:
        tipo_id = _campo(registro, "tipoContratoId", "tipo_contrato_id")
        tipo_nome = tipo or _campo(registro, "tipoContratoNome", "tipo_contrato_nome")
    if _int(tipo_id) == 1:
        return True
    return normalizar(str(tipo_nome or "")) in {
        "contrato",
        "contrato termo inicial",
        "contrato administrativo",
        "termo de contrato",
        "instrumento contratual",
    }


def _prioridade_contrato_feed(registro: Mapping[str, Any]) -> tuple[int, str, int]:
    """Ordena um grupo de contratos para escolher o instrumento inicial."""
    inicial = 0 if _contrato_inicial(registro) else 1
    data = str(
        _campo(registro, "dataAssinatura", "dataAtualizacaoGlobal", "data_assinatura")
        or ""
    )
    seq = _int(_campo(registro, "sequencialContrato", "sequencial_contrato")) or -1
    return inicial, data, -seq


def _agrupar_contratos_feed(
    registros: Iterable[dict[str, Any]],
) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    """Ordena contratos iniciais por contratação, preservando alternativas.

    Uma contratação pode ter mais de um instrumento inicial (por exemplo, um
    fornecedor por lote). O primeiro continua sendo tentado primeiro, mas os
    demais ficam disponíveis caso seu instrumento esteja ausente ou
    inutilizável. Registros que não são contratos iniciais permanecem como um
    único candidato para que o chamador possa contabilizá-los sem consultar
    anexos indevidos.
    """
    grupos: dict[str, list[dict[str, Any]]] = {}
    invalidos = 0
    for registro in registros:
        if not isinstance(registro, dict):
            invalidos += 1
            continue
        numero = _numero_compra_do_contrato(registro)
        if not numero:
            invalidos += 1
            continue
        grupos.setdefault(numero, []).append(registro)
    escolhidos: list[tuple[str, dict[str, Any]]] = []
    for numero, grupo in grupos.items():
        ordenados = sorted(grupo, key=_prioridade_contrato_feed)
        iniciais = [contrato for contrato in ordenados if _contrato_inicial(contrato)]
        escolhidos.extend(
            (numero, contrato) for contrato in (iniciais or ordenados[:1])
        )
    return escolhidos, invalidos


def coletar(
    raiz: Path,
    *,
    data_inicial: str = "20240101",
    data_final: str | None = None,
    processos: int = 20,
    # Mantido como parâmetro de compatibilidade; a coleta não oferece mais
    # estratégias alternativas. Todos os valores aceitos apontam para o feed
    # de contratos.
    fonte: str = FONTE_CONTRATOS,
    termos: Sequence[str] = DEFAULT_TERMOS,
    esferas: set[str] | frozenset[str] | None = ESFERAS_PERMITIDAS,
    max_por_orgao: int = 5,
    max_paginas_busca: int = 0,
    janela_dias: int = 31,
    max_paginas_feed: int = 100,
    max_requisicoes_dia: int = 900,
    intervalo: float = 0.75,
    tentativas: int = 5,
    timeout_confirmacao: float = 20.0,
    tentativas_confirmacao: int = 1,
    policy_version: str | int = POLICY_VERSION,
    ocr: bool = False,
    idioma_ocr: str = "por",
    opcoes_ocr: Mapping[str, Any] | None = None,
    max_tentativas_documentais_por_orgao: int = 3,
    max_tentativas_documentais: int | None = None,
    max_tentativas_por_orgao: int | None = None,
    margem_requisicoes: int = MARGEM_REQUISICOES_PADRAO,
    cache_ttl_segundos: float | timedelta | None = CACHE_TTL_SEGUNDOS,
    cache_ttl_vazio_segundos: float | timedelta | None = CACHE_TTL_VAZIO_SEGUNDOS,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Coleta processos somente pela cadeia ``contrato → compra → anexos``.

    A lista de contratos é a única fonte de descoberta. Depois de normalizar o
    vínculo, o detalhe da compra e o filtro de perfil são aplicados antes das
    duas consultas de anexos e de qualquer download. Um aceite novo contém
    exatamente quatro documentos utilizáveis; aceites históricos de ETP/TR são
    preservados no catálogo, mas não contam para ``processos`` nesta execução.
    """
    if processos < 1:
        raise ValueError("processos deve ser positivo")
    if max_por_orgao < 0:
        raise ValueError("max_por_orgao não pode ser negativo")
    if max_paginas_feed < 0:
        raise ValueError("max_paginas_feed não pode ser negativo")
    if janela_dias < 1:
        raise ValueError("janela_dias deve ser positivo")
    if max_tentativas_documentais is not None:
        max_tentativas_documentais_por_orgao = max_tentativas_documentais
    if max_tentativas_por_orgao is not None:
        max_tentativas_documentais_por_orgao = max_tentativas_por_orgao
    if max_tentativas_documentais_por_orgao < 0:
        raise ValueError("max_tentativas_documentais_por_orgao não pode ser negativo")
    if margem_requisicoes < 0:
        raise ValueError("margem_requisicoes não pode ser negativo")
    if intervalo < 0:
        raise ValueError("intervalo não pode ser negativo")
    if tentativas < 1 or tentativas_confirmacao < 1:
        raise ValueError("tentativas deve ser positiva")
    if timeout_confirmacao <= 0:
        raise ValueError("timeout_confirmacao deve ser positivo")
    if not str(idioma_ocr).strip():
        raise ValueError("idioma_ocr não pode ser vazio")
    # ``fonte`` e os parâmetros de busca/texto existem para compatibilidade de
    # CLI; aceitar seus nomes legados não reativa os coletores removidos.
    if fonte not in {
        FONTE_CONTRATOS,
        "auto",
        "pncp-busca",
        "compras",
        "pncp-feed",
        "contratos",
    }:
        raise ValueError(f"fonte inválida: {fonte}")
    # Os nomes legados são somente aliases de entrada; o estado, o catálogo e
    # as métricas devem sempre usar o namespace único da coleta vigente.
    fonte = FONTE_CONTRATOS
    esferas = _normalizar_esferas(esferas)
    policy_version = str(policy_version).strip() or POLICY_VERSION
    inicio = _data(data_inicial)
    data_final = data_final or (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    fim = _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    if fim >= date.today():
        raise ValueError("data_final deve ser uma data encerrada, anterior a hoje")

    caminhos = Caminhos(Path(raiz))
    caminhos.raiz.mkdir(parents=True, exist_ok=True)
    with EstadoColeta(
        caminhos.estado,
        max_requisicoes_dia,
        policy_version=policy_version,
        margem_requisicoes=margem_requisicoes,
        cache_ttl_segundos=cache_ttl_segundos,
        cache_ttl_vazio_segundos=cache_ttl_vazio_segundos,
    ) as estado:
        migrados_legados = _migrar_aceitos_legados(
            estado,
            caminhos.raiz,
            ocr=ocr,
            idioma_ocr=idioma_ocr,
            opcoes_ocr=opcoes_ocr,
            log=log,
        )
        throttle = _IntervaloGlobal(intervalo)
        with Pncp(
            timeout=60,
            tentativas=tentativas,
            intervalo=intervalo,
            reservar=estado.reservar_requisicao,
            throttle=throttle,
        ) as pncp:
            aceitos_completos = _aceitos_completos(estado.aceitos(), esferas)
            contagens = _contagens_orgaos(aceitos_completos)
            tentativas_documentais = _contagens_tentativas_documentais(estado)
            vistos_nesta_execucao: set[tuple[str, str]] = set()
            total_inspecoes = 0
            total_cadeias_identificadas = 0
            total_contratos_consultados = 0
            registros_invalidos = 0
            parou_por_limite = False
            cobertura_incompleta_execucao = False

            def aceitos_atuais() -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
                return _aceitos_completos(estado.aceitos(), esferas)

            def alvo_atingido() -> bool:
                return len(aceitos_atuais()) >= processos

            def pode_reservar() -> bool:
                metodo = getattr(estado, "pode_reservar_requisicao", None)
                return True if not callable(metodo) else bool(metodo(1))

            def retry_orcamento(tarefa: Mapping[str, Any]) -> None:
                try:
                    estado.marcar_tarefa_retry(
                        dict(tarefa),
                        erro="orçamento atingiu a margem reservada; página pendente",
                        proxima_tentativa_em=None,
                        atraso_segundos=0,
                    )
                except (TypeError, ValueError):
                    pass

            def executar_tarefa(
                tarefa: dict[str, Any],
            ) -> tuple[_ResultadoPagina | None, dict[str, Any] | None]:
                """Reivindica/consulta uma página e devolve sua lease."""
                nonlocal parou_por_limite
                concluida = tarefa.get("status") == CONCLUIDO
                lease: dict[str, Any] | None = None
                atual = tarefa
                if not concluida:
                    if not pode_reservar():
                        parou_por_limite = True
                        return None, None
                    atual = estado.proxima_tarefa_paginacao(
                        identificadores={int(tarefa["id"])}
                    ) or {}
                    if not atual:
                        return None, None
                    lease = dict(atual)
                try:
                    payload = _buscar_pagina_tarefa(estado, atual, pncp, None)
                    registros, total = _desempacotar_pagina(payload)
                except LimiteRequisicoes:
                    parou_por_limite = True
                    if lease:
                        retry_orcamento(lease)
                    return None, None
                except Exception as erro:
                    if lease:
                        estado.marcar_tarefa_retry(
                            lease,
                            erro=str(erro) or type(erro).__name__,
                            proxima_tentativa_em=None,
                            atraso_segundos=60,
                        )
                    log(
                        f"página RETRY {atual.get('fonte')}={atual.get('pagina')}: {erro}"
                    )
                    return None, None
                return _ResultadoPagina(dict(atual), registros, total), lease

            def finalizar_lease(
                lease: Mapping[str, Any] | None, *, pendente: bool = False
            ) -> None:
                if not lease:
                    return
                if pendente:
                    retry_orcamento(lease)
                else:
                    estado.concluir_tarefa_paginacao(dict(lease))

            def processar_contrato(
                numero_compra: str, bruto_contrato: dict[str, Any]
            ) -> bool:
                nonlocal total_inspecoes, total_cadeias_identificadas
                if not numero_compra:
                    return False
                identidade_contrato = _identidade_contrato_feed(bruto_contrato)
                identidade = (numero_compra, identidade_contrato)
                if identidade in vistos_nesta_execucao:
                    return False
                vistos_nesta_execucao.add(identidade)
                if numero_compra in {
                    c["numero_controle_pncp"] for c, _ in aceitos_atuais()
                }:
                    return False
                status = estado.status_inspecao(numero_compra)
                if status in {"FORA_DO_ESCOPO", "LIMITE_ORGAO"}:
                    return False
                if status == "DOWNLOAD_REPROVADO":
                    # Permita testar outro contrato inicial da mesma compra,
                    # mas não repita no mesmo run a tentativa documental já
                    # persistida para este contrato.
                    inspecao_anterior = estado.inspecao(numero_compra) or {}
                    candidato_anterior = inspecao_anterior.get("candidato")
                    contrato_anterior = (
                        candidato_anterior.get("contrato")
                        if isinstance(candidato_anterior, Mapping)
                        else None
                    )
                    if not isinstance(contrato_anterior, Mapping):
                        contratos_anteriores = (
                            candidato_anterior.get("contratos")
                            if isinstance(candidato_anterior, Mapping)
                            else None
                        )
                        contrato_anterior = (
                            contratos_anteriores[0]
                            if isinstance(contratos_anteriores, Sequence)
                            and not isinstance(contratos_anteriores, (str, bytes))
                            and contratos_anteriores
                            and isinstance(contratos_anteriores[0], Mapping)
                            else None
                        )
                    if isinstance(contrato_anterior, Mapping):
                        identidade_anterior = _identidade_contrato_feed(
                            contrato_anterior
                        )
                        if identidade_anterior == identidade_contrato:
                            return False
                    else:
                        return False
                total_inspecoes += 1
                try:
                    compra_bruta = _detalhe_com_cache(estado, pncp, numero_compra)
                    compra = normalizar_compra(compra_bruta, "pncp_contratos")
                except LimiteRequisicoes:
                    raise
                except (PncpError, RuntimeError, ValueError) as erro:
                    mensagem = f"contratação vinculada indisponível: {erro}"
                    estado.salvar_inspecao(
                        numero_compra,
                        {"numero_controle_pncp": numero_compra},
                        status="ERRO_API",
                        motivo=mensagem,
                    )
                    log(f"  confirmação pendente {numero_compra}: {mensagem}")
                    return False
                if compra.get("numero_controle_pncp") != numero_compra:
                    motivo = "contratação vinculada diverge do numeroControlePncpCompra"
                    estado.salvar_inspecao(
                        numero_compra, compra, status="FORA_DO_ESCOPO", motivo=motivo
                    )
                    return False
                ok, motivo = _aceitavel(compra, esferas, preliminar=False)
                if not ok:
                    estado.salvar_inspecao(
                        numero_compra, compra, status="FORA_DO_ESCOPO", motivo=motivo
                    )
                    return False
                orgao = _cnpj_da_compra(compra)
                if contagens[orgao] >= max_por_orgao:
                    estado.salvar_inspecao(
                        numero_compra,
                        compra,
                        status="LIMITE_ORGAO",
                        motivo=f"limite de {max_por_orgao} processos por órgão",
                    )
                    return False
                if tentativas_documentais[orgao] >= max_tentativas_documentais_por_orgao:
                    estado.salvar_inspecao(
                        numero_compra,
                        compra,
                        status="LIMITE_ORGAO",
                        motivo=(
                            "teto persistente de "
                            f"{max_tentativas_documentais_por_orgao} tentativas documentais por órgão"
                        ),
                    )
                    return False

                try:
                    contrato = _normalizar_contrato(bruto_contrato, compra)
                    # O vínculo e o número do contrato são validados antes de
                    # tocar em qualquer lista de anexos. Assim um registro do
                    # feed que aponta para outra compra não consome a consulta
                    # documental dessa contratação.
                    arquivos_compra = _arquivos_com_cache(estado, pncp, compra)
                    arquivos_contrato = _arquivos_contrato_com_cache(
                        estado, pncp, contrato
                    )
                except LimiteRequisicoes:
                    raise
                except (PncpError, RuntimeError, ValueError) as erro:
                    estado.salvar_inspecao(
                        numero_compra,
                        compra,
                        status="ERRO_API",
                        motivo=f"anexos da cadeia indisponíveis: {erro}",
                    )
                    log(f"  API pendente {numero_compra}: {erro}")
                    return False
                candidato, motivo, todos = formar_candidato_cadeia(
                    compra, arquivos_compra, contrato, arquivos_contrato
                )
                if candidato is None:
                    estado.salvar_inspecao(
                        numero_compra,
                        compra,
                        status="SEM_CADEIA_COMPLETA",
                        motivo=motivo,
                        arquivos=todos,
                    )
                    log(f"  x {numero_compra}: {motivo}")
                    return False

                total_cadeias_identificadas += 1
                estado.salvar_inspecao(
                    numero_compra,
                    compra,
                    status="CADEIA_IDENTIFICADA",
                    arquivos=todos,
                    candidato=candidato,
                )
                resultado = baixar_cadeia_completa(
                    pncp,
                    candidato,
                    caminhos,
                    estado=estado,
                    ocr=ocr,
                    idioma_ocr=idioma_ocr,
                    opcoes_ocr=opcoes_ocr,
                )
                if not resultado.aprovado:
                    motivo_download = resultado.motivo or "download da cadeia reprovado"
                    api = "falha de API" in motivo_download
                    estado.salvar_inspecao(
                        numero_compra,
                        compra,
                        status="ERRO_API" if api else "DOWNLOAD_REPROVADO",
                        motivo=motivo_download,
                        arquivos=todos,
                        candidato=candidato,
                    )
                    if not api:
                        tentativas_documentais[orgao] += 1
                    log(f"  x {numero_compra}: {motivo_download}")
                    return False
                if not _documentos_formam_cadeia_completa(resultado.documentos):
                    motivo_download = "download concluído sem os quatro documentos utilizáveis"
                    estado.salvar_inspecao(
                        numero_compra,
                        compra,
                        status="DOWNLOAD_REPROVADO",
                        motivo=motivo_download,
                        arquivos=todos,
                        candidato=candidato,
                    )
                    tentativas_documentais[orgao] += 1
                    return False
                estado.salvar_aceito(candidato, resultado.documentos)
                estado.salvar_inspecao(
                    numero_compra,
                    compra,
                    status="ACEITO",
                    arquivos=todos,
                    candidato=candidato,
                )
                contagens[orgao] += 1
                log(f"  ok {numero_compra} ({len(aceitos_atuais())}/{processos})")
                return True

            def inspecionar_paginas(
                resultados: Sequence[_ResultadoPagina],
                leases: Sequence[Mapping[str, Any]],
            ) -> None:
                nonlocal registros_invalidos, parou_por_limite, total_contratos_consultados
                registros: list[dict[str, Any]] = []
                for resultado in sorted(
                    resultados, key=lambda item: int(item.tarefa.get("pagina") or 0)
                ):
                    registros.extend(resultado.registros)
                grupos, invalidos = _agrupar_contratos_feed(registros)
                registros_invalidos += invalidos
                total_contratos_consultados += len(registros)
                try:
                    for numero, contrato in grupos:
                        if alvo_atingido() or parou_por_limite:
                            break
                        if not _contrato_inicial(contrato):
                            # Sem termo inicial não há instrumento exigível;
                            # outro contrato da mesma compra pode aparecer em
                            # uma página futura, por isso não marcamos como
                            # inspeção definitiva aqui.
                            continue
                        processar_contrato(numero, contrato)
                except LimiteRequisicoes:
                    parou_por_limite = True
                for lease in leases:
                    finalizar_lease(lease, pendente=parou_por_limite)

            def rodar_feed(
                base: Mapping[str, Any], max_paginas: int
            ) -> None:
                nonlocal cobertura_incompleta_execucao, parou_por_limite
                pagina = 1
                while (
                    pagina <= max_paginas
                    and not alvo_atingido()
                    and not parou_por_limite
                ):
                    tarefa = _criar_tarefa_pagina(
                        estado,
                        FONTE_CONTRATOS,
                        base,
                        pagina,
                        500,
                    )
                    resultado, lease = executar_tarefa(tarefa)
                    if parou_por_limite:
                        finalizar_lease(lease, pendente=True)
                        break
                    if resultado is None:
                        # A página vira RETRY; avance para preservar cobertura
                        # das páginas posteriores nesta execução.
                        pagina += 1
                        continue
                    inspecionar_paginas([resultado], [lease] if lease else [])
                    if parou_por_limite or alvo_atingido():
                        break
                    limite = resultado.total
                    if limite <= pagina:
                        break
                    if pagina >= max_paginas:
                        cobertura_incompleta_execucao = True
                        break
                    pagina += 1

            try:
                if max_paginas_feed == 0 and not alvo_atingido():
                    cobertura_incompleta_execucao = True
                else:
                    for inicio_janela, fim_janela in janelas_calendario(
                        data_inicial, data_final, janela_dias
                    ):
                        if alvo_atingido() or parou_por_limite:
                            break
                        rodar_feed(
                            {"inicio": inicio_janela, "fim": fim_janela},
                            max_paginas_feed,
                        )
            finally:
                resumo = _catalogar(
                    caminhos,
                    estado,
                    alvo=processos,
                    fonte=FONTE_CONTRATOS,
                    log=log,
                    cobertura_incompleta=cobertura_incompleta_execucao,
                )
                resumo.update(
                    {
                        "contratos_consultados_nesta_execucao": total_contratos_consultados,
                        "cadeias_identificadas_nesta_execucao": total_cadeias_identificadas,
                        "compras_inspecionadas_nesta_execucao": total_inspecoes,
                        "registros_invalidos_nesta_execucao": registros_invalidos,
                        "registros_invalidos_ano_nesta_execucao": registros_invalidos,
                        "aceitos_migrados_sem_download": migrados_legados,
                        "tentativas_documentais_por_orgao": dict(tentativas_documentais),
                        "max_tentativas_documentais_por_orgao": max_tentativas_documentais_por_orgao,
                        "parou_por_limite_requisicoes": parou_por_limite,
                        "estrategia": "pncp_contratos_para_cadeia_completa",
                    }
                )
                escrever_json(caminhos.catalogo / "estatisticas.json", resumo)
    return resumo


# ----------------------------------------------------------------------- CLI


def principal(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Coleta cadeias completas pelo feed de contratos do PNCP."
    )
    parser.add_argument("--raiz", type=Path, default=Path("corpus"))
    parser.add_argument("--data-inicial", default="20240101")
    parser.add_argument(
        "--data-final",
        default=(date.today() - timedelta(days=1)).strftime("%Y%m%d"),
    )
    parser.add_argument(
        "--processos",
        type=int,
        default=20,
        help="alvo; use 15 para o mínimo do primeiro lote",
    )
    parser.add_argument(
        "--fonte",
        choices=(
            FONTE_CONTRATOS,
            "contratos",
            "auto",
            "pncp-busca",
            "compras",
            "pncp-feed",
        ),
        default=FONTE_CONTRATOS,
        help="compatibilidade; a coleta sempre usa o feed de contratos",
    )
    parser.add_argument("--termo", action="append", dest="termos", default=None,
                        help="compatibilidade; não altera a descoberta por contratos")
    parser.add_argument(
        "--esferas",
        default=",".join(sorted(ESFERAS_PERMITIDAS)),
        help="esferas admitidas, separadas por vírgula (F,E,D,M)",
    )
    parser.add_argument("--max-por-orgao", type=int, default=5)
    parser.add_argument(
        "--max-tentativas-documentais",
        "--max-tentativas-documentais-por-orgao",
        "--max-tentativas-por-orgao",
        dest="max_tentativas_documentais",
        type=int,
        default=3,
    )
    parser.add_argument("--max-paginas-busca", type=int, default=0,
                        help="compatibilidade; páginas da busca textual não são consultadas")
    parser.add_argument("--janela-dias", type=int, default=31)
    parser.add_argument("--max-paginas-feed", type=int, default=100)
    parser.add_argument("--max-requisicoes-dia", type=int, default=900)
    parser.add_argument(
        "--margem-requisicoes",
        type=int,
        default=MARGEM_REQUISICOES_PADRAO,
        help="chamadas preservadas atomicamente para a próxima retomada",
    )
    parser.add_argument("--policy-version", default=POLICY_VERSION)
    parser.add_argument("--ocr", action="store_true", help="usar OCR como fallback de PDF")
    parser.add_argument("--idioma-ocr", "--ocr-idioma", dest="idioma_ocr", default="por")
    parser.add_argument(
        "--intervalo",
        type=float,
        default=0.75,
        help="intervalo mínimo global entre chamadas",
    )
    parser.add_argument("--tentativas", type=int, default=5)
    parser.add_argument(
        "--timeout-confirmacao",
        type=float,
        default=20.0,
        help="compatibilidade; confirmações ocorrem no detalhe vinculado",
    )
    parser.add_argument(
        "--tentativas-confirmacao",
        type=int,
        default=1,
        help="compatibilidade; usado como validação de entrada",
    )
    argumentos = parser.parse_args(argv)

    try:
        fim = datetime.strptime(argumentos.data_final, "%Y%m%d").date()
    except ValueError:
        parser.error("--data-final deve usar YYYYMMDD")
    if fim >= date.today():
        parser.error("--data-final deve ser uma data já encerrada, anterior a hoje")
    esferas = {
        e.strip().upper() for e in str(argumentos.esferas).split(",") if e.strip()
    }
    termos = tuple(argumentos.termos or DEFAULT_TERMOS)
    try:
        resumo = coletar(
            argumentos.raiz,
            data_inicial=argumentos.data_inicial,
            data_final=argumentos.data_final,
            processos=argumentos.processos,
            fonte=argumentos.fonte,
            termos=termos,
            esferas=esferas,
            max_por_orgao=argumentos.max_por_orgao,
            max_paginas_busca=argumentos.max_paginas_busca,
            janela_dias=argumentos.janela_dias,
            max_paginas_feed=argumentos.max_paginas_feed,
            max_requisicoes_dia=argumentos.max_requisicoes_dia,
            intervalo=argumentos.intervalo,
            tentativas=argumentos.tentativas,
            timeout_confirmacao=argumentos.timeout_confirmacao,
            tentativas_confirmacao=argumentos.tentativas_confirmacao,
            policy_version=argumentos.policy_version,
            ocr=argumentos.ocr,
            idioma_ocr=argumentos.idioma_ocr,
            max_tentativas_documentais_por_orgao=argumentos.max_tentativas_documentais,
            margem_requisicoes=argumentos.margem_requisicoes,
        )
    except (ValueError, LimiteRequisicoes) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 2
    passou = resumo["processos"] >= argumentos.processos
    return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(principal())
