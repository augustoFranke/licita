from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from licita_corpus.state import (
    CONCLUIDO,
    PENDENTE,
    POLICY_VERSION,
    RETRY,
    EstadoColeta,
    LimiteRequisicoes,
)


INSTANTE = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
COMPRA = {"numeroControlePNCP": "00000000000000-1-000001/2026"}


def test_migra_banco_antigo_sem_perder_inspecao(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.executescript(
        """
        CREATE TABLE respostas (
            chave TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            atualizada_em TEXT NOT NULL
        );
        CREATE TABLE inspecoes (
            numero_controle_pncp TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            motivo TEXT,
            compra_json TEXT NOT NULL,
            arquivos_json TEXT,
            candidato_json TEXT,
            atualizada_em TEXT NOT NULL
        );
        CREATE TABLE aceitos (
            numero_controle_pncp TEXT PRIMARY KEY,
            candidato_json TEXT NOT NULL,
            documentos_json TEXT NOT NULL,
            aceito_em TEXT NOT NULL
        );
        CREATE TABLE requisicoes (
            dia_utc TEXT PRIMARY KEY,
            quantidade INTEGER NOT NULL
        );
        """
    )
    conexao.execute(
        """INSERT INTO inspecoes
           VALUES (?, 'FORA_DO_ESCOPO', 'antiga', ?, NULL, NULL, ?)""",
        ("antigo", json.dumps(COMPRA), "2026-01-02T09:00:00-03:00"),
    )
    conexao.commit()
    conexao.close()

    estado = EstadoColeta(caminho, policy_version="2026.1")
    try:
        colunas = {
            linha[1]
            for linha in estado.conexao.execute("PRAGMA table_info(inspecoes)")
        }
        assert "policy_version" in colunas
        assert estado.conexao.execute(
            "SELECT name FROM sqlite_master WHERE name = 'ocr_resultados'"
        ).fetchone() is not None
        assert estado.conexao.execute("PRAGMA user_version").fetchone()[0] == 8
        # A migração é aditiva e o registro anterior continua disponível,
        # mas não é reutilizado automaticamente por uma política nova.
        assert estado.status_inspecao("antigo") is None
        assert estado.inspecao("antigo") is None
        assert estado.status_inspecao("antigo", None) == "FORA_DO_ESCOPO"
        assert estado.inspecao("antigo", None)["policy_version"] == "1"
        assert estado.inspecao("antigo", None)["atualizada_em"] == INSTANTE.isoformat()
        assert not estado.ja_processado("antigo")
        assert estado.ja_processado("antigo", None)

        estado.salvar_inspecao("novo", COMPRA, status="ACEITO")
        assert estado.inspecao("novo")["policy_version"] == "2026.1"
        assert estado.ja_processado("novo")
    finally:
        estado.close()


def test_migra_fila_incompleta_deduplica_e_reabre_idempotente(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.execute(
        """CREATE TABLE tarefas_paginacao (
               id INTEGER,
               fonte TEXT,
               parametros_json TEXT,
               pagina INTEGER,
               tamanho_pagina INTEGER,
               criada_em TEXT,
               atualizada_em TEXT
           )"""
    )
    conexao.executemany(
        """INSERT INTO tarefas_paginacao
           (id, fonte, parametros_json, pagina, tamanho_pagina,
            criada_em, atualizada_em)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                2,
                "fonte",
                '{"a": 1}',
                1,
                10,
                "2026-01-02T09:00:00-03:00",
                "2026-01-02T09:00:00-03:00",
            ),
            (
                1,
                "fonte",
                '{"a":1}',
                1,
                10,
                "2026-01-02 12:00:00",
                "2026-01-02 12:00:00",
            ),
            (3, "outra", "{}", 2, None, "ruim", "também ruim"),
        ],
    )
    conexao.commit()
    conexao.close()

    estado = EstadoColeta(caminho)
    try:
        tarefas = estado.listar_tarefas_paginacao()
        assert [t["id"] for t in tarefas] == [1, 3]
        assert tarefas[0]["criada_em"] == INSTANTE.isoformat()
        assert tarefas[0]["atualizada_em"] == INSTANTE.isoformat()
        assert tarefas[1]["status"] == PENDENTE
        assert "migração" in tarefas[1]["erro"]
        assert estado.criar_tarefa_paginacao(
            "fonte", {"a": 1}, 1, tamanho_pagina=10, agora=INSTANTE
        )["id"] == 1
        snapshot = [
            tuple(linha)
            for linha in estado.conexao.execute(
                "SELECT id, chave, parametros_json, status, erro, criada_em, atualizada_em "
                "FROM tarefas_paginacao ORDER BY id"
            )
        ]
    finally:
        estado.close()

    estado = EstadoColeta(caminho)
    try:
        assert [t["id"] for t in estado.listar_tarefas_paginacao()] == [1, 3]
        assert [
            tuple(linha)
            for linha in estado.conexao.execute(
                "SELECT id, chave, parametros_json, status, erro, criada_em, atualizada_em "
                "FROM tarefas_paginacao ORDER BY id"
            )
        ] == snapshot
        indices = {
            linha[1]
            for linha in estado.conexao.execute(
                "PRAGMA index_list(tarefas_paginacao)"
            )
        }
        assert "uq_tarefas_paginacao_natural" in indices
    finally:
        estado.close()


def test_leases_tem_owner_token_expiram_e_rejeitam_owner_obsoleto(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    primeiro = EstadoColeta(caminho)
    segundo = EstadoColeta(caminho)
    try:
        primeiro.criar_tarefa_paginacao("fonte", {}, 1, agora=INSTANTE)
        antigo = primeiro.proxima_tarefa_paginacao(
            agora=INSTANTE, lease_segundos=None
        )
        assert antigo is not None
        assert antigo["worker_token"]
        assert antigo["owner"] == antigo["worker_token"]
        assert antigo["reservada_ate"] == (
            INSTANTE + timedelta(seconds=300)
        ).isoformat()
        assert segundo.proxima_tarefa_paginacao(agora=INSTANTE) is None
        assert primeiro.concluir_tarefa_paginacao(
            antigo["id"], agora=INSTANTE
        ) is None

        novo = segundo.proxima_tarefa_paginacao(
            agora=INSTANTE + timedelta(seconds=301)
        )
        assert novo is not None
        assert novo["worker_token"] != antigo["worker_token"]
        assert primeiro.concluir_tarefa_paginacao(
            antigo["id"], antigo["worker_token"], agora=INSTANTE + timedelta(seconds=301)
        ) is None
        assert primeiro.reagendar_tarefa_paginacao(
            antigo["id"], antigo["worker_token"], erro="owner antigo",
            proxima_tentativa_em=INSTANTE + timedelta(seconds=302),
            agora=INSTANTE + timedelta(seconds=301),
        ) is None
        assert primeiro.falhar_tarefa_paginacao(
            antigo["id"], worker_token=antigo["worker_token"], erro="owner antigo",
            proxima_tentativa_em=INSTANTE + timedelta(seconds=302),
            agora=INSTANTE + timedelta(seconds=301),
        ) is None
        concluida = segundo.concluir_tarefa_paginacao(
            novo["id"], novo["worker_token"], agora=INSTANTE + timedelta(seconds=301)
        )
        assert concluida is not None
        assert concluida["status"] == CONCLUIDO
    finally:
        primeiro.close()
        segundo.close()


def test_aceitos_e_inspecoes_respeitam_policy_ativa_com_legado_explicito(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    candidato = {"numero_controle_pncp": "aceito-1"}
    documentos = [{"papel": "ETP"}]
    estado = EstadoColeta(caminho, policy_version="v1")
    try:
        estado.salvar_aceito(candidato, documentos, agora=INSTANTE)
        estado.salvar_inspecao("aceito-1", COMPRA, status="ACEITO", agora=INSTANTE)
    finally:
        estado.close()

    estado = EstadoColeta(caminho, policy_version="v2")
    try:
        assert estado.aceitos() == []
        assert estado.numeros_aceitos() == set()
        assert estado.aceitos("v1") == [(candidato, documentos)]
        assert estado.numeros_aceitos(None) == {"aceito-1"}
        assert estado.status_inspecao("aceito-1") is None
        assert estado.inspecao("aceito-1") is None
        assert estado.status_inspecao("aceito-1", None) == "ACEITO"
        assert estado.ja_processado("aceito-1", None)
    finally:
        estado.close()


def test_policy_oficial_exata():
    assert POLICY_VERSION == "4-municipal-historical-ocr"


def test_cache_ocr_put_get_chave_estavel_e_corrupcao_vira_miss(tmp_path):
    estado = EstadoColeta(tmp_path / "estado.sqlite3")
    sha256 = "a" * 64
    config = {
        "pipeline_version": "pipeline-v1",
        "opcoes_ocr": {"ocr": True, "dpi_ocr": 200},
    }
    resultado = {
        "texto": "texto derivado por OCR",
        "verificacao": {"abriu": True, "ocr_usado": True},
    }
    try:
        chave = estado.salvar_resultado_ocr(
            sha256,
            " POR ",
            "pipeline-v1",
            config,
            resultado,
            agora=INSTANTE,
        )
        assert chave == estado.chave_resultado_ocr(
            sha256, "por", "pipeline-v1", config
        )
        assert estado.obter_resultado_ocr(
            sha256, "por", "pipeline-v1", config
        ) == resultado
        assert estado.obter_resultado_ocr(
            "b" * 64, "por", "pipeline-v1", config
        ) is None
        assert estado.obter_resultado_ocr(
            sha256, "eng", "pipeline-v1", config
        ) is None
        assert estado.obter_resultado_ocr(
            sha256, "por", "pipeline-v2", config
        ) is None
        assert estado.obter_resultado_ocr(
            sha256, "por", "pipeline-v1", {**config, "extra": True}
        ) is None

        estado.conexao.execute(
            "UPDATE ocr_resultados SET resultado_json = '{' WHERE chave = ?",
            (chave,),
        )
        estado.conexao.commit()
        assert estado.obter_resultado_ocr(
            sha256, "por", "pipeline-v1", config
        ) is None
    finally:
        estado.close()


@pytest.mark.parametrize(
    ("sha256", "idioma", "versao", "config"),
    [
        ("curto", "por", "v1", {}),
        ("a" * 64, " ", "v1", {}),
        ("a" * 64, "por", " ", {}),
        ("a" * 64, "por", "v1", {"infinito": float("inf")}),
    ],
)
def test_cache_ocr_valida_identidade_e_config(
    tmp_path, sha256, idioma, versao, config
):
    estado = EstadoColeta(tmp_path / "estado.sqlite3")
    try:
        with pytest.raises(ValueError):
            estado.obter_resultado_ocr(sha256, idioma, versao, config)
    finally:
        estado.close()


def test_cache_tem_ttl_diferente_para_payload_vazio(tmp_path):
    estado = EstadoColeta(
        tmp_path / "estado.sqlite3",
        cache_ttl_segundos=None,
        cache_ttl_vazio_segundos=timedelta(seconds=5),
    )
    try:
        estado.salvar_resposta(
            "cheia",
            {"items": [1]},
            agora=INSTANTE,
            ttl_segundos=timedelta(seconds=10),
        )
        estado.salvar_resposta("vazia", [], agora=INSTANTE)

        assert estado.resposta("cheia", agora=INSTANTE + timedelta(seconds=9)) == {
            "items": [1]
        }
        assert estado.resposta("cheia", agora=INSTANTE + timedelta(seconds=10)) is None
        assert estado.resposta("vazia", agora=INSTANTE + timedelta(seconds=4)) == []
        assert estado.resposta("vazia", agora=INSTANTE + timedelta(seconds=5)) is None
    finally:
        estado.close()


def test_saldo_e_margem_nao_deixam_consumir_reserva(tmp_path):
    estado = EstadoColeta(
        tmp_path / "estado.sqlite3", max_requisicoes_dia=4, margem_requisicoes=1
    )
    try:
        assert estado.saldo_requisicoes(agora=INSTANTE) == 4
        assert estado.margem_orcamento(agora=INSTANTE) == 3
        assert estado.reservar_requisicao(agora=INSTANTE) == 1
        assert estado.reservar_requisicao(agora=INSTANTE) == 2
        assert estado.reservar_requisicao(agora=INSTANTE) == 3
        assert estado.saldo_requisicoes(agora=INSTANTE) == 1
        assert estado.margem_orcamento(agora=INSTANTE) == 0
        with pytest.raises(LimiteRequisicoes):
            estado.reservar_requisicao(agora=INSTANTE)
    finally:
        estado.close()


def test_tarefa_de_paginacao_retorna_retry_e_conta_tentativas(tmp_path):
    estado = EstadoColeta(tmp_path / "estado.sqlite3")
    proxima = INSTANTE + timedelta(minutes=1)
    try:
        criada = estado.criar_tarefa_paginacao(
            "compras-gov", {"inicio": "2026-01-01"}, 1, tamanho_pagina=500,
            agora=INSTANTE,
        )
        assert criada["status"] == PENDENTE
        assert criada["tentativas"] == 0

        primeira = estado.proxima_tarefa_paginacao(agora=INSTANTE)
        assert primeira is not None
        assert primeira["tentativas"] == 1
        assert estado.proxima_tarefa_paginacao(agora=INSTANTE) is None

        retry = estado.marcar_tarefa_retry(
            primeira,
            "timeout",
            proxima,
            agora=INSTANTE,
        )
        assert retry["status"] == RETRY
        assert retry["tentativas"] == 1
        assert retry["erro"] == "timeout"
        assert retry["proxima_tentativa_em"] == proxima.isoformat()
        assert estado.proxima_tarefa_paginacao(agora=proxima - timedelta(seconds=1)) is None

        segunda = estado.proxima_tarefa_paginacao(agora=proxima)
        assert segunda["tentativas"] == 2
        concluida = estado.concluir_tarefa_paginacao(segunda, agora=proxima)
        assert concluida["status"] == CONCLUIDO
        assert concluida["erro"] is None
        assert estado.tarefas_pendentes(agora=proxima) == []
    finally:
        estado.close()


def test_lease_pode_ficar_restrita_ao_lote_solicitado(tmp_path):
    estado = EstadoColeta(tmp_path / "estado.sqlite3")
    try:
        primeira = estado.criar_tarefa_paginacao(
            "pncp-busca", {"termo": "ETP"}, 1, agora=INSTANTE
        )
        segunda = estado.criar_tarefa_paginacao(
            "compras-gov", {"inicio": "2026-01-01"}, 1, agora=INSTANTE
        )

        escolhida = estado.proxima_tarefa_paginacao(
            agora=INSTANTE,
            identificadores=[segunda["id"]],
        )

        assert escolhida is not None
        assert escolhida["id"] == segunda["id"]
        restante = estado.proxima_tarefa_paginacao(
            agora=INSTANTE,
            identificadores=[primeira["id"]],
        )
        assert restante is not None
        assert restante["id"] == primeira["id"]
    finally:
        estado.close()


def test_migra_requisicoes_canonicas_soma_e_bloqueia_invalidas(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.execute(
        "CREATE TABLE requisicoes (dia_utc TEXT PRIMARY KEY, quantidade INTEGER NOT NULL)"
    )
    conexao.executemany(
        "INSERT INTO requisicoes (dia_utc, quantidade) VALUES (?, ?)",
        [
            ("2026-01-02T23:00:00-03:00", 2),
            ("2026-01-03", "3"),
            ("2026-01-03T01:00:00Z", 4),
            ("data que não existe", 8),
            ("2026-01-03T02:00:00Z", "quantidade ilegível"),
        ],
    )
    conexao.commit()
    conexao.close()

    estado = EstadoColeta(caminho, max_requisicoes_dia=100)
    try:
        assert [
            tuple(linha)
            for linha in estado.conexao.execute(
                "SELECT dia_utc, quantidade FROM requisicoes"
            )
        ] == [("2026-01-03", 9)]
        assert estado.requisicoes_hoje("2026-01-03") == 9
        auditoria = estado.requisicoes_invalidas()
        assert len(auditoria) == 2
        assert {linha["dia_utc_original"] for linha in auditoria} == {
            "data que não existe",
            "2026-01-03T02:00:00Z",
        }
        assert estado.saldo_requisicoes("2026-01-03") == 0
        with pytest.raises(LimiteRequisicoes, match="auditoria"):
            estado.reservar_requisicao("2026-01-03")
        assert estado.requisicoes_hoje("2026-01-03") == 9
    finally:
        estado.close()

    # A reabertura não reaudita nem perde o bloqueio fail-closed.
    estado = EstadoColeta(caminho, max_requisicoes_dia=100)
    try:
        assert len(estado.requisicoes_invalidas()) == 2
        assert estado.orcamento("2026-01-03")["saldo"] == 0
    finally:
        estado.close()


def test_migra_tokens_vazios_para_null_antes_dos_indices(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.execute(
        """CREATE TABLE tarefas_paginacao (
               id INTEGER, fonte TEXT, parametros_json TEXT,
               pagina INTEGER, tamanho_pagina INTEGER,
               criada_em TEXT, atualizada_em TEXT,
               worker_token TEXT, owner TEXT
           )"""
    )
    conexao.executemany(
        """INSERT INTO tarefas_paginacao
           (id, fonte, parametros_json, pagina, tamanho_pagina,
            criada_em, atualizada_em, worker_token, owner)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, "a", "{}", 1, None, INSTANTE.isoformat(), INSTANTE.isoformat(), "", "  "),
            (2, "b", "{}", 1, None, INSTANTE.isoformat(), INSTANTE.isoformat(), "\t", ""),
        ],
    )
    conexao.commit()
    conexao.close()

    estado = EstadoColeta(caminho)
    try:
        assert [
            tuple(linha)
            for linha in estado.conexao.execute(
                "SELECT worker_token, owner FROM tarefas_paginacao ORDER BY id"
            )
        ] == [(None, None), (None, None)]
        assert all(
            tarefa["worker_token"] is None
            for tarefa in estado.listar_tarefas_paginacao()
        )
        indices = {
            linha[1]
            for linha in estado.conexao.execute(
                "PRAGMA index_list(tarefas_paginacao)"
            )
        }
        assert "uq_tarefas_paginacao_worker_token" in indices
        assert "uq_tarefas_paginacao_owner" in indices
        estado.criar_tarefa_paginacao("c", {}, 1, agora=INSTANTE)
        tarefa = estado.proxima_tarefa_paginacao(agora=INSTANTE)
        assert tarefa is not None
        assert tarefa["worker_token"]
    finally:
        estado.close()


