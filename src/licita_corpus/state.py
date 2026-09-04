"""Estado persistente e pequeno da coleta de cadeias documentais.

O estado não é o corpus: ele só permite retomar uma coleta interrompida sem
repetir páginas, inspeções de arquivos ou consumir novamente o orçamento de
requisições da API no mesmo dia.

O banco é deliberadamente mantido com SQLite simples. A inicialização é uma
migração transacional: bancos criados por versões anteriores continuam
utilizáveis, as colunas/dados originais são preservados e somente as tabelas de
resultados que precisam da chave composta são reconstruídas atomicamente.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


class LimiteRequisicoes(RuntimeError):
    """O orçamento local de chamadas da API foi esgotado."""


# Identificador da política usada para decidir se uma inspeção pode ser
# reaproveitada.  É texto de propósito: além de ``1`` permite versões como
# ``"2025-01"`` sem alterar o schema.
# Policy default permanece o identificador histórico para que bancos e
# artefatos R4 antigos continuem reprodutíveis. O coletor novo informa
# explicitamente sua policy de cadeia completa.
POLICY_VERSION = "4-municipal-historical-ocr"
DEFAULT_POLICY_VERSION = POLICY_VERSION

# Os valores são apenas defaults.  Chamadas individuais podem informar outro
# TTL, o que também torna a política testável sem esperar pelo relógio real.
CACHE_TTL_SEGUNDOS = 24 * 60 * 60
CACHE_TTL_VAZIO_SEGUNDOS = 5 * 60
DEFAULT_LEASE_SEGUNDOS = 300
# Alias curto para consumidores que expõem a duração da lease.
LEASE_SEGUNDOS = DEFAULT_LEASE_SEGUNDOS

STATUS_PENDENTE = "PENDENTE"
STATUS_CONCLUIDO = "CONCLUIDO"
STATUS_RETRY = "RETRY"
# Atalhos curtos também são exportados para consumidores que preferem usar
# os estados diretamente.
PENDENTE = STATUS_PENDENTE
CONCLUIDO = STATUS_CONCLUIDO
RETRY = STATUS_RETRY
STATUS_TAREFA_PENDENTE = STATUS_PENDENTE
STATUS_TAREFA_CONCLUIDO = STATUS_CONCLUIDO
STATUS_TAREFA_RETRY = STATUS_RETRY

STATUS_TAREFAS_PAGINACAO = frozenset(
    {STATUS_PENDENTE, STATUS_CONCLUIDO, STATUS_RETRY}
)

_MISSING = object()


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _json_parametros(parametros: Mapping[str, Any]) -> str:
    """Representação estável usada pela identidade natural de uma tarefa."""
    return json.dumps(
        dict(parametros),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _ttl_segundos(valor: Any) -> float | None:
    """Converte as formas públicas de TTL para segundos.

    ``None`` significa sem expiração.  TTL zero é válido e representa uma
    entrada que já não deve ser reutilizada.
    """
    if valor is None:
        return None
    if isinstance(valor, timedelta):
        resultado = valor.total_seconds()
    else:
        try:
            resultado = float(valor)
        except (TypeError, ValueError) as erro:
            raise ValueError("TTL deve ser numérico, timedelta ou None") from erro
    if not math.isfinite(resultado):
        if resultado > 0:
            return None
        raise ValueError("TTL deve ser finito ou None")
    if resultado < 0:
        raise ValueError("TTL não pode ser negativo")
    return resultado


def _datetime_utc(valor: Any) -> datetime | None:
    """Interpreta um instante persistido, sempre em UTC."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        instante = valor
    elif isinstance(valor, date):
        instante = datetime.combine(valor, datetime.min.time())
    else:
        texto = str(valor).strip()
        if not texto:
            return None
        try:
            instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            # Bancos antigos podem conter somente a data.  Não aceite um
            # prefixo de data de um valor maior: isso esconderia corrupção.
            if len(texto) != 10:
                return None
            try:
                instante = datetime.strptime(texto, "%Y-%m-%d")
            except ValueError:
                return None
    if instante.tzinfo is None:
        return instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc)


def _texto_instante(valor: Any, *, padrao: datetime | None = None) -> str:
    """Serializa um instante no único formato persistido pelo estado.

    Valores fornecidos pela aplicação que não sejam instantes válidos são
    erros.  A migração usa um caminho separado e registra esses erros antes de
    escolher um valor de recuperação, em vez de transformar corrupção em
    ``agora`` silenciosamente.
    """
    instante = _datetime_utc(valor)
    if instante is None:
        if valor is not None:
            raise ValueError("timestamp inválido")
        instante = padrao or datetime.now(timezone.utc)
    return instante.isoformat()


def _dia_utc(valor: Any = None, *, agora: Any = None) -> str:
    if valor is None:
        instante = _datetime_utc(agora)
        if instante is None:
            instante = datetime.now(timezone.utc)
        return instante.date().isoformat()
    if isinstance(valor, datetime):
        instante = _datetime_utc(valor)
        assert instante is not None  # para satisfazer o type checker
        return instante.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    texto = str(valor).strip()
    if not texto:
        raise ValueError("dia_utc não pode ser vazio")
    # Aceita tanto YYYY-MM-DD quanto um ISO completo para facilitar a
    # inspeção/reprodução de execuções antigas.
    instante = _datetime_utc(texto)
    if instante is not None:
        return instante.date().isoformat()
    raise ValueError("dia_utc deve ser uma data ISO válida")


def _inteiro_nao_negativo(valor: Any, nome: str) -> int:
    if isinstance(valor, bool):
        raise ValueError(f"{nome} deve ser inteiro não negativo")
    try:
        resultado = int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{nome} deve ser inteiro não negativo") from erro
    if resultado < 0:
        raise ValueError(f"{nome} deve ser inteiro não negativo")
    return resultado


