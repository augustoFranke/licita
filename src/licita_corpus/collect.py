"""Coleta retomável e restrita de pares ETP→TR.

A descoberta pode usar a busca textual do PNCP como acelerador, mas uma compra
só chega à lista de arquivos depois de ser confirmada por uma fonte oficial.
O feed PNCP e o feed do Compras.gov.br já são fontes autoritativas. O coletor
nunca consulta contratos e nunca baixa editais.

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
    documento_id,
    escrever_json,
    escrever_jsonl,
    estatisticas,
    montar_processo,
    montar_relacoes,
    ocr_historico_utilizavel,
)
from .classify import (
    ESFERAS_SUPORTADAS,
    ETP,
    PERFIL_SUPPORTED,
    TR,
    categoria_objeto,
    classificar_perfil_inicial,
    papel_documento,
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


# Decisões ficam gravadas por (processo, policy_version). A política 4 rejeitou
# ~20 mil processos por "esfera não é municipal"; reaproveitá-las sob o escopo
# de todas as esferas faria o coletor pular justamente o que passou a ser
# elegível. Por isso a ampliação da esfera exige uma política nova — as
# inspeções anteriores coexistem no estado, mas não são reaproveitadas.
POLICY_VERSION = "5-todas-esferas-historical-ocr"
# Alterar este identificador sempre que a implementação, defaults ou
# interpretação das opções do OCR mudar de forma capaz de alterar o texto.
OCR_PIPELINE_VERSION = "verify-pymupdf-tesseract-v1"
#: Esferas do perfil — fonte única em ``classify.ESFERAS_SUPORTADAS``.
ESFERAS_PERMITIDAS = ESFERAS_SUPORTADAS
DEFAULT_TERMOS = ("Estudo Tecnico Preliminar", "ETP")
ANOS_PRIORITARIOS = (2024, 2023, 2022, 2025)
PAGINAS_POR_LOTE = 5
MARGEM_REQUISICOES_PADRAO = 15


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
    """Converte os formatos das APIs em metadado comum e valida o ano.

    O ano no número ``.../AAAA`` é a identidade da contratação. Se a API
    também enviar ano da compra ou data de publicação, ambos precisam ser
    compatíveis com essa identidade; um registro inconsistente não é aceito
    silenciosamente.
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
        if publicada.year != ano_por_numero:
            raise ValueError(
                f"ano da publicação ({publicada.year}) diverge do número PNCP "
                f"({ano_por_numero})"
            )

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
        return False, "fora do perfil municipal de Pregão Eletrônico para bens comuns"
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
    """Forma um candidato preservando todas as revisões ETP/TR ativas.

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
        return [
            dict(item)
            for item in valor
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
    por_papel: dict[str, list[dict[str, Any]]] = {ETP: [], TR: []}
    for documento in documentos:
        papel = documento.get("papel")
        if papel not in por_papel:
            # Edital/contrato de um aceite legado é descartado na migração;
            # seus hashes não precisam ser rebaixados nem entram no corpus V0.
            continue
        por_papel[papel].append(documento)
    if any(len(por_papel[papel]) != 1 for papel in (ETP, TR)):
        return None

    novos: list[dict[str, Any]] = []
    for papel in (ETP, TR):
        original = dict(por_papel[papel][0])
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
        novos.append(registro)
    # O aceite migrado mantém o candidato original; só a verificação física
    # dos dois documentos é atualizada. Isso preserva URLs/revisões legadas
    # mesmo quando o registro antigo não tinha o formato mais novo.
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
    """Migra aceites de outras políticas quando os arquivos ainda passam."""
    ativos = estado.numeros_aceitos()
    migrados = 0
    for candidato, documentos in estado.aceitos(None):
        numero = str(candidato.get("numero_controle_pncp") or "")
        if not numero or numero in ativos:
            continue
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
        "FORA_DO_ESCOPO",
        "LIMITE_ORGAO",
        "DOWNLOAD_REPROVADO",
    }


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


def _estatisticas_tarefas(estado: EstadoColeta) -> dict[str, Any]:
    tarefas = estado.listar_tarefas_paginacao()
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
    """Preserva controles negativos municipais entre recatalogações.

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
    controles, documentos_controle, relacoes_controle = _controles_catalogados(
        caminhos
    )
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
        # O lote é de cadeia: ETP e TR são obrigatórios e os elos opcionais
        # publicados pelo ente entram junto. Filtrar só o par aqui apagaria do
        # catálogo edital e contrato já baixados e verificados.
        documentos_par = [
            dict(documento)
            for documento in documentos
            if documento.get("papel") in PAPEIS_DO_LOTE
        ]
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
        processo = montar_processo(
            candidato["compra"],
            {"fonte": fonte},
            documentos_locais,
            (),
        )
        processo["policy_version"] = estado.policy_version
        processo["collection_policy_version"] = estado.policy_version
        processos.append(processo)
        relacoes.extend(montar_relacoes(pid, processo["cadeia"]))
        documentos_com_texto.extend(documentos_locais)
        escrever_json(caminhos.documentos / pid / "metadata.json", processo)

    ids_ativos = {str(processo.get("processo_id") or "") for processo in processos}
    processos.extend(
        processo
        for processo in controles
        if str(processo.get("processo_id") or "") not in ids_ativos
    )
    documentos_com_texto.extend(
        documento
        for documento in documentos_controle
        if str(documento.get("processo_id") or "") not in ids_ativos
    )
    relacoes.extend(
        relacao
        for relacao in relacoes_controle
        if str(relacao.get("processo_id") or "") not in ids_ativos
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
    tarefas_stats = _estatisticas_tarefas(estado)
    if cobertura_incompleta:
        tarefas_stats["cobertura_incompleta"] = True
        tarefas_stats["cobertura_paginas_incompleta"] = True
    resumo.update(
        {
            "estrategia": "compras_gov_para_descoberta_pncp_para_documentos",
            "alvo_processos": alvo,
            "fonte_preferencial": fonte,
            "policy_version": estado.policy_version,
            "requisicoes_hoje_utc": estado.requisicoes_hoje(),
            "limite_requisicoes_dia_utc": estado.max_requisicoes_dia,
            "margem_requisicoes": estado.margem_requisicoes,
            "editais_baixados": 0,
            "contratos_consultados": 0,
            "marcas_de_reuso": reuse.resumir(marcas),
            **tarefas_stats,
        }
    )
    escrever_json(caminhos.catalogo / "estatisticas.json", resumo)
    log(json.dumps(resumo, ensure_ascii=False, indent=2))
    return resumo


# ------------------------------------------------------------------- coletor


def coletar(
    raiz: Path,
    *,
    data_inicial: str = "20240101",
    data_final: str | None = None,
    processos: int = 20,
    fonte: str = "auto",
    termos: Sequence[str] = DEFAULT_TERMOS,
    esferas: set[str] | frozenset[str] | None = ESFERAS_PERMITIDAS,
    max_por_orgao: int = 5,
    max_paginas_busca: int = 40,
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
    """Executa ou retoma a coleta até o alvo, sem buscar edital/contrato."""
    if processos < 1:
        raise ValueError("processos deve ser positivo")
    if max_por_orgao < 0:
        raise ValueError("max_por_orgao não pode ser negativo")
    if max_paginas_busca < 0 or max_paginas_feed < 0:
        raise ValueError("limite de páginas não pode ser negativo")
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
    if timeout_confirmacao <= 0:
        raise ValueError("timeout_confirmacao deve ser positivo")
    if tentativas_confirmacao < 1:
        raise ValueError("tentativas_confirmacao deve ser positiva")
    if not str(idioma_ocr).strip():
        raise ValueError("idioma_ocr não pode ser vazio")
    esferas = _normalizar_esferas(esferas)
    policy_version = str(policy_version).strip() or POLICY_VERSION

    inicio = _data(data_inicial)
    data_final = data_final or (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    fim = _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    if fim >= date.today():
        raise ValueError("data_final deve ser uma data encerrada, anterior a hoje")
    if fonte not in {"auto", "pncp-busca", "compras", "pncp-feed"}:
        raise ValueError(f"fonte inválida: {fonte}")

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
        ) as pncp, ComprasGov(
            timeout=45,
            tentativas=tentativas,
            intervalo=intervalo,
            reservar=estado.reservar_requisicao,
            throttle=throttle,
        ) as compras, Pncp(
            timeout=timeout_confirmacao,
            tentativas=tentativas_confirmacao,
            intervalo=intervalo,
            reservar=estado.reservar_requisicao,
            throttle=throttle,
        ) as pncp_confirmacao, ComprasGov(
            timeout=timeout_confirmacao,
            tentativas=tentativas_confirmacao,
            intervalo=intervalo,
            reservar=estado.reservar_requisicao,
            throttle=throttle,
        ) as compras_confirmacao:
            contagens = _contagens_orgaos(_aceitos_no_perfil(estado.aceitos()))
            tentativas_documentais = _contagens_tentativas_documentais(estado)
            vistos_nesta_execucao: set[str] = set()
            total_inspecoes = 0
            total_pares_publicados = 0
            registros_invalidos = 0
            parou_por_limite = False
            cobertura_incompleta_execucao = False

            def aceitos_atuais() -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
                return _aceitos_no_perfil(estado.aceitos())

            def alvo_atingido() -> bool:
                return len(aceitos_atuais()) >= processos

            def pode_reservar() -> bool:
                metodo = getattr(estado, "pode_reservar_requisicao", None)
                if not callable(metodo):
                    return True
                return bool(metodo(1))

            def retry_orcamento(tarefa: Mapping[str, Any]) -> None:
                try:
                    estado.marcar_tarefa_retry(
                        dict(tarefa),
                        erro="orçamento atingiu a margem reservada; página pendente",
                        proxima_tentativa_em=None,
                        atraso_segundos=0,
                    )
                except (TypeError, ValueError):
                    # A tarefa pode ser uma linha concluída de uma versão
                    # antiga; nesse caso não há lease mutável a liberar.
                    pass

            def executar_tarefas(
                tarefas: Sequence[dict[str, Any]],
            ) -> tuple[list[_ResultadoPagina], list[dict[str, Any]]]:
                """Reivindica páginas pela fila e marca erro como RETRY."""
                nonlocal parou_por_limite
                resultados: list[_ResultadoPagina] = []
                leases: list[dict[str, Any]] = []
                selecionadas = {
                    int(tarefa.get("id"))
                    for tarefa in tarefas
                    if tarefa.get("id") is not None
                    and tarefa.get("status") != CONCLUIDO
                }
                # Checkpoint concluído é reutilizado pelo cache; isso permite
                # reprocessar uma página sob nova policy sem nova chamada.
                for tarefa in tarefas:
                    if tarefa.get("status") != CONCLUIDO:
                        continue
                    try:
                        payload = _buscar_pagina_tarefa(estado, tarefa, pncp, compras)
                        registros, total = _desempacotar_pagina(payload)
                    except Exception as erro:
                        log(f"página concluída sem cache utilizável: {erro}")
                        continue
                    resultados.append(_ResultadoPagina(dict(tarefa), registros, total))

                vistos_tarefas_externas: set[int] = set()
                while selecionadas and not parou_por_limite:
                    # Uma resposta já cacheada pode ser processada mesmo se a
                    # margem não permitir uma nova chamada. As páginas novas
                    # permanecem PENDENTE.
                    tem_cache = False
                    for tarefa in tarefas:
                        identificador = tarefa.get("id")
                        if identificador is None or int(identificador) not in selecionadas:
                            continue
                        parametros = _parametros_tarefa(tarefa)
                        chave = estado.chave_resposta(str(tarefa.get("fonte") or ""), parametros)
                        if estado.resposta(chave) is not None:
                            tem_cache = True
                            break
                    if not tem_cache and not pode_reservar():
                        parou_por_limite = True
                        break

                    tarefa = estado.proxima_tarefa_paginacao(
                        identificadores=selecionadas
                    )
                    if tarefa is None:
                        break
                    identificador = tarefa.get("id")
                    id_normal = None if identificador is None else int(identificador)
                    if id_normal not in selecionadas and id_normal in vistos_tarefas_externas:
                        break
                    try:
                        payload = _buscar_pagina_tarefa(estado, tarefa, pncp, compras)
                        registros, total = _desempacotar_pagina(payload)
                    except LimiteRequisicoes:
                        parou_por_limite = True
                        retry_orcamento(tarefa)
                        if id_normal in selecionadas:
                            selecionadas.discard(id_normal)
                        break
                    except Exception as erro:
                        # Falha de uma página (inclusive um double de
                        # transporte que não use PncpError) não encerra o lote.
                        # O token da lease autoriza a transição atômica para
                        # RETRY.
                        mensagem = str(erro) or type(erro).__name__
                        estado.marcar_tarefa_retry(
                            tarefa,
                            erro=mensagem,
                            proxima_tentativa_em=None,
                            atraso_segundos=60,
                        )
                        log(
                            f"página RETRY {tarefa.get('fonte')}="
                            f"{tarefa.get('pagina')}: {mensagem}"
                        )
                        if id_normal in selecionadas:
                            selecionadas.discard(id_normal)
                        else:
                            vistos_tarefas_externas.add(id_normal or -1)
                        continue

                    if id_normal in selecionadas:
                        selecionadas.discard(id_normal)
                    else:
                        vistos_tarefas_externas.add(id_normal or -1)
                    if tarefa.get("status") != CONCLUIDO:
                        leases.append(dict(tarefa))
                    resultados.append(_ResultadoPagina(dict(tarefa), registros, total))

                # Se a fila não entregou uma tarefa nova, qualquer selecionada
                # continua pendente no estado. Nenhuma página é falsamente
                # concluída por falta de orçamento.
                return resultados, leases

            def finalizar_leases(
                leases: Sequence[dict[str, Any]], *, pendentes: bool = False
            ) -> None:
                for tarefa in leases:
                    if pendentes:
                        retry_orcamento(tarefa)
                    else:
                        estado.concluir_tarefa_paginacao(tarefa)

            def processar_compra(
                compra: dict[str, Any], *, origem: str, detalhe: bool
            ) -> bool:
                nonlocal total_inspecoes, total_pares_publicados
                numero = compra["numero_controle_pncp"]
                if numero in estado.numeros_aceitos():
                    return False
                if not _data_no_periodo(
                    compra,
                    data_inicial[:4] + "-" + data_inicial[4:6] + "-" + data_inicial[6:],
                    data_final[:4] + "-" + data_final[4:6] + "-" + data_final[6:],
                ):
                    return False
                if _reaproveitar_inspecao(estado, numero):
                    return False
                ok, motivo = _aceitavel(compra, esferas, preliminar=not detalhe)
                if not ok:
                    estado.salvar_inspecao(
                        numero, compra, status="FORA_DO_ESCOPO", motivo=motivo
                    )
                    return False

                orgao = _cnpj_da_compra(compra)
                if contagens[orgao] >= max_por_orgao:
                    estado.salvar_inspecao(
                        numero,
                        compra,
                        status="LIMITE_ORGAO",
                        motivo=f"limite de {max_por_orgao} processos por órgão",
                    )
                    return False
                if tentativas_documentais[orgao] >= max_tentativas_documentais_por_orgao:
                    estado.salvar_inspecao(
                        numero,
                        compra,
                        status="LIMITE_ORGAO",
                        motivo=(
                            "teto persistente de "
                            f"{max_tentativas_documentais_por_orgao} tentativas "
                            "documentais por órgão"
                        ),
                    )
                    return False

                total_inspecoes += 1
                # Para busca textual, a confirmação vem inteira antes da lista
                # de arquivos: feed PNCP paginado → Compras → detalhe.
                if not detalhe:
                    try:
                        try:
                            # Compras.gov costuma responder mais rápido e já
                            # fornece os metadados necessários ao gate. PNCP
                            # permanece fonte dos documentos e fallback de
                            # confirmação, sem repetir o endpoint de detalhe.
                            compra = _confirmar_busca_no_compras(
                                estado, compras_confirmacao, compra
                            )
                        except LimiteRequisicoes:
                            raise
                        except (PncpError, RuntimeError) as erro_compras:
                            try:
                                compra = _confirmar_busca_no_pncp(
                                    estado, pncp_confirmacao, compra
                                )
                            except LimiteRequisicoes:
                                raise
                            except (PncpError, RuntimeError) as erro_pncp:
                                raise PncpError(
                                    "Compras.gov: "
                                    f"{erro_compras}; PNCP: {erro_pncp}"
                                ) from erro_pncp
                    except LimiteRequisicoes:
                        raise
                    except (PncpError, RuntimeError, ValueError) as erro:
                        mensagem = f"confirmação Compras.gov/PNCP: {erro}"
                        estado.salvar_inspecao(
                            numero,
                            compra,
                            status="ERRO_API",
                            motivo=mensagem,
                        )
                        log(f"  confirmação pendente {numero}: {mensagem}")
                        return False
                    ok, motivo = _aceitavel(compra, esferas, preliminar=False)
                    if not ok:
                        estado.salvar_inspecao(
                            numero,
                            compra,
                            status="FORA_DO_ESCOPO",
                            motivo=motivo,
                        )
                        return False

                if not _data_no_periodo(
                    compra,
                    data_inicial[:4] + "-" + data_inicial[4:6] + "-" + data_inicial[6:],
                    data_final[:4] + "-" + data_final[4:6] + "-" + data_final[6:],
                ):
                    estado.salvar_inspecao(
                        numero,
                        compra,
                        status="FORA_DO_ESCOPO",
                        motivo="data de publicação ausente ou fora do intervalo",
                    )
                    return False

                # Nenhuma chamada de arquivos ocorre antes do bloco de
                # confirmação acima.
                try:
                    arquivos = _arquivos_com_cache(estado, pncp, compra)
                except LimiteRequisicoes:
                    raise
                except Exception as erro:
                    estado.salvar_inspecao(
                        numero, compra, status="ERRO_API", motivo=str(erro)
                    )
                    log(f"  API pendente {numero}: {erro}")
                    return False
                candidato, motivo, _todos_arquivos = formar_candidato(compra, arquivos)
                if candidato is None:
                    estado.salvar_inspecao(
                        numero,
                        compra,
                        status="SEM_PAR_ETP_TR",
                        motivo=motivo,
                        arquivos=arquivos,
                    )
                    return False

                total_pares_publicados += 1
                estado.salvar_inspecao(
                    numero,
                    compra,
                    status="PAR_PUBLICADO",
                    arquivos=arquivos,
                    candidato=candidato,
                )
                resultado = baixar_par(
                    pncp,
                    candidato,
                    caminhos,
                    estado=estado,
                    ocr=ocr,
                    idioma_ocr=idioma_ocr,
                    opcoes_ocr=opcoes_ocr,
                )
                if not resultado.aprovado:
                    motivo_download = resultado.motivo or "download documental reprovado"
                    api = motivo_download.startswith("falha de API")
                    status = "ERRO_API" if api else "DOWNLOAD_REPROVADO"
                    estado.salvar_inspecao(
                        numero,
                        compra,
                        status=status,
                        motivo=motivo_download,
                        arquivos=arquivos,
                        candidato=candidato,
                    )
                    if not api:
                        tentativas_documentais[orgao] += 1
                    log(f"  x {numero}: {motivo_download}")
                    return False

                estado.salvar_aceito(candidato, resultado.documentos)
                estado.salvar_inspecao(
                    numero,
                    compra,
                    status="ACEITO",
                    arquivos=arquivos,
                    candidato=candidato,
                )
                contagens[orgao] += 1
                log(f"  ok {numero} ({len(aceitos_atuais())}/{processos})")
                return True

            def inspecionar_paginas(
                resultados: Sequence[_ResultadoPagina],
                leases: Sequence[dict[str, Any]],
            ) -> None:
                nonlocal parou_por_limite, registros_invalidos
                pares: list[tuple[dict[str, Any], str, bool]] = []
                for resultado in sorted(
                    resultados,
                    key=lambda item: int(item.tarefa.get("pagina") or 0),
                ):
                    fonte_tarefa = str(resultado.tarefa.get("fonte") or "")
                    origem = {
                        "pncp-busca": "pncp_busca",
                        "compras-gov": "compras_gov",
                        "pncp-feed": "pncp_feed",
                    }.get(fonte_tarefa, fonte_tarefa)
                    detalhe = fonte_tarefa in {"compras-gov", "pncp-feed"}
                    for bruto in resultado.registros:
                        try:
                            pares.append((normalizar_compra(bruto, origem), origem, detalhe))
                        except ValueError:
                            registros_invalidos += 1
                # Deduplica no lote antes de intercalar os órgãos; a ordem de
                # descoberta de cada órgão continua determinística.
                dedup: list[tuple[dict[str, Any], str, bool]] = []
                vistos_lote: set[str] = set()
                for par in pares:
                    numero = par[0]["numero_controle_pncp"]
                    if numero in vistos_lote or numero in vistos_nesta_execucao:
                        continue
                    vistos_lote.add(numero)
                    vistos_nesta_execucao.add(numero)
                    dedup.append(par)
                # O sort é estável: dentro de cada nível de completude,
                # preserva o round-robin por CNPJ. Registros que dispensam
                # confirmação ou já informam modalidade 6 avançam primeiro.
                ordenados = sorted(
                    _round_robin_pares(dedup), key=_prioridade_confirmacao
                )
                try:
                    for compra, origem, detalhe in ordenados:
                        if alvo_atingido():
                            break
                        processar_compra(compra, origem=origem, detalhe=detalhe)
                except LimiteRequisicoes:
                    parou_por_limite = True
                    finalizar_leases(leases, pendentes=True)
                    return
                finalizar_leases(leases, pendentes=False)

            def total_paginas_fonte(fonte_tarefa: str, total: int, tamanho: int) -> int:
                if fonte_tarefa == "pncp-busca":
                    return (total + tamanho - 1) // tamanho if total else 0
                return total

            def rodar_consulta(
                fonte_tarefa: str,
                base: Mapping[str, Any],
                tamanho: int,
                max_paginas: int,
                *,
                rotulo: str,
            ) -> None:
                nonlocal parou_por_limite, cobertura_incompleta_execucao
                inicio_pagina = 1
                if max_paginas == 0 and not alvo_atingido():
                    cobertura_incompleta_execucao = True
                    return
                while (
                    inicio_pagina <= max_paginas
                    and not alvo_atingido()
                    and not parou_por_limite
                ):
                    primeiro = _criar_tarefa_pagina(
                        estado,
                        fonte_tarefa,
                        base,
                        inicio_pagina,
                        tamanho,
                    )
                    resultados, leases = executar_tarefas([primeiro])
                    if parou_por_limite:
                        finalizar_leases(leases, pendentes=True)
                        break
                    total_conhecido = next(
                        (resultado.total for resultado in resultados if resultado.tarefa.get("id") == primeiro.get("id")),
                        None,
                    )
                    if total_conhecido is not None:
                        limite_fonte = total_paginas_fonte(
                            fonte_tarefa, total_conhecido, tamanho
                        )
                        fim_lote = min(
                            max_paginas,
                            inicio_pagina + PAGINAS_POR_LOTE - 1,
                            max(inicio_pagina, limite_fonte),
                        )
                    else:
                        # Se a primeira página falhou, ainda consulte as
                        # próximas quatro: a falha vira RETRY sem bloquear a
                        # cobertura das páginas seguintes.
                        fim_lote = min(
                            max_paginas,
                            inicio_pagina + PAGINAS_POR_LOTE - 1,
                        )

                    restantes = [
                        _criar_tarefa_pagina(
                            estado,
                            fonte_tarefa,
                            base,
                            pagina,
                            tamanho,
                        )
                        for pagina in range(inicio_pagina + 1, fim_lote + 1)
                    ]
                    if restantes:
                        resultados_restantes, leases_restantes = executar_tarefas(restantes)
                        resultados.extend(resultados_restantes)
                        leases = [*leases, *leases_restantes]
                    log(
                        f"{rotulo}: páginas {inicio_pagina}–{fim_lote} "
                        f"({len(resultados)} respostas)"
                    )
                    inspecionar_paginas(resultados, leases)
                    if parou_por_limite or alvo_atingido():
                        break

                    total_batch = next(
                        (
                            resultado.total
                            for resultado in reversed(resultados)
                            if resultado.tarefa.get("fonte") == fonte_tarefa
                        ),
                        total_conhecido,
                    )
                    if total_batch is not None:
                        limite_fonte = total_paginas_fonte(
                            fonte_tarefa, total_batch, tamanho
                        )
                        if limite_fonte <= fim_lote:
                            break
                        if fim_lote >= max_paginas:
                            cobertura_incompleta_execucao = True
                            break
                    elif any(not resultado.registros for resultado in resultados):
                        break
                    inicio_pagina = fim_lote + 1

            try:
                if fonte in {"auto", "pncp-busca"} and not alvo_atingido():
                    consultas = termos_historicos(termos, data_inicial, data_final)
                    for consulta in consultas:
                        if alvo_atingido() or parou_por_limite:
                            break
                        rodar_consulta(
                            "pncp-busca",
                            {"termo": consulta},
                            50,
                            max_paginas_busca,
                            rotulo=f"busca PNCP q={consulta!r}",
                        )

                if fonte in {"auto", "compras"} and not alvo_atingido() and not parou_por_limite:
                    for inicio_janela, fim_janela in janelas_calendario(
                        data_inicial, data_final, janela_dias
                    ):
                        if alvo_atingido() or parou_por_limite:
                            break
                        rodar_consulta(
                            "compras-gov",
                            {"inicio": inicio_janela, "fim": fim_janela},
                            500,
                            max_paginas_feed,
                            rotulo=f"feed Compras.gov.br {inicio_janela}–{fim_janela}",
                        )

                if fonte == "pncp-feed" and not alvo_atingido() and not parou_por_limite:
                    for inicio_janela, fim_janela in janelas_calendario(
                        data_inicial, data_final, janela_dias
                    ):
                        if alvo_atingido() or parou_por_limite:
                            break
                        rodar_consulta(
                            "pncp-feed",
                            {"inicio": inicio_janela, "fim": fim_janela},
                            500,
                            max_paginas_feed,
                            rotulo=f"feed PNCP {inicio_janela}–{fim_janela}",
                        )
            finally:
                resumo = _catalogar(
                    caminhos,
                    estado,
                    alvo=processos,
                    fonte=fonte,
                    log=log,
                    cobertura_incompleta=cobertura_incompleta_execucao,
                )
                resumo.update(
                    {
                        "compras_inspecionadas_nesta_execucao": total_inspecoes,
                        "pares_publicados_nesta_execucao": total_pares_publicados,
                        "registros_invalidos_ano_nesta_execucao": registros_invalidos,
                        "aceitos_migrados_sem_download": migrados_legados,
                        "tentativas_documentais_por_orgao": dict(tentativas_documentais),
                        "max_tentativas_documentais_por_orgao": max_tentativas_documentais_por_orgao,
                        "parou_por_limite_requisicoes": parou_por_limite,
                    }
                )
                escrever_json(caminhos.catalogo / "estatisticas.json", resumo)

    return resumo


# ----------------------------------------------------------------------- CLI


def principal(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Coleta somente pares ETP→TR pelas APIs públicas PNCP/Compras.gov.br."
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
        choices=("auto", "pncp-busca", "compras", "pncp-feed"),
        default="auto",
    )
    parser.add_argument("--termo", action="append", dest="termos", default=None)
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
    parser.add_argument("--max-paginas-busca", type=int, default=40)
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
        help="timeout por tentativa nas confirmações de metadados",
    )
    parser.add_argument(
        "--tentativas-confirmacao",
        type=int,
        default=1,
        help="tentativas rápidas por canal antes de registrar RETRY",
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