def test_policies_coexistem_com_chave_composta_e_consultas_sem_filtro(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.executescript(
        """
        CREATE TABLE inspecoes (
            numero_controle_pncp TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            motivo TEXT,
            compra_json TEXT NOT NULL,
            arquivos_json TEXT,
            candidato_json TEXT,
            atualizada_em TEXT NOT NULL
        );
        CREATE TABLE aceitos (
            numero_controle_pncp TEXT PRIMARY KEY,
            candidato_json TEXT NOT NULL,
            documentos_json TEXT NOT NULL,
            aceito_em TEXT NOT NULL
        );
        """
    )
    conexao.execute(
        "INSERT INTO inspecoes VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("mesmo", "FORA_DO_ESCOPO", "v1", "{}", None, None, "2026-01-01"),
    )
    conexao.execute(
        "INSERT INTO aceitos VALUES (?, ?, ?, ?)",
        ("mesmo", json.dumps({"numero_controle_pncp": "mesmo", "versao": "v1"}), "[]", "2026-01-01"),
    )
    conexao.commit()
    conexao.close()

    v2 = EstadoColeta(caminho, policy_version="v2")
    try:
        compra_v2 = {"numero_controle_pncp": "mesmo", "versao": "v2"}
        v2.salvar_inspecao(
            "mesmo", compra_v2, status="ACEITO", policy_version="v2", agora=INSTANTE
        )
        v2.salvar_aceito(compra_v2, [{"papel": "TR"}], policy_version="v2", agora=INSTANTE)
        assert [
            tuple(linha)
            for linha in v2.conexao.execute(
                "SELECT numero_controle_pncp, policy_version FROM inspecoes "
                "ORDER BY policy_version"
            )
        ] == [("mesmo", "1"), ("mesmo", "v2")]
        assert [
            tuple(linha)
            for linha in v2.conexao.execute(
                "SELECT numero_controle_pncp, policy_version FROM aceitos "
                "ORDER BY policy_version"
            )
        ] == [("mesmo", "1"), ("mesmo", "v2")]
        assert [linha[5] for linha in v2.conexao.execute("PRAGMA table_info(inspecoes)") if linha[1] in {"numero_controle_pncp", "policy_version"}] == [1, 2]
        assert v2.status_inspecao("mesmo") == "ACEITO"
        assert v2.inspecao("mesmo")["policy_version"] == "v2"
        assert v2.aceitos() == [(compra_v2, [{"papel": "TR"}])]
        assert v2.aceitos("1")[0][0]["versao"] == "v1"
        assert len(v2.aceitos(None)) == 2
        assert v2.inspecao("mesmo", "1")["status"] == "FORA_DO_ESCOPO"
        assert v2.inspecao("mesmo", None)["policy_version"] == "v2"
        assert v2.aceito("mesmo", None) == (compra_v2, [{"papel": "TR"}])
    finally:
        v2.close()

    v1 = EstadoColeta(caminho, policy_version="1")
    try:
        assert v1.status_inspecao("mesmo") == "FORA_DO_ESCOPO"
        assert v1.aceito("mesmo")[0]["versao"] == "v1"
        assert len(v1.aceitos(None)) == 2
    finally:
        v1.close()


def test_migra_banco_intermediario_com_policy_sem_perder_v1(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.executescript(
        """
        CREATE TABLE inspecoes (
            numero_controle_pncp TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            motivo TEXT,
            compra_json TEXT NOT NULL,
            arquivos_json TEXT,
            candidato_json TEXT,
            atualizada_em TEXT NOT NULL,
            policy_version TEXT NOT NULL DEFAULT '1'
        );
        CREATE TABLE aceitos (
            numero_controle_pncp TEXT PRIMARY KEY,
            candidato_json TEXT NOT NULL,
            documentos_json TEXT NOT NULL,
            aceito_em TEXT NOT NULL,
            policy_version TEXT NOT NULL DEFAULT '1'
        );
        CREATE UNIQUE INDEX idx_inspecoes_status ON inspecoes(numero_controle_pncp);
        CREATE INDEX idx_aceitos_policy_version ON aceitos(numero_controle_pncp);
        """
    )
    conexao.execute(
        "INSERT INTO inspecoes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("intermediario", "FORA_DO_ESCOPO", None, "{}", None, None, "2026-01-01", "1"),
    )
    conexao.execute(
        "INSERT INTO aceitos VALUES (?, ?, ?, ?, ?)",
        ("intermediario", json.dumps({"numero_controle_pncp": "intermediario", "v": 1}), "[]", "2026-01-01", "1"),
    )
    conexao.commit()
    conexao.close()

    estado = EstadoColeta(caminho, policy_version="2")
    try:
        candidato_v2 = {"numero_controle_pncp": "intermediario", "v": 2}
        estado.salvar_inspecao(
            "intermediario", candidato_v2, status="ACEITO", policy_version="2", agora=INSTANTE
        )
        estado.salvar_aceito(candidato_v2, [], policy_version="2", agora=INSTANTE)
        assert {
            tuple(linha)
            for linha in estado.conexao.execute(
                "SELECT numero_controle_pncp, policy_version FROM inspecoes"
            )
        } == {("intermediario", "1"), ("intermediario", "2")}
        assert {
            tuple(linha)
            for linha in estado.conexao.execute(
                "SELECT numero_controle_pncp, policy_version FROM aceitos"
            )
        } == {("intermediario", "1"), ("intermediario", "2")}
    finally:
        estado.close()


def test_migracao_recria_indice_com_definicao_correta(tmp_path):
    caminho = tmp_path / "estado.sqlite3"
    estado = EstadoColeta(caminho)
    estado.close()
    conexao = sqlite3.connect(caminho)
    conexao.execute("DROP INDEX idx_inspecoes_status")
    conexao.execute(
        "CREATE INDEX idx_inspecoes_status ON inspecoes(numero_controle_pncp)"
    )
    conexao.execute("DROP INDEX uq_tarefas_paginacao_worker_token")
    conexao.execute(
        "CREATE INDEX uq_tarefas_paginacao_worker_token ON tarefas_paginacao(owner)"
    )
    conexao.commit()
    conexao.close()

    estado = EstadoColeta(caminho)
    try:
        assert [linha[2] for linha in estado.conexao.execute(
            "PRAGMA index_info(idx_inspecoes_status)"
        )] == ["status"]
        trabalhador = estado.conexao.execute(
            "PRAGMA index_list(tarefas_paginacao)"
        ).fetchall()
        indice = next(
            linha for linha in trabalhador
            if linha[1] == "uq_tarefas_paginacao_worker_token"
        )
        assert indice[2] == 1
        assert [linha[2] for linha in estado.conexao.execute(
            "PRAGMA index_info(uq_tarefas_paginacao_worker_token)"
        )] == ["worker_token"]
    finally:
        estado.close()


def test_migracao_falha_faz_rollback_do_schema_legado(tmp_path, monkeypatch):
    caminho = tmp_path / "estado.sqlite3"
    conexao = sqlite3.connect(caminho)
    conexao.execute(
        """CREATE TABLE inspecoes (
               numero_controle_pncp TEXT PRIMARY KEY,
               status TEXT NOT NULL, motivo TEXT,
               compra_json TEXT NOT NULL, arquivos_json TEXT,
               candidato_json TEXT, atualizada_em TEXT NOT NULL
           )"""
    )
    conexao.execute(
        "INSERT INTO inspecoes VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("legado", "ACEITO", None, "{}", None, None, "data original"),
    )
    conexao.commit()
    conexao.close()

    migracao_original = EstadoColeta._migrar_tabelas_politica

    def falhar_depois_da_migracao(self, *args):
        migracao_original(self, *args)
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(
        EstadoColeta, "_migrar_tabelas_politica", falhar_depois_da_migracao
    )
    with pytest.raises(RuntimeError, match="falha de teste"):
        EstadoColeta(caminho)

    conexao = sqlite3.connect(caminho)
    assert [linha[1] for linha in conexao.execute("PRAGMA table_info(inspecoes)")] == [
        "numero_controle_pncp", "status", "motivo", "compra_json",
        "arquivos_json", "candidato_json", "atualizada_em",
    ]
    assert conexao.execute("SELECT atualizada_em FROM inspecoes").fetchone()[0] == "data original"
    assert conexao.execute("PRAGMA user_version").fetchone()[0] == 0
    conexao.close()