def _token_normalizado(valor: Any) -> str | None:
    """Normaliza a identidade de um worker antes de qualquer comparação.

    SQLite considera ``''`` um valor real em um índice UNIQUE (ao contrário de
    NULL).  Tokens vazios ou formados só por espaços não identificam um dono e
    portanto precisam ter a semântica de NULL em toda a API, não apenas durante
    a migração.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _quantidade_legada(valor: Any) -> int | None:
    """Lê uma quantidade antiga sem converter corrupção em um número válido."""
    limite_sqlite = 2**63 - 1
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return valor if 0 <= valor <= limite_sqlite else None
    if isinstance(valor, float):
        if (
            not math.isfinite(valor)
            or not valor.is_integer()
            or valor < 0
            or valor > limite_sqlite
        ):
            return None
        return int(valor)
    texto = str(valor).strip()
    if not texto or not re.fullmatch(r"\+?\d+", texto):
        return None
    try:
        resultado = int(texto)
    except (TypeError, ValueError, OverflowError):
        return None
    return resultado if resultado <= limite_sqlite else None


def _payload_vazio(payload: Any) -> bool:
    """Indica respostas sem conteúdo útil, sem considerar 0/False vazios.

    Além de ``[]``/``{}``, reconhece o formato comum de endpoints paginados
    (``[itens, total]`` ou ``{"items": [], "total": ...}``).
    """
    if payload is None or payload == [] or payload == {} or payload == "":
        return True
    if isinstance(payload, (list, tuple)):
        return bool(
            len(payload) == 2
            and payload[0] in (None, [], {})
        )
    if isinstance(payload, Mapping) and len(payload) == 1:
        valor = next(iter(payload.values()))
        return valor in (None, [], {}, "")
    if isinstance(payload, Mapping):
        for nome in ("items", "resultado", "resultados", "data", "content"):
            if nome in payload and payload[nome] in (None, [], {}, ""):
                return True
    return False


class EstadoColeta:
    """SQLite transacional para cache, fila e resultados aprovados.

    Os dois primeiros argumentos mantêm exatamente a API original.  As opções
    adicionais são opcionais e só controlam a política nova de cache, política
    de inspeção, margem de orçamento e tarefas de paginação.
    """

    # 8 adiciona o cache OCR permanente, separado do cache HTTP com TTL.
    _VERSAO_SCHEMA = 8
    POLICY_VERSION = POLICY_VERSION
    DEFAULT_LEASE_SEGUNDOS = DEFAULT_LEASE_SEGUNDOS
    LEASE_SEGUNDOS = DEFAULT_LEASE_SEGUNDOS
    STATUS_PENDENTE = STATUS_PENDENTE
    STATUS_CONCLUIDO = STATUS_CONCLUIDO
    STATUS_RETRY = STATUS_RETRY

    def __init__(
        self,
        caminho: Path,
        max_requisicoes_dia: int = 0,
        *,
        policy_version: str | int = DEFAULT_POLICY_VERSION,
        cache_ttl_segundos: float | timedelta | None = CACHE_TTL_SEGUNDOS,
        cache_ttl_vazio_segundos: float | timedelta | None = CACHE_TTL_VAZIO_SEGUNDOS,
        margem_requisicoes: int = 0,
        **opcoes: Any,
    ) -> None:
        # Alguns nomes de configuração são mantidos como aliases para que a
        # adoção da política não exija mudanças nos chamadores existentes.
        if "ttl_cache" in opcoes:
            cache_ttl_segundos = opcoes.pop("ttl_cache")
        if "cache_ttl" in opcoes:
            cache_ttl_segundos = opcoes.pop("cache_ttl")
        if "ttl_vazio" in opcoes:
            cache_ttl_vazio_segundos = opcoes.pop("ttl_vazio")
        if "ttl_cache_vazio" in opcoes:
            cache_ttl_vazio_segundos = opcoes.pop("ttl_cache_vazio")
        if "ttl_respostas" in opcoes:
            cache_ttl_segundos = opcoes.pop("ttl_respostas")
        if "ttl_respostas_vazias" in opcoes:
            cache_ttl_vazio_segundos = opcoes.pop("ttl_respostas_vazias")
        if "versao_politica" in opcoes:
            policy_version = opcoes.pop("versao_politica")
        if "policy" in opcoes:
            policy_version = opcoes.pop("policy")
        if "margem_orcamento" in opcoes:
            margem_requisicoes = opcoes.pop("margem_orcamento")
        if "margem" in opcoes:
            margem_requisicoes = opcoes.pop("margem")
        if "budget_margin" in opcoes:
            margem_requisicoes = opcoes.pop("budget_margin")
        if opcoes:
            nomes = ", ".join(sorted(opcoes))
            raise TypeError(f"opções desconhecidas: {nomes}")

        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.max_requisicoes_dia = int(max_requisicoes_dia)
        self.policy_version = str(policy_version)
        self.cache_ttl_segundos = _ttl_segundos(cache_ttl_segundos)
        self.cache_ttl_vazio_segundos = _ttl_segundos(cache_ttl_vazio_segundos)
        # Nomes curtos para código de configuração que já use a convenção
        # ``ttl_cache``.
        self.ttl_cache = self.cache_ttl_segundos
        self.ttl_cache_vazio = self.cache_ttl_vazio_segundos
        self.margem_requisicoes = _inteiro_nao_negativo(
            margem_requisicoes, "margem_requisicoes"
        )

        self.conexao = sqlite3.connect(caminho)
        self.conexao.row_factory = sqlite3.Row
        self.conexao.execute("PRAGMA journal_mode=WAL")
        self.conexao.execute("PRAGMA busy_timeout=30000")
        self._requisicoes_migracao_insegura = False
        try:
            self._inicializar_schema()
        except BaseException:
            # A inicialização é uma transação única. Fechar aqui também evita
            # deixar uma conexão parcialmente inicializada nas migrações que
            # falham por um schema externo incompatível.
            self.conexao.rollback()
            self.conexao.close()
            raise

    def _inicializar_schema(self) -> None:
        """Cria o schema e migra um banco legado em uma única transação.

        SQLite não permite alterar uma ``PRIMARY KEY`` existente. As tabelas
        de inspeção e aceite são, portanto, copiadas para uma tabela com a
        chave composta quando necessário. DDL, normalização, auditoria e
        índices ficam dentro da mesma transação; uma falha deixa o banco
        legado intacto em vez de produzir uma migração pela metade.
        """
        try:
            self.conexao.execute("BEGIN IMMEDIATE")

            # Não use executescript aqui: ele pode confirmar implicitamente a
            # transação aberta pelo chamador em versões do sqlite3.
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS respostas (
                       chave TEXT PRIMARY KEY,
                       payload TEXT NOT NULL,
                       atualizada_em TEXT NOT NULL
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS inspecoes (
                       numero_controle_pncp TEXT NOT NULL,
                       status TEXT NOT NULL,
                       motivo TEXT,
                       compra_json TEXT NOT NULL,
                       arquivos_json TEXT,
                       candidato_json TEXT,
                       atualizada_em TEXT NOT NULL,
                       policy_version TEXT NOT NULL DEFAULT '1',
                       PRIMARY KEY (numero_controle_pncp, policy_version)
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS aceitos (
                       numero_controle_pncp TEXT NOT NULL,
                       candidato_json TEXT NOT NULL,
                       documentos_json TEXT NOT NULL,
                       aceito_em TEXT NOT NULL,
                       policy_version TEXT NOT NULL DEFAULT '1',
                       PRIMARY KEY (numero_controle_pncp, policy_version)
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS requisicoes (
                       dia_utc TEXT PRIMARY KEY,
                       quantidade INTEGER NOT NULL
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS ocr_resultados (
                       sha256_original TEXT NOT NULL,
                       idioma TEXT NOT NULL,
                       pipeline_version TEXT NOT NULL,
                       configuracao_json TEXT NOT NULL,
                       chave TEXT NOT NULL UNIQUE,
                       resultado_json TEXT NOT NULL,
                       texto_sha256 TEXT NOT NULL,
                       criado_em TEXT NOT NULL,
                       PRIMARY KEY (
                           sha256_original, idioma, pipeline_version,
                           configuracao_json
                       )
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS tarefas_paginacao (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       chave TEXT NOT NULL,
                       fonte TEXT NOT NULL,
                       parametros_json TEXT NOT NULL,
                       pagina INTEGER NOT NULL,
                       tamanho_pagina INTEGER,
                       status TEXT NOT NULL DEFAULT 'PENDENTE',
                       tentativas INTEGER NOT NULL DEFAULT 0,
                       erro TEXT,
                       proxima_tentativa_em TEXT,
                       reservada_ate TEXT,
                       criada_em TEXT NOT NULL,
                       atualizada_em TEXT NOT NULL,
                       worker_token TEXT,
                       owner TEXT,
                       CHECK (status IN ('PENDENTE', 'CONCLUIDO', 'RETRY'))
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS requisicoes_invalidas (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       rowid_legado INTEGER,
                       dia_utc_original TEXT,
                       quantidade_original TEXT,
                       motivo TEXT NOT NULL,
                       auditada_em TEXT NOT NULL
                   )"""
            )
            self.conexao.execute(
                """CREATE TABLE IF NOT EXISTS migracao_erros (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       tabela TEXT NOT NULL,
                       rowid_legado INTEGER,
                       campo TEXT,
                       valor_original TEXT,
                       motivo TEXT NOT NULL,
                       registrado_em TEXT NOT NULL
                   )"""
            )
            for tabela, coluna, definicao in (
                ("requisicoes_invalidas", "id", "INTEGER"),
                ("requisicoes_invalidas", "rowid_legado", "INTEGER"),
                ("requisicoes_invalidas", "dia_utc_original", "TEXT"),
                ("requisicoes_invalidas", "quantidade_original", "TEXT"),
                ("requisicoes_invalidas", "motivo", "TEXT"),
                ("requisicoes_invalidas", "auditada_em", "TEXT"),
                ("migracao_erros", "id", "INTEGER"),
                ("migracao_erros", "tabela", "TEXT"),
                ("migracao_erros", "rowid_legado", "INTEGER"),
                ("migracao_erros", "campo", "TEXT"),
                ("migracao_erros", "valor_original", "TEXT"),
                ("migracao_erros", "motivo", "TEXT"),
                ("migracao_erros", "registrado_em", "TEXT"),
            ):
                self._adicionar_coluna(tabela, coluna, definicao)

            # Todas as colunas são adicionadas antes de qualquer índice. Isso
            # inclui tabelas intermediárias que foram criadas só pela metade.
            for tabela, coluna, definicao in (
                ("respostas", "chave", "TEXT"),
                ("respostas", "payload", "TEXT"),
                ("respostas", "atualizada_em", "TEXT"),
                ("inspecoes", "numero_controle_pncp", "TEXT"),
                ("inspecoes", "status", "TEXT DEFAULT 'ERRO_API'"),
                ("inspecoes", "motivo", "TEXT"),
                ("inspecoes", "compra_json", "TEXT"),
                ("inspecoes", "arquivos_json", "TEXT"),
                ("inspecoes", "candidato_json", "TEXT"),
                ("inspecoes", "atualizada_em", "TEXT"),
                ("aceitos", "numero_controle_pncp", "TEXT"),
                ("aceitos", "candidato_json", "TEXT"),
                ("aceitos", "documentos_json", "TEXT"),
                ("aceitos", "aceito_em", "TEXT"),
                ("requisicoes", "dia_utc", "TEXT"),
                # Sem quantidade, NULL precisa ser auditado; zero liberaria
                # orçamento como se a ausência fosse dado válido.
                ("requisicoes", "quantidade", "INTEGER"),
            ):
                self._adicionar_coluna(tabela, coluna, definicao)
            self._adicionar_coluna(
                "inspecoes", "policy_version", "TEXT NOT NULL DEFAULT '1'"
            )
            self._adicionar_coluna(
                "aceitos", "policy_version", "TEXT NOT NULL DEFAULT '1'"
            )
            self._adicionar_coluna("respostas", "ttl_segundos", "REAL")
            self._adicionar_coluna("respostas", "ttl_vazio_segundos", "REAL")
            self._adicionar_coluna(
                "respostas", "payload_vazio", "INTEGER NOT NULL DEFAULT 0"
            )

            # A fila foi introduzida depois das tabelas originais. ``id``
            # também é adicionado para protótipos que usavam apenas rowid.
            for coluna, definicao in (
                ("id", "INTEGER"),
                ("chave", "TEXT"),
                ("fonte", "TEXT"),
                ("parametros_json", "TEXT"),
                ("pagina", "INTEGER"),
                ("tamanho_pagina", "INTEGER"),
                ("status", "TEXT NOT NULL DEFAULT 'PENDENTE'"),
                ("tentativas", "INTEGER NOT NULL DEFAULT 0"),
                ("erro", "TEXT"),
                ("proxima_tentativa_em", "TEXT"),
                ("reservada_ate", "TEXT"),
                ("criada_em", "TEXT"),
                ("atualizada_em", "TEXT"),
                ("worker_token", "TEXT"),
                ("owner", "TEXT"),
            ):
                self._adicionar_coluna("tarefas_paginacao", coluna, definicao)

            # Índices antigos (inclusive UNIQUE com uma definição errada)
            # podem impedir a própria cópia/normalização. Eles só voltam a
            # existir depois da deduplicação e serão validados por
            # _garantir_indice.
            for nome_indice in (
                "idx_tarefas_paginacao_prontas",
                "idx_tarefas_paginacao_status",
                "uq_tarefas_paginacao_id",
                "uq_tarefas_paginacao_chave",
                "uq_tarefas_paginacao_natural",
                "uq_tarefas_paginacao_worker_token",
                "uq_tarefas_paginacao_owner",
            ):
                if self._indice_listado("tarefas_paginacao", nome_indice) is not None:
                    self.conexao.execute(
                        f"DROP INDEX {self._sql_identificador(nome_indice)}"
                    )

            # Nomes usados por protótipos intermediários são copiados sem
            # apagar a coluna atual. A operação é idempotente.
            self._copiar_coluna_legada(
                "tarefas_paginacao", "parametros_json", "params_json"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "parametros_json", "parametros"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "criada_em", "criado_em"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "criada_em", "created_at"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "atualizada_em", "updated_at"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "proxima_tentativa_em", "proxima_tentativa"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "proxima_tentativa_em", "next_attempt_at"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "reservada_ate", "lease_ate"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "reservada_ate", "reserved_until"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "worker_token", "token"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "worker_token", "owner"
            )
            self._copiar_coluna_legada(
                "tarefas_paginacao", "owner", "worker_token"
            )

            # Algumas versões usavam nomes diferentes para o contador. O
            # valor canônico é sempre o que será validado logo abaixo.
            for origem in ("dia", "data", "data_utc", "date"):
                self._copiar_coluna_legada("requisicoes", "dia_utc", origem)
            for origem in ("count", "quantidade_requisicoes", "total"):
                self._copiar_coluna_legada("requisicoes", "quantidade", origem)

            migracao_em = _texto_instante(self.agora())
            self._migrar_requisicoes(migracao_em)
            self._migrar_tabelas_politica(migracao_em)
            self._migrar_timestamps_simples(migracao_em)
            self._migrar_tarefas(migracao_em)

            # IF NOT EXISTS não valida uma definição já existente. Cada
            # índice é inspecionado e recriado quando as colunas/uniqueness
            # não correspondem ao contrato atual.
            self._garantir_indice(
                "idx_inspecoes_status", "inspecoes", ("status",)
            )
            self._garantir_indice(
                "idx_aceitos_policy_version", "aceitos", ("policy_version",)
            )
            self._garantir_indice(
                "idx_tarefas_paginacao_prontas",
                "tarefas_paginacao",
                ("status", "proxima_tentativa_em", "reservada_ate"),
            )
            self._garantir_indice(
                "idx_tarefas_paginacao_status", "tarefas_paginacao", ("status",)
            )
            self._garantir_indice(
                "uq_tarefas_paginacao_id", "tarefas_paginacao", ("id",), unico=True
            )
            self._garantir_indice(
                "uq_tarefas_paginacao_chave",
                "tarefas_paginacao",
                ("chave",),
                unico=True,
            )
            self._garantir_indice(
                "uq_tarefas_paginacao_natural",
                "tarefas_paginacao",
                ("fonte", "parametros_json", "pagina", None),
                unico=True,
                expressao="COALESCE(tamanho_pagina, -1)",
            )
            self._garantir_indice(
                "uq_tarefas_paginacao_worker_token",
                "tarefas_paginacao",
                ("worker_token",),
                unico=True,
            )
            self._garantir_indice(
                "uq_tarefas_paginacao_owner",
                "tarefas_paginacao",
                ("owner",),
                unico=True,
            )

            versao_atual = int(
                self.conexao.execute("PRAGMA user_version").fetchone()[0]
            )
            if versao_atual < self._VERSAO_SCHEMA:
                self.conexao.execute(f"PRAGMA user_version = {self._VERSAO_SCHEMA}")
            self.conexao.commit()
        except BaseException:
            self.conexao.rollback()
            raise

    @staticmethod
    def _sql_identificador(nome: str) -> str:
        return '"' + str(nome).replace('"', '""') + '"'

    def _colunas_info(self, tabela: str) -> list[sqlite3.Row]:
        nome = self._sql_identificador(tabela)
        return list(self.conexao.execute(f"PRAGMA table_info({nome})"))

    def _colunas_tabela(self, tabela: str) -> set[str]:
        return {str(linha[1]) for linha in self._colunas_info(tabela)}

    def _adicionar_coluna(self, tabela: str, coluna: str, definicao: str) -> None:
        if coluna not in self._colunas_tabela(tabela):
            self.conexao.execute(
                f"ALTER TABLE {self._sql_identificador(tabela)} "
                f"ADD COLUMN {self._sql_identificador(coluna)} {definicao}"
            )

    def _copiar_coluna_legada(
        self, tabela: str, destino: str, origem: str
    ) -> None:
        colunas = self._colunas_tabela(tabela)
        if destino in colunas and origem in colunas and destino != origem:
            tabela_sql = self._sql_identificador(tabela)
            destino_sql = self._sql_identificador(destino)
            origem_sql = self._sql_identificador(origem)
            self.conexao.execute(
                f"UPDATE {tabela_sql} SET {destino_sql} = {origem_sql} "
                f"WHERE {destino_sql} IS NULL AND {origem_sql} IS NOT NULL"
            )

    @staticmethod
    def _texto_original(valor: Any) -> str | None:
        if valor is None:
            return None
        if isinstance(valor, bytes):
            return valor.decode("utf-8", errors="replace")
        return str(valor)

    def _registrar_migracao(
        self,
        tabela: str,
        rowid_legado: Any,
        campo: str | None,
        valor_original: Any,
        motivo: str,
        registrado_em: str,
    ) -> None:
        self.conexao.execute(
            """INSERT INTO migracao_erros
                   (tabela, rowid_legado, campo, valor_original, motivo,
                    registrado_em)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                tabela,
                rowid_legado,
                campo,
                self._texto_original(valor_original),
                motivo,
                registrado_em,
            ),
        )

    def _linhas_com_rowid(self, tabela: str) -> list[dict[str, Any]]:
        tabela_sql = self._sql_identificador(tabela)
        try:
            linhas = self.conexao.execute(
                f"SELECT rowid AS _rowid, * FROM {tabela_sql}"
            ).fetchall()
            return [dict(linha) for linha in linhas]
        except sqlite3.OperationalError as erro:
            if "rowid" not in str(erro).lower():
                raise
            # Uma tabela WITHOUT ROWID ainda pode ser um legado válido. A
            # posição da linha é apenas um desempate determinístico.
            linhas = self.conexao.execute(
                f"SELECT * FROM {tabela_sql}"
            ).fetchall()
            return [
                {**dict(linha), "_rowid": posicao}
                for posicao, linha in enumerate(linhas, start=1)
            ]

    def _migrar_requisicoes(self, migracao_em: str) -> None:
        """Canonicaliza, soma e audita o contador diário legado.

        Uma data com offset é convertida para a data do instante em UTC. Todas
        as linhas válidas são agregadas antes de serem gravadas, de modo que
        dois registros como ``23:30-03:00`` e ``02:30Z`` ocupem a mesma chave.
        Linha inválida não é descartada silenciosamente: seu texto original é
        guardado em ``requisicoes_invalidas`` e o orçamento finito entra em
        modo *fail closed* até que a auditoria seja resolvida.
        """
        agregadas: dict[str, int] = {}
        linhas_invalidas: list[tuple[dict[str, Any], str]] = []
        for registro in self._linhas_com_rowid("requisicoes"):
            dia_original = registro.get("dia_utc")
            quantidade_original = registro.get("quantidade")
            erros: list[str] = []
            try:
                dia = _dia_utc(dia_original)
            except (TypeError, ValueError) as erro:
                dia = None
                erros.append(f"dia_utc inválido ({erro})")
            quantidade = _quantidade_legada(quantidade_original)
            if quantidade is None:
                erros.append("quantidade inválida")
            if erros:
                linhas_invalidas.append((registro, "; ".join(erros)))
                continue
            assert dia is not None
            assert quantidade is not None
            total = agregadas.get(dia, 0) + quantidade
            if total > 2**63 - 1:
                linhas_invalidas.append(
                    (registro, "quantidade agregada excede o limite do SQLite")
                )
            else:
                agregadas[dia] = total

        # DELETE + INSERT é deliberado. INSERT OR REPLACE não soma linhas
        # canônicas e uma tabela antiga pode ter uma UNIQUE incompatível.
        self.conexao.execute("DELETE FROM requisicoes")
        self.conexao.executemany(
            "INSERT INTO requisicoes (dia_utc, quantidade) VALUES (?, ?)",
            sorted(agregadas.items()),
        )
        for registro, motivo in linhas_invalidas:
            self.conexao.execute(
                """INSERT INTO requisicoes_invalidas
                       (rowid_legado, dia_utc_original, quantidade_original,
                        motivo, auditada_em)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    registro.get("_rowid"),
                    self._texto_original(registro.get("dia_utc")),
                    self._texto_original(registro.get("quantidade")),
                    motivo,
                    migracao_em,
                ),
            )
            self._registrar_migracao(
                "requisicoes",
                registro.get("_rowid"),
                "dia_utc/quantidade",
                (
                    self._texto_original(registro.get("dia_utc")),
                    self._texto_original(registro.get("quantidade")),
                ),
                motivo,
                migracao_em,
            )
        self._requisicoes_migracao_insegura = (
            self.conexao.execute(
                "SELECT 1 FROM requisicoes_invalidas LIMIT 1"
            ).fetchone()
            is not None
        )

    def _chaves_primarias(self, tabela: str) -> list[str]:
        informacoes = [linha for linha in self._colunas_info(tabela) if linha[5]]
        return [
            str(linha[1])
            for linha in sorted(informacoes, key=lambda linha: int(linha[5]))
        ]

    def _indice_listado(
        self, tabela: str, nome: str
    ) -> sqlite3.Row | None:
        tabela_sql = self._sql_identificador(tabela)
        for linha in self.conexao.execute(f"PRAGMA index_list({tabela_sql})"):
            if str(linha[1]) == nome:
                return linha
        return None

    def _colunas_indice(self, nome: str) -> list[str | None]:
        nome_sql = self._sql_identificador(nome)
        return [
            None if linha[2] is None else str(linha[2])
            for linha in self.conexao.execute(f"PRAGMA index_info({nome_sql})")
        ]

    def _schema_politica_correto(self, tabela: str) -> bool:
        esperadas = {
            "inspecoes": {
                "numero_controle_pncp",
                "status",
                "compra_json",
                "atualizada_em",
                "policy_version",
            },
            "aceitos": {
                "numero_controle_pncp",
                "candidato_json",
                "documentos_json",
                "aceito_em",
                "policy_version",
            },
        }[tabela]
        colunas = {str(linha[1]): linha for linha in self._colunas_info(tabela)}
        if not esperadas.issubset(colunas):
            return False
        if self._chaves_primarias(tabela) != [
            "numero_controle_pncp",
            "policy_version",
        ]:
            return False
        definicao_tabela = self.conexao.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (tabela,),
        ).fetchone()
        sql_tabela = str(definicao_tabela[0] or "").lower() if definicao_tabela else ""
        if "without rowid" in sql_tabela:
            return False
        obrigatorias = (
            ("numero_controle_pncp", "status", "compra_json", "atualizada_em", "policy_version")
            if tabela == "inspecoes"
            else (
                "numero_controle_pncp",
                "candidato_json",
                "documentos_json",
                "aceito_em",
                "policy_version",
            )
        )
        if any(not int(colunas[nome][3]) for nome in obrigatorias):
            return False
        # Uma UNIQUE(numero) antiga continua impedindo v1 e v2 coexistirem,
        # mesmo que alguém tenha criado a PK composta depois.
        for indice in self.conexao.execute(
            f"PRAGMA index_list({self._sql_identificador(tabela)})"
        ):
            if int(indice[2]) and self._colunas_indice(str(indice[1])) != [
                "numero_controle_pncp",
                "policy_version",
            ]:
                return False
        return True

    def _decl_extra(self, tipo: Any) -> str:
        texto = str(tipo or "BLOB")
        # O schema vem de um arquivo SQLite externo. Preserve tipos usuais,
        # mas não interpolamos caracteres de uma declaração arbitrária.
        if not re.fullmatch(r"[A-Za-z0-9_ ,()]+", texto):
            return "BLOB"
        return texto or "BLOB"

    def _migrar_tabelas_politica(self, migracao_em: str) -> None:
        for tabela in ("inspecoes", "aceitos"):
            # A normalização de policy_version acontece na cópia. Fazer UPDATE
            # antes dela poderia colidir com uma UNIQUE antiga (por exemplo,
            # as versões "1" e " 1 ") e interromper uma migração recuperável.
            if not self._schema_politica_correto(tabela):
                self._reconstruir_tabela_politica(tabela, migracao_em)

    def _reconstruir_tabela_politica(
        self, tabela: str, migracao_em: str
    ) -> None:
        if tabela == "inspecoes":
            conhecidas = [
                "numero_controle_pncp",
                "status",
                "motivo",
                "compra_json",
                "arquivos_json",
                "candidato_json",
                "atualizada_em",
                "policy_version",
            ]
            declaracoes = [
                "numero_controle_pncp TEXT NOT NULL",
                "status TEXT NOT NULL",
                "motivo TEXT",
                "compra_json TEXT NOT NULL",
                "arquivos_json TEXT",
                "candidato_json TEXT",
                "atualizada_em TEXT NOT NULL",
                "policy_version TEXT NOT NULL DEFAULT '1'",
            ]
            obrigatorios_json = {"compra_json": "{}"}
            timestamp_coluna = "atualizada_em"
        else:
            conhecidas = [
                "numero_controle_pncp",
                "candidato_json",
                "documentos_json",
                "aceito_em",
                "policy_version",
            ]
            declaracoes = [
                "numero_controle_pncp TEXT NOT NULL",
                "candidato_json TEXT NOT NULL",
                "documentos_json TEXT NOT NULL",
                "aceito_em TEXT NOT NULL",
                "policy_version TEXT NOT NULL DEFAULT '1'",
            ]
            obrigatorios_json = {
                "candidato_json": "{}",
                "documentos_json": "[]",
            }
            timestamp_coluna = "aceito_em"

        informacoes = self._colunas_info(tabela)
        extras = [
            linha
            for linha in informacoes
            if str(linha[1]) not in conhecidas
        ]
        linhas = self._linhas_com_rowid(tabela)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
        preparados: dict[
            tuple[str, str], tuple[datetime, int, dict[str, Any]]
        ] = {}
        for posicao, registro in enumerate(linhas, start=1):
            rowid_valor = registro.get("_rowid")
            try:
                rowid = int(rowid_valor)
            except (TypeError, ValueError):
                rowid = posicao
            erros: list[str] = []

            numero_original = registro.get("numero_controle_pncp")
            numero = self._texto_original(numero_original)
            if numero is None or not numero.strip():
                numero = f"__licita_migracao_sem_numero__{rowid}"
                erros.append("numero_controle_pncp inválido")
            else:
                numero = numero.strip()

            politica_original = registro.get("policy_version")
            politica = self._texto_original(politica_original)
            if politica is None or not politica.strip():
                politica = "1"
                erros.append("policy_version inválida")
            else:
                politica = politica.strip()

            if tabela == "inspecoes":
                status_original = registro.get("status")
                status = self._texto_original(status_original)
                if status is None or not status.strip():
                    status = STATUS_RETRY
                    erros.append("status ausente")
                else:
                    status = status.strip()
                valores: dict[str, Any] = {
                    "numero_controle_pncp": numero,
                    "status": status,
                    "motivo": registro.get("motivo"),
                    "compra_json": registro.get("compra_json"),
                    "arquivos_json": registro.get("arquivos_json"),
                    "candidato_json": registro.get("candidato_json"),
                    "atualizada_em": None,
                    "policy_version": politica,
                }
            else:
                valores = {
                    "numero_controle_pncp": numero,
                    "candidato_json": registro.get("candidato_json"),
                    "documentos_json": registro.get("documentos_json"),
                    "aceito_em": None,
                    "policy_version": politica,
                }

            for coluna, padrao in obrigatorios_json.items():
                if valores[coluna] is None:
                    valores[coluna] = padrao
                    erros.append(f"{coluna} ausente")
            instante = _datetime_utc(registro.get(timestamp_coluna))
            if instante is None:
                instante = _datetime_utc(epoch)
                assert instante is not None
                erros.append(f"timestamp inválido em {timestamp_coluna}")
            valores[timestamp_coluna] = instante.isoformat()
            for detalhe in extras:
                nome = str(detalhe[1])
                valores[nome] = registro.get(nome)
            if erros:
                for detalhe in erros:
                    self._registrar_migracao(
                        tabela,
                        rowid,
                        None,
                        registro.get(detalhe.split(" ")[0]),
                        detalhe,
                        migracao_em,
                    )

            chave = (numero, politica)
            anterior = preparados.get(chave)
            atual = (instante, rowid, valores)
            if anterior is not None:
                self._registrar_migracao(
                    tabela,
                    rowid,
                    "numero_controle_pncp/policy_version",
                    f"{numero}/{politica}",
                    "duplicata da chave composta; mantido o registro mais recente",
                    migracao_em,
                )
            if anterior is None or (instante, rowid) >= (anterior[0], anterior[1]):
                preparados[chave] = atual

        temp = f"__licita_migracao_{tabela}"
        self.conexao.execute(f"DROP TABLE IF EXISTS {self._sql_identificador(temp)}")
        colunas_temp = list(declaracoes)
        for detalhe in extras:
            colunas_temp.append(
                f"{self._sql_identificador(str(detalhe[1]))} "
                f"{self._decl_extra(detalhe[2])}"
            )
        colunas_temp.append(
            "PRIMARY KEY (numero_controle_pncp, policy_version)"
        )
        self.conexao.execute(
            f"CREATE TABLE {self._sql_identificador(temp)} "
            f"({', '.join(colunas_temp)})"
        )
        colunas_insert = conhecidas + [str(detalhe[1]) for detalhe in extras]
        sql_insert = (
            f"INSERT INTO {self._sql_identificador(temp)} "
            f"({', '.join(self._sql_identificador(nome) for nome in colunas_insert)}) "
            f"VALUES ({', '.join('?' for _ in colunas_insert)})"
        )
        for _chave, (_instante, _rowid, valores) in preparados.items():
            self.conexao.execute(
                sql_insert,
                tuple(valores.get(nome) for nome in colunas_insert),
            )
        self.conexao.execute(f"DROP TABLE {self._sql_identificador(tabela)}")
        self.conexao.execute(
            f"ALTER TABLE {self._sql_identificador(temp)} "
            f"RENAME TO {self._sql_identificador(tabela)}"
        )

    def _garantir_indice(
        self,
        nome: str,
        tabela: str,
        colunas: tuple[str | None, ...],
        *,
        unico: bool = False,
        expressao: str | None = None,
    ) -> None:
        indice = self._indice_listado(tabela, nome)
        correto = False
        if indice is not None:
            parcial = int(indice[4]) if len(indice) > 4 else 0
            correto = (
                int(indice[2]) == int(unico)
                and parcial == 0
                and self._colunas_indice(nome) == list(colunas)
            )
            if correto and expressao is not None:
                sql = self.conexao.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'index' "
                    "AND name = ?",
                    (nome,),
                ).fetchone()
                sql_normal = re.sub(r"\s+", "", str(sql[0] if sql else "")).lower()
                expressao_normal = re.sub(r"\s+", "", expressao).lower()
                correto = expressao_normal in sql_normal and "where" not in sql_normal
            elif correto and expressao is None:
                correto = True
        if correto:
            return
        if indice is not None:
            self.conexao.execute(f"DROP INDEX {self._sql_identificador(nome)}")
        termos = [
            expressao if coluna is None else self._sql_identificador(coluna)
            for coluna in colunas
        ]
        self.conexao.execute(
            f"CREATE {'UNIQUE ' if unico else ''}INDEX "
            f"{self._sql_identificador(nome)} ON "
            f"{self._sql_identificador(tabela)} ({', '.join(termos)})"
        )

    @staticmethod
    def _erro_de_migracao(erro: Any, detalhe: str) -> str:
        marcador = f"migração: {detalhe}"
        texto = None if erro is None else str(erro)
        if not texto:
            return marcador
        if marcador in texto:
            return texto
        return f"{texto}; {marcador}"

    def _migrar_timestamps_simples(self, _migracao_em: str) -> None:
        """Canonicaliza timestamps fora da fila sem inventar ``agora``.

        Para dados que não têm estado de retry, o epoch é um valor seguro: a
        entrada fica antiga/expirada, mas o timestamp continua válido e a
        informação original não é transformada em uma execução recente.
        """
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
        for tabela, coluna in (
            ("respostas", "atualizada_em"),
            ("inspecoes", "atualizada_em"),
            ("aceitos", "aceito_em"),
        ):
            for linha in self.conexao.execute(
                f"SELECT rowid, {coluna} FROM {tabela}"
            ).fetchall():
                instante = _datetime_utc(linha[1])
                normalizado = (
                    instante.isoformat() if instante is not None else epoch
                )
                if linha[1] != normalizado:
                    if tabela == "respostas" and instante is None:
                        # Um TTL NULL não pode transformar timestamp
                        # corrompido em cache eterno.
                        self.conexao.execute(
                            "UPDATE respostas SET atualizada_em = ?, "
                            "ttl_segundos = 0, ttl_vazio_segundos = 0 "
                            "WHERE rowid = ?",
                            (normalizado, linha[0]),
                        )
                    else:
                        self.conexao.execute(
                            f"UPDATE {tabela} SET {coluna} = ? WHERE rowid = ?",
                            (normalizado, linha[0]),
                        )

    def _migrar_tarefas(self, _migracao_em: str) -> None:
        """Normaliza a fila e remove duplicatas de forma determinística."""
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
        linhas = self.conexao.execute(
            "SELECT rowid AS _rowid, * FROM tarefas_paginacao"
        ).fetchall()

        def inteiro(valor: Any, padrao: int) -> tuple[int, bool]:
            try:
                padrao_normal = int(padrao)
            except (TypeError, ValueError):
                padrao_normal = 1
            if valor is None:
                return padrao_normal, False
            if isinstance(valor, bool):
                return padrao_normal, False
            try:
                resultado = int(valor)
            except (TypeError, ValueError):
                return padrao_normal, False
            return (resultado, resultado >= 0)

        preparados: list[dict[str, Any]] = []
        for linha in linhas:
            registro = dict(linha)
            rowid = registro["_rowid"]
            erros: list[str] = []

            fonte = str(registro.get("fonte") or "")
            raw_parametros = registro.get("parametros_json")
            try:
                parametros_carregados = json.loads(raw_parametros)
                if not isinstance(parametros_carregados, Mapping):
                    raise ValueError("objeto JSON esperado")
                parametros = dict(parametros_carregados)
            except (TypeError, ValueError, json.JSONDecodeError):
                parametros = {}
                if raw_parametros not in (None, "", "{}"):
                    erros.append("parametros_json inválido")
            parametros_json = _json_parametros(parametros)

            pagina, pagina_ok = inteiro(
                registro.get("pagina"),
                parametros.get("pagina", 1),
            )
            if not pagina_ok:
                erros.append("pagina inválida")
            tamanho_valor = registro.get("tamanho_pagina")
            if tamanho_valor is None or tamanho_valor == "":
                tamanho = None
            else:
                tamanho, tamanho_ok = inteiro(tamanho_valor, 0)
                if not tamanho_ok:
                    tamanho = None
                    erros.append("tamanho_pagina inválido")

            status_original = str(registro.get("status") or STATUS_PENDENTE).upper()
            if status_original not in STATUS_TAREFAS_PAGINACAO:
                status = STATUS_PENDENTE
                erros.append("status inválido")
            else:
                status = status_original

            tentativas, tentativas_ok = inteiro(registro.get("tentativas"), 0)
            if not tentativas_ok:
                erros.append("tentativas inválidas")

            def timestamp_obrigatorio(nome: str) -> str:
                valor = registro.get(nome)
                instante = _datetime_utc(valor)
                if instante is None:
                    erros.append(f"timestamp inválido em {nome}")
                    # Epoch é válido/canônico, mas não faz um registro
                    # corrompido parecer uma tarefa recém-criada.
                    return epoch
                return instante.isoformat()

            criada = timestamp_obrigatorio("criada_em")
            atualizada = timestamp_obrigatorio("atualizada_em")

            def timestamp_opcional(nome: str) -> str | None:
                valor = registro.get(nome)
                if valor is None:
                    return None
                if str(valor).strip() == "":
                    erros.append(f"timestamp inválido em {nome}")
                    return None
                instante = _datetime_utc(valor)
                if instante is None:
                    erros.append(f"timestamp inválido em {nome}")
                    return None
                return instante.isoformat()

            proxima = timestamp_opcional("proxima_tentativa_em")
            reservada = timestamp_opcional("reservada_ate")

            # Normalize antes de deduplicar: '' e whitespace não podem
            # ocupar a vaga única de um worker nem autorizar uma lease.
            worker_token = _token_normalizado(registro.get("worker_token"))
            owner = _token_normalizado(registro.get("owner"))
            if worker_token is None:
                worker_token = owner
            if owner is None:
                owner = worker_token
            if worker_token and owner and worker_token != owner:
                owner = worker_token
                erros.append("worker_token e owner divergentes")

            # Leases da versão antiga não têm dono verificável. Eles não podem
            # permanecer bloqueando a fila após a migração.
            if reservada is not None and not worker_token:
                reservada = None
                erros.append("lease legado sem worker_token")
            if status == STATUS_CONCLUIDO and (worker_token or reservada):
                worker_token = None
                owner = None
                reservada = None

            if erros:
                erro = registro.get("erro")
                for detalhe in erros:
                    erro = self._erro_de_migracao(erro, detalhe)
                if status not in (STATUS_PENDENTE, STATUS_RETRY):
                    status = STATUS_PENDENTE
            else:
                erro = registro.get("erro")

            self.conexao.execute(
                """UPDATE tarefas_paginacao
                   SET fonte = ?, parametros_json = ?, pagina = ?,
                       tamanho_pagina = ?, status = ?, tentativas = ?, erro = ?,
                       proxima_tentativa_em = ?, reservada_ate = ?,
                       criada_em = ?, atualizada_em = ?, worker_token = ?,
                       owner = ?
                 WHERE rowid = ?""",
                (
                    fonte,
                    parametros_json,
                    pagina,
                    tamanho,
                    status,
                    tentativas,
                    erro,
                    proxima,
                    reservada,
                    criada,
                    atualizada,
                    worker_token,
                    owner,
                    rowid,
                ),
            )
            preparados.append(
                {
                    "rowid": rowid,
                    "id": registro.get("id"),
                    "natural": (fonte, parametros_json, pagina, tamanho),
                }
            )

        # O menor id (e, na falta dele, o menor rowid) é o sobrevivente. Isso
        # torna a escolha reproduzível entre reaberturas e processos.
        def ordem(registro: Mapping[str, Any]) -> tuple[int, int, int]:
            try:
                identificador = int(registro.get("id"))
            except (TypeError, ValueError):
                return (1, int(registro["rowid"]), int(registro["rowid"]))
            return (0, identificador, int(registro["rowid"]))

        vistos_naturais: set[tuple[Any, ...]] = set()
        for registro in sorted(preparados, key=ordem):
            natural = tuple(registro["natural"])
            if natural in vistos_naturais:
                self.conexao.execute(
                    "DELETE FROM tarefas_paginacao WHERE rowid = ?",
                    (registro["rowid"],),
                )
            else:
                vistos_naturais.add(natural)

        restantes = self.conexao.execute(
            "SELECT rowid AS _rowid, * FROM tarefas_paginacao"
        ).fetchall()
        restantes_ordenadas = sorted(
            (dict(linha) for linha in restantes),
            key=lambda registro: ordem(
                {"id": registro.get("id"), "rowid": registro["_rowid"]}
            ),
        )

        # Tabelas legadas sem id recebem ids estáveis; ids repetidos também são
        # corrigidos antes do índice único.
        ids_usados: set[int] = set()
        ids_validos = []
        for registro in restantes_ordenadas:
            try:
                ids_validos.append(int(registro.get("id")))
            except (TypeError, ValueError):
                pass
        proximo_id = max(ids_validos or [0]) + 1
        for registro in restantes_ordenadas:
            try:
                identificador = int(registro.get("id"))
                id_valido = True
            except (TypeError, ValueError):
                identificador = -1
                id_valido = False
            if (
                not id_valido
                or identificador in ids_usados
                or registro.get("id") is None
            ):
                while proximo_id in ids_usados:
                    proximo_id += 1
                identificador = proximo_id
                proximo_id += 1
                self.conexao.execute(
                    "UPDATE tarefas_paginacao SET id = ? WHERE rowid = ?",
                    (identificador, registro["_rowid"]),
                )
            ids_usados.add(identificador)

        # Coloque chaves temporárias primeiro para funcionar inclusive quando
        # a tabela antiga já possuía UNIQUE(chave). Preserve, porém, as chaves
        # explícitas antes de fazer essa troca.
        restantes = self.conexao.execute(
            "SELECT rowid AS _rowid, * FROM tarefas_paginacao"
        ).fetchall()
        chaves_originais = {
            linha["_rowid"]: str(linha["chave"] or "").strip()
            for linha in restantes
        }
        for linha in restantes:
            temporaria = f"__licita_migracao__{linha['_rowid']}"
            self.conexao.execute(
                "UPDATE tarefas_paginacao SET chave = ? WHERE rowid = ?",
                (temporaria, linha["_rowid"]),
            )

        chaves_usadas: set[str] = set()
        for linha in sorted(
            (dict(item) for item in restantes),
            key=lambda registro: ordem(
                {"id": registro.get("id"), "rowid": registro["_rowid"]}
            ),
        ):
            fonte = str(linha.get("fonte") or "")
            try:
                parametros = json.loads(linha.get("parametros_json"))
                if not isinstance(parametros, Mapping):
                    parametros = {}
            except (TypeError, ValueError, json.JSONDecodeError):
                parametros = {}
            pagina, pagina_ok = inteiro(linha.get("pagina"), 1)
            if not pagina_ok:
                pagina = 1
            tamanho_valor = linha.get("tamanho_pagina")
            tamanho = None if tamanho_valor is None else int(tamanho_valor)
            natural = self.chave_tarefa_paginacao(
                fonte, parametros, pagina, tamanho
            )
            chave_original = chaves_originais[linha["_rowid"]]
            chave = chave_original or natural
            if chave in chaves_usadas:
                chave = natural
            if chave in chaves_usadas:
                chave = f"{natural}:legacy:{linha['_rowid']}"
                while chave in chaves_usadas:
                    chave += "_"
            chaves_usadas.add(chave)
            self.conexao.execute(
                "UPDATE tarefas_paginacao SET chave = ? WHERE rowid = ?",
                (chave, linha["_rowid"]),
            )

        # Tokens duplicados ou sem lease não podem formar dois donos. O menor
        # id conserva o token; os demais voltam à fila com erro explícito.
        tokens: dict[str, int] = {}
        for linha in self.conexao.execute(
            "SELECT rowid AS _rowid, id, status, worker_token, reservada_ate, erro "
            "FROM tarefas_paginacao ORDER BY id, rowid"
        ).fetchall():
            token = linha["worker_token"]
            if not token:
                continue
            if token in tokens or linha["reservada_ate"] is None:
                erro = linha["erro"]
                detalhe = (
                    "worker_token duplicado"
                    if token in tokens
                    else "worker_token sem lease"
                )
                erro = self._erro_de_migracao(erro, detalhe)
                self.conexao.execute(
                    """UPDATE tarefas_paginacao
                       SET worker_token = NULL, owner = NULL,
                           reservada_ate = NULL, status = ?, erro = ?
                       WHERE rowid = ?""",
                    (
                        STATUS_RETRY
                        if linha["status"] == STATUS_RETRY
                        else STATUS_PENDENTE,
                        erro,
                        linha["_rowid"],
                    ),
                )
            else:
                tokens[str(token)] = int(linha["id"])

    def close(self) -> None:
        self.conexao.close()

    def __enter__(self) -> "EstadoColeta":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def agora() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def chave_resposta(fonte: str, parametros: dict[str, Any]) -> str:
        return f"{fonte}:{json.dumps(parametros, sort_keys=True, ensure_ascii=False)}"

    @staticmethod
    def _identidade_resultado_ocr(
        sha256_original: str,
        idioma: str,
        pipeline_version: str,
        configuracao: Mapping[str, Any],
    ) -> tuple[str, str, str, str, str]:
        sha256 = str(sha256_original).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("sha256_original deve ser um SHA-256 hexadecimal")
        idioma_normalizado = str(idioma).strip().lower()
        if not idioma_normalizado:
            raise ValueError("idioma OCR não pode ser vazio")
        versao = str(pipeline_version).strip()
        if not versao:
            raise ValueError("pipeline_version OCR não pode ser vazio")
        if not isinstance(configuracao, Mapping):
            raise ValueError("configuração OCR deve ser um objeto")
        try:
            configuracao_json = json.dumps(
                dict(configuracao),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            carregada = json.loads(configuracao_json)
        except (TypeError, ValueError, json.JSONDecodeError) as erro:
            raise ValueError("configuração OCR deve ser JSON válido") from erro
        if not isinstance(carregada, dict):
            raise ValueError("configuração OCR deve ser um objeto")
        material = json.dumps(
            [sha256, idioma_normalizado, versao, configuracao_json],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        chave = hashlib.sha256(material).hexdigest()
        return sha256, idioma_normalizado, versao, configuracao_json, chave

    @classmethod
    def chave_resultado_ocr(
        cls,
        sha256_original: str,
        idioma: str,
        pipeline_version: str,
        configuracao: Mapping[str, Any],
    ) -> str:
        """Produz a chave determinística de uma execução OCR."""
        return cls._identidade_resultado_ocr(
            sha256_original, idioma, pipeline_version, configuracao
        )[4]

    def obter_resultado_ocr(
        self,
        sha256_original: str,
        idioma: str,
        pipeline_version: str,
        configuracao: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Obtém OCR bem-sucedido sem expiração; corrupção equivale a miss."""
        sha256, idioma, versao, configuracao_json, chave = (
            self._identidade_resultado_ocr(
                sha256_original, idioma, pipeline_version, configuracao
            )
        )
        linha = self.conexao.execute(
            """SELECT chave, resultado_json, texto_sha256, criado_em
                 FROM ocr_resultados
                WHERE sha256_original = ? AND idioma = ?
                  AND pipeline_version = ? AND configuracao_json = ?""",
            (sha256, idioma, versao, configuracao_json),
        ).fetchone()
        if linha is None or linha[0] != chave or _datetime_utc(linha[3]) is None:
            return None
        try:
            resultado = json.loads(linha[1])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(resultado, dict):
            return None
        texto = resultado.get("texto")
        if not isinstance(texto, str):
            return None
        texto_sha256 = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", str(linha[2] or "")):
            return None
        if not secrets.compare_digest(texto_sha256, str(linha[2])):
            return None
        return resultado

    # Nome curto mantido como alias da operação pública de obtenção.
    resultado_ocr = obter_resultado_ocr

    def salvar_resultado_ocr(
        self,
        sha256_original: str,
        idioma: str,
        pipeline_version: str,
        configuracao: Mapping[str, Any],
        resultado: Mapping[str, Any] | None = None,
        *,
        texto: str | None = None,
        metadados: Mapping[str, Any] | None = None,
        criado_em: Any = None,
        agora: Any = None,
    ) -> str:
        """Persiste somente um resultado OCR derivado e devolve sua chave.

        O chamador decide se a execução foi bem-sucedida. Falhas operacionais
        não devem chamar este método e, portanto, nunca viram acertos eternos.
        """
        sha256, idioma, versao, configuracao_json, chave = (
            self._identidade_resultado_ocr(
                sha256_original, idioma, pipeline_version, configuracao
            )
        )
        if resultado is None:
            if texto is None:
                raise ValueError("resultado OCR deve conter texto")
            payload: dict[str, Any] = {"texto": texto}
            if metadados is not None:
                if not isinstance(metadados, Mapping):
                    raise ValueError("metadados OCR devem ser um objeto")
                payload["metadados"] = dict(metadados)
        else:
            if not isinstance(resultado, Mapping):
                raise ValueError("resultado OCR deve ser um objeto")
            payload = dict(resultado)
            if texto is not None:
                payload["texto"] = texto
        texto_derivado = payload.get("texto")
        if not isinstance(texto_derivado, str):
            raise ValueError("resultado OCR deve conter texto textual")
        try:
            resultado_json = json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            json.loads(resultado_json)
        except (TypeError, ValueError, json.JSONDecodeError) as erro:
            raise ValueError("resultado OCR deve ser JSON válido") from erro
        instante = criado_em if criado_em is not None else agora
        timestamp = _texto_instante(instante if instante is not None else self.agora())
        texto_sha256 = hashlib.sha256(texto_derivado.encode("utf-8")).hexdigest()
        self.conexao.execute(
            """INSERT INTO ocr_resultados
                   (sha256_original, idioma, pipeline_version,
                    configuracao_json, chave, resultado_json,
                    texto_sha256, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sha256_original, idioma, pipeline_version,
                           configuracao_json) DO UPDATE SET
                   chave = excluded.chave,
                   resultado_json = excluded.resultado_json,
                   texto_sha256 = excluded.texto_sha256,
                   criado_em = excluded.criado_em""",
            (
                sha256,
                idioma,
                versao,
                configuracao_json,
                chave,
                resultado_json,
                texto_sha256,
                timestamp,
            ),
        )
        self.conexao.commit()
        return chave

    # ------------------------------------------------------------------ cache
    def resposta(
        self,
        chave: str,
        ttl_segundos: float | timedelta | None | object = _MISSING,
        *,
        ttl_vazio_segundos: float | timedelta | None | object = _MISSING,
        agora: Any = None,
        ttl: float | timedelta | None | object = _MISSING,
        ttl_vazio: float | timedelta | None | object = _MISSING,
    ) -> Any | None:
        """Retorna uma resposta ainda válida ou ``None`` em cache miss.

        Respostas vazias têm um TTL próprio, curto por padrão.  Isso evita que
        uma página vazia causada por indisponibilidade momentânea seja tratada
        como prova permanente de que não existem resultados.  O valor vazio,
        enquanto fresco, continua sendo retornado exatamente como foi salvo;
        assim a API original do coletor não muda.
        """
        if ttl is not _MISSING:
            ttl_segundos = ttl
        if ttl_vazio is not _MISSING:
            ttl_vazio_segundos = ttl_vazio

        linha = self.conexao.execute(
            """SELECT payload, atualizada_em, ttl_segundos,
                      ttl_vazio_segundos, payload_vazio
                 FROM respostas WHERE chave = ?""",
            (chave,),
        ).fetchone()
        if linha is None:
            return None
        try:
            payload = json.loads(linha[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            # Uma resposta corrompida não deve impedir a retomada nem ser
            # confundida com um resultado válido.
            return None

        vazio = bool(linha[4]) or _payload_vazio(payload)
        if ttl_segundos is _MISSING:
            ttl_normal = linha[2]
            if ttl_normal is None:
                ttl_normal = self.cache_ttl_segundos
        else:
            ttl_normal = ttl_segundos
        if ttl_vazio_segundos is _MISSING:
            ttl_vazio = linha[3]
            if ttl_vazio is None:
                ttl_vazio = self.cache_ttl_vazio_segundos
        else:
            ttl_vazio = ttl_vazio_segundos
        ttl_usado = _ttl_segundos(ttl_vazio if vazio else ttl_normal)
        if not self._cache_dentro_do_ttl(linha[1], ttl_usado, agora=agora):
            return None
        return payload

    def _cache_dentro_do_ttl(
        self, atualizada_em: Any, ttl: float | None, *, agora: Any = None
    ) -> bool:
        # Mesmo uma entrada sem expiração precisa ter um timestamp legível;
        # caso contrário não há como distinguir dado antigo de corrupção.
        salvo = _datetime_utc(atualizada_em)
        if salvo is None:
            return False
        if ttl is None:
            return True
        momento = _datetime_utc(agora)
        if momento is None:
            momento = _datetime_utc(self.agora())
        if salvo is None or momento is None:
            # Timestamp ilegível é tratado como expirado; nunca se deve
            # reutilizar silenciosamente uma resposta cuja idade não sabemos.
            return False
        idade = (momento - salvo).total_seconds()
        # Relógio atrasado não invalida uma entrada recém-gravada.  ``ttl=0``
        # continua expirando no mesmo instante.
        return idade < ttl if idade >= 0 else True

    def salvar_resposta(
        self,
        chave: str,
        payload: Any,
        *,
        atualizada_em: Any = None,
        agora: Any = None,
        ttl_segundos: float | timedelta | None = None,
        ttl_vazio_segundos: float | timedelta | None = None,
        ttl: float | timedelta | None = None,
        ttl_vazio: float | timedelta | None = None,
    ) -> None:
        """Persiste uma resposta e, opcionalmente, seus TTLs específicos."""
        if ttl is not None:
            ttl_segundos = ttl
        if ttl_vazio is not None:
            ttl_vazio_segundos = ttl_vazio
        ttl_normal = _ttl_segundos(ttl_segundos)
        ttl_vazio_normal = _ttl_segundos(ttl_vazio_segundos)
        instante = atualizada_em if atualizada_em is not None else agora
        if instante is None:
            instante = self.agora()
        atualizada = _texto_instante(instante)
        vazio = int(_payload_vazio(payload))
        self.conexao.execute(
            """INSERT INTO respostas
                   (chave, payload, atualizada_em, ttl_segundos,
                    ttl_vazio_segundos, payload_vazio)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(chave) DO UPDATE SET
                   payload = excluded.payload,
                   atualizada_em = excluded.atualizada_em,
                   ttl_segundos = excluded.ttl_segundos,
                   ttl_vazio_segundos = excluded.ttl_vazio_segundos,
                   payload_vazio = excluded.payload_vazio""",
            (
                chave,
                _json(payload),
                atualizada,
                ttl_normal,
                ttl_vazio_normal,
                vazio,
            ),
        )
        self.conexao.commit()

    def resposta_expirada(
        self,
        chave: str,
        ttl_segundos: float | timedelta | None | object = _MISSING,
        *,
        ttl_vazio_segundos: float | timedelta | None | object = _MISSING,
        agora: Any = None,
        ttl: float | timedelta | None | object = _MISSING,
        ttl_vazio: float | timedelta | None | object = _MISSING,
    ) -> bool:
        """Informa se existe uma resposta mas ela não pode mais ser usada."""
        if ttl is not _MISSING:
            ttl_segundos = ttl
        if ttl_vazio is not _MISSING:
            ttl_vazio_segundos = ttl_vazio
        linha = self.conexao.execute(
            "SELECT payload, atualizada_em, ttl_segundos, ttl_vazio_segundos, payload_vazio FROM respostas WHERE chave = ?",
            (chave,),
        ).fetchone()
        if linha is None:
            return False
        try:
            payload = json.loads(linha[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            return True
        vazio = bool(linha[4]) or _payload_vazio(payload)
        ttl = ttl_vazio_segundos if vazio else ttl_segundos
        if ttl is _MISSING:
            ttl = linha[3] if vazio else linha[2]
            if ttl is None:
                ttl = self.cache_ttl_vazio_segundos if vazio else self.cache_ttl_segundos
        return not self._cache_dentro_do_ttl(
            linha[1], _ttl_segundos(ttl), agora=agora
        )

    # ------------------------------------------------------------- orçamento
    def requisicoes_invalidas(self) -> list[dict[str, Any]]:
        """Retorna as linhas legadas que impediram uma migração segura.

        A presença de qualquer linha mantém o orçamento finito bloqueado. A
        aplicação pode exportar esta lista, corrigir a origem e remover os
        registros auditados explicitamente; a inicialização nunca os apaga.
        """
        linhas = self.conexao.execute(
            """SELECT id, rowid_legado, dia_utc_original,
                      quantidade_original, motivo, auditada_em
                 FROM requisicoes_invalidas ORDER BY id"""
        ).fetchall()
        self._requisicoes_migracao_insegura = bool(linhas)
        return [dict(linha) for linha in linhas]

    def auditoria_requisicoes(self) -> list[dict[str, Any]]:
        """Alias explícito para consumidores que chamam o registro de auditoria."""
        return self.requisicoes_invalidas()

    def tem_requisicoes_invalidas(self) -> bool:
        return bool(self.requisicoes_invalidas())

    def reservar_requisicao(
        self,
        dia_utc: Any = None,
        *,
        agora: Any = None,
        margem: int | None = None,
    ) -> int:
        """Reserva uma chamada antes de ela sair para a internet.

        O contador é por dia UTC e inclui retentativas. Assim, uma execução
        retomada não ultrapassa silenciosamente o orçamento configurado.  A
        margem, quando informada, mantém esse número de chamadas disponível
        para uma fase posterior da execução; por padrão ela é zero, mantendo o
        comportamento original.
        """
        dia = _dia_utc(
            dia_utc, agora=agora if agora is not None else self.agora()
        )
        margem_usada = (
            self.margem_requisicoes
            if margem is None
            else _inteiro_nao_negativo(margem, "margem")
        )
        if self.max_requisicoes_dia > 0 and self.tem_requisicoes_invalidas():
            raise LimiteRequisicoes(
                "orçamento bloqueado: há requisições legadas inválidas "
                "pendentes de auditoria"
            )
        # A margem faz parte da mesma transação/UPDATE da reserva. A leitura
        # de saldo é apenas informativa e não participa da decisão, evitando
        # que duas conexões passem simultaneamente pelo mesmo saldo.
        with self.conexao:
            self.conexao.execute("BEGIN IMMEDIATE")
            self.conexao.execute(
                "INSERT OR IGNORE INTO requisicoes (dia_utc, quantidade) VALUES (?, 0)",
                (dia,),
            )
            limite_efetivo = self.max_requisicoes_dia - margem_usada
            cursor = self.conexao.execute(
                """UPDATE requisicoes
                      SET quantidade = quantidade + 1
                    WHERE dia_utc = ?
                      AND (? <= 0 OR quantidade < ?)""",
                (dia, self.max_requisicoes_dia, limite_efetivo),
            )
            if cursor.rowcount != 1:
                raise LimiteRequisicoes(
                    f"orçamento de {self.max_requisicoes_dia} requisições/dia atingido"
                )
            linha = self.conexao.execute(
                "SELECT quantidade FROM requisicoes WHERE dia_utc = ?", (dia,)
            ).fetchone()
            novas = int(linha[0]) if linha else 0
        return novas

    def requisicoes_hoje(self, dia_utc: Any = None, *, agora: Any = None) -> int:
        dia = _dia_utc(
            dia_utc, agora=agora if agora is not None else self.agora()
        )
        linha = self.conexao.execute(
            "SELECT quantidade FROM requisicoes WHERE dia_utc = ?", (dia,)
        ).fetchone()
        return int(linha[0]) if linha else 0

    def saldo_requisicoes(
        self,
        dia_utc: Any = None,
        *,
        agora: Any = None,
        margem: int | None = 0,
    ) -> int | None:
        """Retorna o saldo disponível; ``None`` representa orçamento ilimitado."""
        margem_normal = _inteiro_nao_negativo(
            self.margem_requisicoes if margem is None else margem, "margem"
        )
        if self.max_requisicoes_dia <= 0:
            return None
        if self.tem_requisicoes_invalidas():
            # Não sabemos em qual dia uma linha inválida incidiu. Zero é a
            # única resposta segura para não liberar orçamento por engano.
            return 0
        return max(
            0,
            self.max_requisicoes_dia
            - margem_normal
            - self.requisicoes_hoje(dia_utc, agora=agora),
        )

    def saldo_orcamento(
        self, dia_utc: Any = None, *, agora: Any = None, margem: int | None = 0
    ) -> int | None:
        return self.saldo_requisicoes(dia_utc, agora=agora, margem=margem)

    def saldo_disponivel(
        self, dia_utc: Any = None, *, agora: Any = None, margem: int | None = 0
    ) -> int | None:
        return self.saldo_requisicoes(dia_utc, agora=agora, margem=margem)

    def saldo(self, dia_utc: Any = None, *, agora: Any = None) -> int | None:
        return self.saldo_requisicoes(dia_utc, agora=agora)

    def requisicoes_restantes(
        self, dia_utc: Any = None, *, agora: Any = None, margem: int | None = 0
    ) -> int | None:
        return self.saldo_requisicoes(dia_utc, agora=agora, margem=margem)

    def margem_orcamento(
        self,
        dia_utc: Any = None,
        *,
        agora: Any = None,
        margem: int | None = None,
    ) -> int | None:
        """Saldo respeitando a margem configurada para novas reservas."""
        return self.saldo_requisicoes(
            dia_utc,
            agora=agora,
            margem=self.margem_requisicoes if margem is None else margem,
        )

    def margem_disponivel(
        self, dia_utc: Any = None, *, agora: Any = None, margem: int | None = None
    ) -> int | None:
        return self.margem_orcamento(dia_utc, agora=agora, margem=margem)

    def margem(self, dia_utc: Any = None, *, agora: Any = None) -> int | None:
        return self.margem_orcamento(dia_utc, agora=agora)

    def pode_reservar_requisicao(
        self,
        quantidade: int = 1,
        dia_utc: Any = None,
        *,
        agora: Any = None,
        margem: int | None = None,
    ) -> bool:
        quantidade_normal = _inteiro_nao_negativo(quantidade, "quantidade")
        margem_normal = (
            self.margem_requisicoes
            if margem is None
            else _inteiro_nao_negativo(margem, "margem")
        )
        if self.max_requisicoes_dia > 0 and self.tem_requisicoes_invalidas():
            return False
        saldo = self.saldo_requisicoes(
            dia_utc, agora=agora, margem=margem_normal
        )
        return saldo is None or saldo >= quantidade_normal

    def orcamento(self, dia_utc: Any = None, *, agora: Any = None) -> dict[str, Any]:
        dia = _dia_utc(
            dia_utc, agora=agora if agora is not None else self.agora()
        )
        usadas = self.requisicoes_hoje(dia)
        saldo = self.saldo_requisicoes(dia)
        return {
            "dia_utc": dia,
            "limite": None if self.max_requisicoes_dia <= 0 else self.max_requisicoes_dia,
            "usadas": usadas,
            "saldo": saldo,
            "margem": self.margem_orcamento(dia),
        }

    # ------------------------------------------------------------ inspeções
    def _versao_salva(self, policy_version: str | int | None) -> str:
        if policy_version is None:
            return self.policy_version
        texto = str(policy_version).strip()
        return texto or self.policy_version

    def _linha_inspecao(
        self, numero: str, policy_version: str | int | None | object
    ) -> sqlite3.Row | None:
        parametros: list[Any] = [numero]
        sql = "SELECT * FROM inspecoes WHERE numero_controle_pncp = ?"
        if policy_version is not None:
            sql += " AND policy_version = ?"
            parametros.append(str(policy_version).strip())
        sql += " ORDER BY atualizada_em DESC, rowid DESC LIMIT 1"
        return self.conexao.execute(sql, parametros).fetchone()

    def status_inspecao(
        self,
        numero: str,
        policy_version: str | int | None | object = _MISSING,
    ) -> str | None:
        """Retorna o status da versão solicitada.

        A versão omitida é a política ativa. ``None`` explícito significa sem
        filtro e escolhe a inspeção mais recente, contrato escalar que mantém
        compatibilidade sem escolher aleatoriamente entre v1 e v2.
        """
        versao = self.policy_version if policy_version is _MISSING else policy_version
        linha = self._linha_inspecao(numero, versao)
        return None if linha is None else str(linha["status"])

    def inspecao(
        self,
        numero: str,
        policy_version: str | int | None | object = _MISSING,
    ) -> dict[str, Any] | None:
        """Retorna a inspeção da política ativa ou a mais recente sem filtro."""
        versao = self.policy_version if policy_version is _MISSING else policy_version
        linha = self._linha_inspecao(numero, versao)
        if linha is None:
            return None
        resultado = dict(linha)
        for coluna in ("compra_json", "arquivos_json", "candidato_json"):
            valor = resultado.get(coluna)
            if valor is not None:
                try:
                    resultado[coluna[:-5]] = json.loads(valor)
                except (TypeError, ValueError, json.JSONDecodeError):
                    resultado[coluna[:-5]] = None
        return resultado

    def salvar_inspecao(
        self,
        numero: str,
        compra: dict[str, Any],
        *,
        status: str,
        motivo: str | None = None,
        arquivos: list[dict[str, Any]] | None = None,
        candidato: dict[str, Any] | None = None,
        policy_version: str | int | None = None,
        atualizada_em: Any = None,
        agora: Any = None,
    ) -> None:
        versao = self._versao_salva(policy_version)
        instante = atualizada_em if atualizada_em is not None else agora
        if instante is None:
            instante = self.agora()
        self.conexao.execute(
            """INSERT INTO inspecoes
               (numero_controle_pncp, status, motivo, compra_json, arquivos_json,
                candidato_json, atualizada_em, policy_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(numero_controle_pncp, policy_version) DO UPDATE SET
                   status = excluded.status,
                   motivo = excluded.motivo,
                   compra_json = excluded.compra_json,
                   arquivos_json = excluded.arquivos_json,
                   candidato_json = excluded.candidato_json,
                   atualizada_em = excluded.atualizada_em""",
            (
                numero,
                status,
                motivo,
                _json(compra),
                _json(arquivos) if arquivos is not None else None,
                _json(candidato) if candidato is not None else None,
                _texto_instante(instante),
                versao,
            ),
        )
        self.conexao.commit()

    def ja_processado(
        self, numero: str, policy_version: str | int | None | object = _MISSING
    ) -> bool:
        """Indica se a inspeção pode ser reutilizada.

        A versão omitida precisa pertencer à política configurada na
        instância. ``None`` explícito consulta a inspeção mais recente de
        qualquer versão.
        """
        versao = self.policy_version if policy_version is _MISSING else policy_version
        return self.status_inspecao(numero, versao) is not None

    def inspecao_compativel(self, numero: str) -> bool:
        return self.ja_processado(numero, self.policy_version)

    def salvar_aceito(
        self,
        candidato: dict[str, Any],
        documentos: list[dict[str, Any]],
        *,
        policy_version: str | int | None = None,
        versao_politica: str | int | None | object = _MISSING,
        aceito_em: Any = None,
        agora: Any = None,
    ) -> None:
        """Persiste um aceite associado à política que o produziu."""
        if versao_politica is not _MISSING:
            policy_version = versao_politica
        versao = self._versao_salva(policy_version)
        numero = candidato["numero_controle_pncp"]
        instante = aceito_em if aceito_em is not None else agora
        if instante is None:
            instante = self.agora()
        self.conexao.execute(
            """INSERT INTO aceitos
               (numero_controle_pncp, candidato_json, documentos_json,
                aceito_em, policy_version)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(numero_controle_pncp, policy_version) DO UPDATE SET
                   candidato_json = excluded.candidato_json,
                   documentos_json = excluded.documentos_json,
                   aceito_em = excluded.aceito_em""",
            (
                numero,
                _json(candidato),
                _json(documentos),
                _texto_instante(instante),
                versao,
            ),
        )
        self.conexao.commit()

    def aceitos(
        self,
        policy_version: str | int | None | object = _MISSING,
        *,
        versao_politica: str | int | None | object = _MISSING,
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """Consulta aceites da política ativa.

        Omitir a versão usa a política da instância. ``None`` explícito
        retorna todas as versões e mantém a API legada disponível quando a
        política for trocada.
        """
        if versao_politica is not _MISSING:
            policy_version = versao_politica
        versao = self.policy_version if policy_version is _MISSING else policy_version
        sql = (
            "SELECT candidato_json, documentos_json FROM aceitos"
            " WHERE 1 = 1"
        )
        parametros: list[Any] = []
        if versao is not None:
            sql += " AND policy_version = ?"
            parametros.append(str(versao).strip())
        sql += " ORDER BY aceito_em, rowid"
        linhas = self.conexao.execute(sql, parametros)
        return [
            (json.loads(linha[0]), json.loads(linha[1]))
            for linha in linhas
        ]

    def numeros_aceitos(
        self,
        policy_version: str | int | None | object = _MISSING,
        *,
        versao_politica: str | int | None | object = _MISSING,
    ) -> set[str]:
        if versao_politica is not _MISSING:
            policy_version = versao_politica
        return {
            c["numero_controle_pncp"]
            for c, _ in self.aceitos(policy_version)
        }

    def aceito(
        self,
        numero: str,
        policy_version: str | int | None | object = _MISSING,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        versao = self.policy_version if policy_version is _MISSING else policy_version
        parametros: list[Any] = [numero]
        sql = (
            "SELECT candidato_json, documentos_json FROM aceitos "
            "WHERE numero_controle_pncp = ?"
        )
        if versao is not None:
            sql += " AND policy_version = ?"
            parametros.append(str(versao).strip())
        # A API plural com None retorna todas; a API escalar escolhe o mais
        # recente para não depender da ordem física do banco.
        sql += " ORDER BY aceito_em DESC, rowid DESC LIMIT 1"
        linha = self.conexao.execute(sql, parametros).fetchone()
        if linha is None:
            return None
        return json.loads(linha[0]), json.loads(linha[1])

    def obter_aceito(
        self,
        numero: str,
        policy_version: str | int | None | object = _MISSING,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        return self.aceito(numero, policy_version)

    def reprovados(
        self, policy_version: str | int | None | object = _MISSING
    ) -> list[dict[str, str]]:
        versao = self.policy_version if policy_version is _MISSING else policy_version
        sql = """SELECT numero_controle_pncp, motivo FROM inspecoes
                  WHERE status IN ('SEM_PAR_ETP_TR', 'SEM_CADEIA_COMPLETA',
                                   'DOWNLOAD_REPROVADO', 'FORA_DO_ESCOPO',
                                   'LIMITE_ORGAO', 'ERRO_API')"""
        parametros: list[Any] = []
        if versao is not None:
            sql += " AND policy_version = ?"
            parametros.append(str(versao).strip())
        sql += " ORDER BY atualizada_em, rowid"
        linhas = self.conexao.execute(sql, parametros)
        return [
            {
                "numero_controle_pncp": str(linha[0]),
                "motivo": str(linha[1] or "sem motivo registrado"),
            }
            for linha in linhas
        ]

    # ------------------------------------------------------- tarefas de página
    @staticmethod
    def chave_tarefa_paginacao(
        fonte: str,
        parametros: Mapping[str, Any] | None,
        pagina: int,
        tamanho_pagina: int | None = None,
    ) -> str:
        pagina_normal = _inteiro_nao_negativo(pagina, "pagina")
        tamanho_normal = (
            None
            if tamanho_pagina is None
            else _inteiro_nao_negativo(tamanho_pagina, "tamanho_pagina")
        )
        return "pagina:" + _json_parametros(
            {
                "fonte": str(fonte),
                "parametros": dict(parametros or {}),
                "pagina": pagina_normal,
                "tamanho_pagina": tamanho_normal,
            }
        )

    @staticmethod
    def _status_tarefa(status: str) -> str:
        valor = str(status).upper()
        if valor not in STATUS_TAREFAS_PAGINACAO:
            permitidos = ", ".join(sorted(STATUS_TAREFAS_PAGINACAO))
            raise ValueError(f"status de tarefa inválido; use {permitidos}")
        return valor

    def _tarefa_dict(self, linha: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        resultado = dict(linha)
        parametros_json = resultado.get("parametros_json")
        try:
            resultado["parametros"] = (
                json.loads(parametros_json) if parametros_json is not None else {}
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            resultado["parametros"] = {}
        # O alias sem sufixo facilita o uso por consumidores que não trabalham
        # diretamente com o schema SQL.
        resultado["proxima_tentativa"] = resultado.get("proxima_tentativa_em")
        resultado["lease_ate"] = resultado.get("reservada_ate")
        resultado["task_id"] = resultado.get("id")
        worker_token = _token_normalizado(resultado.get("worker_token"))
        owner = _token_normalizado(resultado.get("owner"))
        token = worker_token or owner
        resultado["worker_token"] = token
        resultado["owner"] = token
        # ``token`` é um alias de compatibilidade; o nome documentado é
        # worker_token.
        resultado["token"] = token
        return resultado

    def _identificador_tarefa(self, identificador: Any) -> tuple[str, Any]:
        if isinstance(identificador, Mapping):
            if identificador.get("id") is not None:
                return "id", int(identificador["id"])
            if identificador.get("task_id") is not None:
                return "id", int(identificador["task_id"])
            if identificador.get("chave") is not None:
                return "chave", str(identificador["chave"])
            raise ValueError("tarefa deve conter id ou chave")
        if isinstance(identificador, bool):
            raise ValueError("identificador de tarefa inválido")
        if isinstance(identificador, int):
            return "id", identificador
        return "chave", str(identificador)

    def _buscar_tarefa(self, identificador: Any) -> sqlite3.Row | None:
        coluna, valor = self._identificador_tarefa(identificador)
        return self.conexao.execute(
            f"SELECT * FROM tarefas_paginacao WHERE {coluna} = ?", (valor,)
        ).fetchone()

    def criar_tarefa_paginacao(
        self,
        fonte: str | None = None,
        parametros: Mapping[str, Any] | None = None,
        pagina: int | None = None,
        *,
        tamanho_pagina: int | None = None,
        tamanho: int | None = None,
        chave: str | None = None,
        status: str = STATUS_PENDENTE,
        tentativas: int = 0,
        erro: str | None = None,
        proxima_tentativa_em: Any = None,
        proxima_tentativa: Any = None,
        agora: Any = None,
        params: Mapping[str, Any] | None = None,
        parametros_json: str | None = None,
    ) -> dict[str, Any]:
        """Cria uma tarefa idempotente para uma página de uma fonte.

        A chave natural inclui fonte, parâmetros, página e tamanho.  Repetir a
        chamada retorna a tarefa existente sem zerar tentativas, erro ou
        estado, o que é essencial para retomadas.
        """
        if parametros is None and params is not None:
            parametros = params
        if parametros is None and parametros_json is not None:
            try:
                carregados = json.loads(parametros_json)
            except (TypeError, ValueError, json.JSONDecodeError) as erro_json:
                raise ValueError("parametros_json inválido") from erro_json
            if not isinstance(carregados, Mapping):
                raise ValueError("parametros_json deve conter um objeto JSON")
            parametros = carregados
        parametros_dict = dict(parametros or {})
        if pagina is None:
            pagina = parametros_dict.get("pagina", 1)
        pagina_normal = _inteiro_nao_negativo(pagina, "pagina")
        if tamanho_pagina is None:
            tamanho_pagina = tamanho
        tamanho_normal = (
            None
            if tamanho_pagina is None
            else _inteiro_nao_negativo(tamanho_pagina, "tamanho_pagina")
        )
        fonte_normal = str(fonte or "")
        status_normal = self._status_tarefa(status)
        tentativas_normal = _inteiro_nao_negativo(tentativas, "tentativas")
        if proxima_tentativa is not None:
            proxima_tentativa_em = proxima_tentativa
        proxima = (
            None
            if proxima_tentativa_em is None
            else _texto_instante(proxima_tentativa_em)
        )
        parametros_json_normal = _json_parametros(parametros_dict)
        chave_normal = chave or self.chave_tarefa_paginacao(
            fonte_normal, parametros_dict, pagina_normal, tamanho_normal
        )
        instante = _texto_instante(agora if agora is not None else self.agora())
        with self.conexao:
            # O índice natural e o de chave tornam a criação idempotente; o
            # estado existente nunca é zerado por uma nova descoberta. Um id
            # explícito também mantém utilizável uma tabela legada que recebeu
            # ``id`` por ALTER TABLE e, portanto, não tem AUTOINCREMENT.
            self.conexao.execute("BEGIN IMMEDIATE")
            ids: list[int] = []
            for linha in self.conexao.execute(
                "SELECT id FROM tarefas_paginacao WHERE id IS NOT NULL"
            ):
                try:
                    ids.append(int(linha[0]))
                except (TypeError, ValueError):
                    pass
            novo_id = max(ids or [0]) + 1
            self.conexao.execute(
                """INSERT OR IGNORE INTO tarefas_paginacao
                   (id, chave, fonte, parametros_json, pagina, tamanho_pagina,
                    status, tentativas, erro, proxima_tentativa_em,
                    reservada_ate, criada_em, atualizada_em,
                    worker_token, owner)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)""",
                (
                    novo_id,
                    chave_normal,
                    fonte_normal,
                    parametros_json_normal,
                    pagina_normal,
                    tamanho_normal,
                    status_normal,
                    tentativas_normal,
                    erro,
                    proxima,
                    instante,
                    instante,
                ),
            )
        linha = self._buscar_tarefa(chave_normal)
        if linha is None:
            linha = self.conexao.execute(
                """SELECT * FROM tarefas_paginacao
                   WHERE fonte = ? AND parametros_json = ? AND pagina = ?
                     AND COALESCE(tamanho_pagina, -1) = COALESCE(?, -1)
                   ORDER BY id LIMIT 1""",
                (
                    fonte_normal,
                    parametros_json_normal,
                    pagina_normal,
                    tamanho_normal,
                ),
            ).fetchone()
        if linha is None:  # pragma: no cover - só seria possível com corrupção externa
            raise RuntimeError("não foi possível persistir tarefa de paginação")
        return self._tarefa_dict(linha)

    def salvar_tarefa_paginacao(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.criar_tarefa_paginacao(*args, **kwargs)

    def adicionar_tarefa_paginacao(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.criar_tarefa_paginacao(*args, **kwargs)

    def agendar_tarefa_paginacao(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.criar_tarefa_paginacao(*args, **kwargs)

    def criar_tarefa_pagina(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.criar_tarefa_paginacao(*args, **kwargs)

    def tarefa_paginacao(self, identificador: Any) -> dict[str, Any] | None:
        linha = self._buscar_tarefa(identificador)
        return None if linha is None else self._tarefa_dict(linha)

    def obter_tarefa_paginacao(self, identificador: Any) -> dict[str, Any] | None:
        return self.tarefa_paginacao(identificador)

    def listar_tarefas_paginacao(
        self,
        status: str | Iterable[str] | None = None,
        *,
        prontas: bool = False,
        agora: Any = None,
    ) -> list[dict[str, Any]]:
        parametros: list[Any] = []
        sql = "SELECT * FROM tarefas_paginacao"
        if status is not None:
            if isinstance(status, str):
                estados = [self._status_tarefa(status)]
            else:
                estados = [self._status_tarefa(valor) for valor in status]
            if not estados:
                return []
            sql += " WHERE status IN (" + ",".join("?" for _ in estados) + ")"
            parametros.extend(estados)
        if prontas:
            momento = _texto_instante(agora if agora is not None else self.agora())
            trecho = (
                "status IN ('PENDENTE', 'RETRY') "
                "AND (proxima_tentativa_em IS NULL OR proxima_tentativa_em <= ?) "
                "AND (reservada_ate IS NULL OR reservada_ate <= ?)"
            )
            if " WHERE " in sql:
                sql += " AND " + trecho
            else:
                sql += " WHERE " + trecho
            parametros.extend([momento, momento])
        sql += " ORDER BY id"
        linhas = self.conexao.execute(sql, parametros).fetchall()
        return [self._tarefa_dict(linha) for linha in linhas]

    def tarefas_paginacao(
        self, status: str | Iterable[str] | None = None, *, prontas: bool = False, agora: Any = None
    ) -> list[dict[str, Any]]:
        return self.listar_tarefas_paginacao(status, prontas=prontas, agora=agora)

    def listar_tarefas(
        self, status: str | Iterable[str] | None = None, *, prontas: bool = False, agora: Any = None
    ) -> list[dict[str, Any]]:
        return self.listar_tarefas_paginacao(status, prontas=prontas, agora=agora)

    def tarefas_pendentes(self, *, agora: Any = None) -> list[dict[str, Any]]:
        return self.listar_tarefas_paginacao(
            (STATUS_PENDENTE, STATUS_RETRY), prontas=True, agora=agora
        )

    def proxima_tarefa_paginacao(
        self,
        agora: Any = None,
        *,
        lease_segundos: float | timedelta | None = None,
        identificadores: Iterable[int] | None = None,
    ) -> dict[str, Any] | None:
        """Reivindica atomicamente a próxima página pronta.

        Quando ``identificadores`` é informado, a lease fica restrita ao lote
        solicitado. Isso impede uma consulta de drenar páginas pendentes de
        outra fonte ou estratégia. Cada reivindicação recebe um token novo.
        """
        ids = None
        if identificadores is not None:
            ids = tuple(dict.fromkeys(int(valor) for valor in identificadores))
            if not ids:
                return None
        momento = self._momento(agora)
        momento_texto = momento.isoformat()
        lease = (
            DEFAULT_LEASE_SEGUNDOS
            if lease_segundos is None
            else _ttl_segundos(lease_segundos)
        )
        # ``_ttl_segundos(inf)`` representa ausência de TTL para o cache; para
        # leases isso seria um dono que nunca pode ser recuperado, portanto
        # também usa o padrão seguro.
        if lease is None:
            lease = DEFAULT_LEASE_SEGUNDOS
        reservada = (momento + timedelta(seconds=lease)).isoformat()

        with self.conexao:
            # BEGIN IMMEDIATE torna SELECT + UPDATE uma única reivindicação
            # mesmo com duas conexões/processos no mesmo arquivo.
            self.conexao.execute("BEGIN IMMEDIATE")
            filtro_ids = ""
            parametros: tuple[Any, ...] = (momento_texto, momento_texto)
            if ids is not None:
                filtro_ids = f" AND id IN ({','.join('?' for _ in ids)})"
                parametros += ids
            linha = self.conexao.execute(
                f"""SELECT * FROM tarefas_paginacao
                   WHERE status IN ('PENDENTE', 'RETRY')
                     AND (proxima_tentativa_em IS NULL OR proxima_tentativa_em <= ?)
                     AND (reservada_ate IS NULL OR reservada_ate <= ?)
                     {filtro_ids}
                   ORDER BY COALESCE(proxima_tentativa_em, criada_em), id
                   LIMIT 1""",
                parametros,
            ).fetchone()
            if linha is None:
                return None

            # A aleatoriedade é deliberada: o token identifica esta execução,
            # não a página. A checagem também mantém a garantia se um gerador
            # externo/seeded produzir uma colisão excepcional.
            while True:
                worker_token = secrets.token_urlsafe(32)
                ocupado = self.conexao.execute(
                    "SELECT 1 FROM tarefas_paginacao "
                    "WHERE worker_token = ? OR owner = ? LIMIT 1",
                    (worker_token, worker_token),
                ).fetchone()
                if ocupado is None:
                    break
            self.conexao.execute(
                """UPDATE tarefas_paginacao
                   SET tentativas = tentativas + 1,
                       reservada_ate = ?, atualizada_em = ?,
                       worker_token = ?, owner = ?
                   WHERE id = ?""",
                (
                    reservada,
                    momento_texto,
                    worker_token,
                    worker_token,
                    linha["id"],
                ),
            )
            atualizada = self.conexao.execute(
                "SELECT * FROM tarefas_paginacao WHERE id = ?", (linha["id"],)
            ).fetchone()
        return None if atualizada is None else self._tarefa_dict(atualizada)

    def _momento(self, agora: Any = None) -> datetime:
        if agora is None:
            return datetime.now(timezone.utc)
        momento = _datetime_utc(agora)
        if momento is None:
            raise ValueError("timestamp inválido")
        return momento

    def _token_tarefa(
        self,
        identificador: Any,
        worker_token: Any = None,
        *,
        token: Any = None,
        owner: Any = None,
    ) -> str | None:
        # Valores vazios têm a mesma semântica de NULL também na API. Só
        # depois da normalização tentamos o próximo alias, evitando que um
        # worker_token vazio esconda um owner válido de um registro legado.
        for escolhido in (worker_token, token, owner):
            normalizado = _token_normalizado(escolhido)
            if normalizado is not None:
                return normalizado
        if isinstance(identificador, Mapping):
            for nome in ("worker_token", "owner", "token"):
                normalizado = _token_normalizado(identificador.get(nome))
                if normalizado is not None:
                    return normalizado
        return None

    def _atualizar_tarefa_com_lease(
        self,
        identificador: Any,
        worker_token: str | None,
        momento: datetime,
        atribuicoes: str,
        parametros: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        """Atualiza somente enquanto o token ainda for o dono não expirado."""
        if not worker_token:
            return None
        coluna, valor = self._identificador_tarefa(identificador)
        instante = momento.isoformat()
        with self.conexao:
            cursor = self.conexao.execute(
                f"""UPDATE tarefas_paginacao
                       SET {atribuicoes}
                     WHERE {coluna} = ?
                       AND (worker_token = ?
                            OR (worker_token IS NULL AND owner = ?))
                       AND reservada_ate IS NOT NULL
                       AND reservada_ate > ?""",
                parametros + (valor, worker_token, worker_token, instante),
            )
            if cursor.rowcount != 1:
                return None
            linha = self.conexao.execute(
                f"SELECT * FROM tarefas_paginacao WHERE {coluna} = ?", (valor,)
            ).fetchone()
        return None if linha is None else self._tarefa_dict(linha)

    def concluir_tarefa_paginacao(
        self,
        identificador: Any,
        worker_token: Any = None,
        agora: Any = None,
        *,
        token: Any = None,
        owner: Any = None,
    ) -> dict[str, Any] | None:
        # A API antiga aceitava ``(tarefa, agora)``. Preserve a chamada sem
        # permitir que ela contorne a exigência nova de token.
        if worker_token is not None and _datetime_utc(worker_token) is not None:
            if agora is None:
                # Também reconhece a antiga forma textual ``(tarefa, agora)``;
                # tokens gerados pelo estado não são timestamps ISO.
                agora = worker_token
                worker_token = None
            elif _datetime_utc(agora) is None:
                # Forma de extensão da API antiga: (id, agora, token).
                worker_token, agora = agora, worker_token
        momento = self._momento(agora)
        token_normal = self._token_tarefa(
            identificador, worker_token, token=token, owner=owner
        )
        return self._atualizar_tarefa_com_lease(
            identificador,
            token_normal,
            momento,
            "status = 'CONCLUIDO', erro = NULL, "
            "proxima_tentativa_em = NULL, reservada_ate = NULL, "
            "worker_token = NULL, owner = NULL, atualizada_em = ?",
            (momento.isoformat(),),
        )

    def marcar_tarefa_concluida(
        self,
        identificador: Any,
        worker_token: Any = None,
        agora: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        return self.concluir_tarefa_paginacao(
            identificador, worker_token, agora, **kwargs
        )

    def concluir_tarefa(
        self,
        identificador: Any,
        worker_token: Any = None,
        agora: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        return self.concluir_tarefa_paginacao(
            identificador, worker_token, agora, **kwargs
        )

    def marcar_tarefa_retry(
        self,
        identificador: Any,
        *posicionais: Any,
        erro: str | None | object = _MISSING,
        proxima_tentativa_em: Any = _MISSING,
        agora: Any = None,
        proxima_tentativa: Any = None,
        atraso_segundos: float | timedelta | None = None,
        backoff_base_segundos: float = 60,
        worker_token: Any = None,
        token: Any = None,
        owner: Any = None,
    ) -> dict[str, Any] | None:
        """Registra falha somente para o worker dono de uma lease ativa.

        Para compatibilidade, uma tarefa retornada pela reivindicação pode ser
        passada como o primeiro argumento e ``erro``/a próxima data podem
        continuar posicionais. Com um id escalar, o token é obrigatório e
        pode ser informado por ``worker_token``/``token`` ou como primeiro
        argumento posicional.
        """
        pos = list(posicionais)
        eh_mapeamento = isinstance(identificador, Mapping)
        token_mapeado = self._token_tarefa(identificador)
        token_explicito = self._token_tarefa(
            identificador, worker_token, token=token, owner=owner
        )

        if eh_mapeamento:
            # O formato legado é (tarefa, erro, proxima_tentativa_em). Se o
            # chamador repetiu o token no segundo argumento, aceite também.
            if pos and token_mapeado is not None and str(pos[0]) == token_mapeado:
                pos.pop(0)
            if pos:
                if erro is not _MISSING:
                    raise TypeError("erro informado duas vezes")
                erro = pos.pop(0)
            if pos:
                if proxima_tentativa_em is not _MISSING:
                    raise TypeError("proxima_tentativa_em informado duas vezes")
                proxima_tentativa_em = pos.pop(0)
        else:
            # No id escalar a primeira posição nova é o token. Também aceite
            # a forma de compatibilidade que acrescenta o token ao final dos
            # argumentos antigos, mas apenas quando ele coincide com o token
            # persistido da tarefa.
            if token_explicito is None and pos:
                token_da_linha = None
                try:
                    coluna_linha, valor_linha = self._identificador_tarefa(
                        identificador
                    )
                    linha_linha = self.conexao.execute(
                        f"SELECT worker_token, owner FROM tarefas_paginacao "
                        f"WHERE {coluna_linha} = ?", (valor_linha,)
                    ).fetchone()
                    if linha_linha is not None:
                        token_da_linha = _token_normalizado(
                            linha_linha[0]
                        ) or _token_normalizado(linha_linha[1])
                except (TypeError, ValueError):
                    pass
                if (
                    token_da_linha is not None
                    and len(pos) > 1
                    and str(pos[-1]) == str(token_da_linha)
                ):
                    worker_token = pos.pop()
                else:
                    worker_token = pos.pop(0)
                token_explicito = self._token_tarefa(
                    identificador, worker_token, token=token, owner=owner
                )
            if pos:
                if erro is not _MISSING:
                    raise TypeError("erro informado duas vezes")
                erro = pos.pop(0)
            if pos:
                if proxima_tentativa_em is not _MISSING:
                    raise TypeError("proxima_tentativa_em informado duas vezes")
                proxima_tentativa_em = pos.pop(0)
        if pos:
            # Embora ``agora`` seja keyword-only na API original, aceitar uma
            # última data aqui torna a forma (id, token, erro, próxima, agora)
            # inequívoca sem abrir mão da validação do token.
            if len(pos) == 1 and agora is None and _datetime_utc(pos[0]) is not None:
                agora = pos.pop()
            else:
                raise TypeError("argumentos posicionais demais para a tarefa")

        token_normal = token_explicito
        if token_normal is None:
            token_normal = self._token_tarefa(
                identificador, worker_token, token=token, owner=owner
            )
        momento = self._momento(agora)
        if proxima_tentativa is not None:
            proxima_tentativa_em = proxima_tentativa
        if erro is _MISSING:
            erro = None
        coluna, valor = self._identificador_tarefa(identificador)

        with self.conexao:
            # A autorização e a atualização ficam na mesma transação. O teste
            # de expiração impede que um owner atrasado altere uma nova lease.
            if not token_normal:
                return None
            self.conexao.execute("BEGIN IMMEDIATE")
            linha = self.conexao.execute(
                f"""SELECT * FROM tarefas_paginacao
                       WHERE {coluna} = ?
                         AND (worker_token = ?
                              OR (worker_token IS NULL AND owner = ?))
                         AND reservada_ate IS NOT NULL
                         AND reservada_ate > ?""",
                (valor, token_normal, token_normal, momento.isoformat()),
            ).fetchone()
            if linha is None:
                return None
            tentativas = int(linha["tentativas"] or 0)
            if proxima_tentativa_em is None:
                if atraso_segundos is None:
                    base = _ttl_segundos(backoff_base_segundos)
                    if base is None:
                        base = 60
                    atraso = base * (2 ** max(tentativas - 1, 0))
                else:
                    atraso = _ttl_segundos(atraso_segundos)
                    if atraso is None:
                        atraso = DEFAULT_LEASE_SEGUNDOS
                proxima = (momento + timedelta(seconds=atraso)).isoformat()
            else:
                proxima = _texto_instante(proxima_tentativa_em)
            cursor = self.conexao.execute(
                f"""UPDATE tarefas_paginacao
                       SET status = 'RETRY', tentativas = ?, erro = ?,
                           proxima_tentativa_em = ?, reservada_ate = NULL,
                           worker_token = NULL, owner = NULL,
                           atualizada_em = ?
                     WHERE {coluna} = ?
                       AND (worker_token = ?
                            OR (worker_token IS NULL AND owner = ?))
                       AND reservada_ate IS NOT NULL
                       AND reservada_ate > ?""",
                (
                    tentativas,
                    erro,
                    proxima,
                    momento.isoformat(),
                    valor,
                    token_normal,
                    token_normal,
                    momento.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return None
            atualizada = self.conexao.execute(
                f"SELECT * FROM tarefas_paginacao WHERE {coluna} = ?", (valor,)
            ).fetchone()
        return None if atualizada is None else self._tarefa_dict(atualizada)

    def reagendar_tarefa_paginacao(
        self, identificador: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.marcar_tarefa_retry(identificador, *args, **kwargs)

    def falhar_tarefa_paginacao(
        self, identificador: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.marcar_tarefa_retry(identificador, *args, **kwargs)

    def retry_tarefa_paginacao(
        self, identificador: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.marcar_tarefa_retry(identificador, *args, **kwargs)

    def reagendar_tarefa(
        self, identificador: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.marcar_tarefa_retry(identificador, *args, **kwargs)

    def falhar_tarefa(
        self, identificador: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.marcar_tarefa_retry(identificador, *args, **kwargs)

    def retry_tarefa(
        self, identificador: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.marcar_tarefa_retry(identificador, *args, **kwargs)

    def salvar_tarefa_concluida(
        self,
        identificador: Any,
        worker_token: Any = None,
        agora: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        return self.concluir_tarefa_paginacao(
            identificador, worker_token, agora, **kwargs
        )
