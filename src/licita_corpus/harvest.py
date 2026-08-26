"""Descoberta rarest-first de cadeias documentais no PNCP.

O coletor começa no feed oficial de contratações por publicação, já filtrado
para Pregão Eletrônico. Metadados eliminam entes e objetos fora do escopo antes
de qualquer chamada adicional. A ordem dos testes caros é deliberada:

``contratação → arquivos ETP/TR/edital → contratos associados → contrato``.

Quando um órgão publica o trio raro, suas demais contratações são priorizadas
por consultas com CNPJ. Estado, páginas e falhas ficam em SQLite para retomada.
"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from .classify import (
    CONTRATO,
    EDITAL,
    ETP,
    TR,
    categoria_objeto,
    normalizar,
    papel_documento,
    papel_documento_contrato,
    parece_aquisicao_de_bens,
)
from .pncp import Pncp, PncpError, partes_controle
from .select import Candidato, Cotas, selecionar


@dataclass(frozen=True, slots=True)
class ResultadoDescoberta:
    candidatos: list[dict[str, Any]]
    contratacoes_lidas: int
    compras_inspecionadas: int
    rejeitados: int
    falhas_api: int = 0


@dataclass(frozen=True, slots=True)
class Consulta:
    chave: str
    tipo: str
    inicio: str
    fim: str
    cnpj: str | None = None


class BancoHarvest:
    """Fila e cache transacionais do harvest; uma linha por contratação."""

    def __init__(self, caminho: Path, validade_dias: int = 7) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.validade_dias = validade_dias
        self.conexao = sqlite3.connect(caminho)
        self.conexao.row_factory = sqlite3.Row
        self.conexao.execute("PRAGMA journal_mode=WAL")
        self.conexao.executescript(
            """
            CREATE TABLE IF NOT EXISTS consultas (
                chave TEXT PRIMARY KEY,
                tipo TEXT NOT NULL,
                inicio TEXT NOT NULL,
                fim TEXT NOT NULL,
                cnpj TEXT,
                proxima_pagina INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'PENDENTE',
                erro TEXT,
                atualizada_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inspecoes (
                numero_controle_pncp TEXT PRIMARY KEY,
                cnpj TEXT NOT NULL,
                categoria TEXT NOT NULL,
                status TEXT NOT NULL,
                motivo TEXT,
                tem_trio INTEGER NOT NULL,
                candidato_json TEXT,
                atualizada_em TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_inspecoes_status ON inspecoes(status);
            CREATE INDEX IF NOT EXISTS idx_inspecoes_cnpj ON inspecoes(cnpj);
            """
        )
        self.conexao.commit()

    def close(self) -> None:
        self.conexao.close()

    @staticmethod
    def _agora() -> str:
        return datetime.now().astimezone().isoformat()

    def iniciar_consulta(self, consulta: Consulta) -> sqlite3.Row:
        self.conexao.execute(
            """INSERT OR IGNORE INTO consultas
               (chave, tipo, inicio, fim, cnpj, atualizada_em)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (consulta.chave, consulta.tipo, consulta.inicio, consulta.fim, consulta.cnpj, self._agora()),
        )
        self.conexao.commit()
        linha = self.conexao.execute(
            "SELECT * FROM consultas WHERE chave = ?", (consulta.chave,)
        ).fetchone()
        limite = (datetime.now().astimezone() - timedelta(days=self.validade_dias)).isoformat()
        if linha["status"] == "CONCLUIDA" and linha["atualizada_em"] < limite:
            self.conexao.execute(
                """UPDATE consultas SET proxima_pagina = 1, status = 'PENDENTE',
                   erro = NULL, atualizada_em = ? WHERE chave = ?""",
                (self._agora(), consulta.chave),
            )
            self.conexao.commit()
            linha = self.conexao.execute(
                "SELECT * FROM consultas WHERE chave = ?", (consulta.chave,)
            ).fetchone()
        return linha

    def avancar_consulta(self, chave: str, proxima_pagina: int, concluida: bool) -> None:
        self.conexao.execute(
            """UPDATE consultas
               SET proxima_pagina = ?, status = ?, erro = NULL, atualizada_em = ?
               WHERE chave = ?""",
            (proxima_pagina, "CONCLUIDA" if concluida else "PENDENTE", self._agora(), chave),
        )
        self.conexao.commit()

    def falhar_consulta(self, chave: str, erro: str) -> None:
        self.conexao.execute(
            """UPDATE consultas SET status = 'PENDENTE', erro = ?, atualizada_em = ?
               WHERE chave = ?""",
            (erro, self._agora(), chave),
        )
        self.conexao.commit()

    def ja_inspecionados(self, numeros: Iterable[str]) -> set[str]:
        valores = list(numeros)
        if not valores:
            return set()
        marcas = ",".join("?" for _ in valores)
        limite = (datetime.now().astimezone() - timedelta(days=self.validade_dias)).isoformat()
        linhas = self.conexao.execute(
            f"""SELECT numero_controle_pncp FROM inspecoes
                WHERE numero_controle_pncp IN ({marcas})
                  AND (status = 'COMPLETO' OR atualizada_em >= ?)""",
            [*valores, limite],
        )
        return {linha[0] for linha in linhas}

    def salvar_inspecao(self, registro: dict[str, Any]) -> None:
        candidato = registro.get("candidato")
        self.conexao.execute(
            """INSERT OR REPLACE INTO inspecoes
               (numero_controle_pncp, cnpj, categoria, status, motivo, tem_trio,
                candidato_json, atualizada_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                registro["numero_controle_pncp"],
                registro["cnpj"],
                registro["categoria"],
                registro["status"],
                registro.get("motivo"),
                int(registro["tem_trio"]),
                json.dumps(candidato, ensure_ascii=False) if candidato else None,
                self._agora(),
            ),
        )
        self.conexao.commit()

    def candidatos_completos(self) -> list[dict[str, Any]]:
        linhas = self.conexao.execute(
            "SELECT candidato_json FROM inspecoes WHERE status = 'COMPLETO' ORDER BY atualizada_em"
        )
        return [json.loads(linha[0]) for linha in linhas if linha[0]]

    def invalidar_download(self, numero: str, motivo: str) -> None:
        self.conexao.execute(
            """UPDATE inspecoes SET status = 'DOWNLOAD_REPROVADO', motivo = ?,
               candidato_json = NULL, atualizada_em = ?
               WHERE numero_controle_pncp = ?""",
            (motivo, self._agora(), numero),
        )
        self.conexao.commit()

    def consultas_com_falha(self) -> list[Consulta]:
        linhas = self.conexao.execute(
            """SELECT chave, tipo, inicio, fim, cnpj FROM consultas
               WHERE status = 'PENDENTE' AND erro IS NOT NULL ORDER BY atualizada_em"""
        )
        return [Consulta(*linha) for linha in linhas]

    def quantidade_falhas_pendentes(self) -> int:
        return int(
            self.conexao.execute(
                "SELECT COUNT(*) FROM consultas WHERE status = 'PENDENTE' AND erro IS NOT NULL"
            ).fetchone()[0]
        )

    def publicadores_produtivos(self) -> list[str]:
        linhas = self.conexao.execute(
            "SELECT DISTINCT cnpj FROM inspecoes WHERE tem_trio = 1 ORDER BY cnpj"
        )
        return [linha[0] for linha in linhas]

    def completos_do_orgao(self, cnpj: str) -> int:
        return int(
            self.conexao.execute(
                "SELECT COUNT(*) FROM inspecoes WHERE status = 'COMPLETO' AND cnpj = ?", (cnpj,)
            ).fetchone()[0]
        )

    def quantidade_inspecoes(self) -> int:
        return int(self.conexao.execute("SELECT COUNT(*) FROM inspecoes").fetchone()[0])

    def quantidade_rejeitados(self) -> int:
        return int(
            self.conexao.execute("SELECT COUNT(*) FROM inspecoes WHERE status != 'COMPLETO'").fetchone()[0]
        )


def _data(valor: str) -> date:
    return datetime.strptime(valor, "%Y%m%d").date()


def janelas_diarias(data_inicial: str, data_final: str) -> list[tuple[str, str]]:
    inicio, fim = _data(data_inicial), _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    return [
        ((fim - timedelta(days=i)).strftime("%Y%m%d"), (fim - timedelta(days=i)).strftime("%Y%m%d"))
        for i in range((fim - inicio).days + 1)
    ]


def janelas_amplas(data_inicial: str, data_final: str) -> list[tuple[str, str]]:
    """Janelas reversas de até 365 dias para consultas de um único órgão."""
    inicio, fim = _data(data_inicial), _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    saida: list[tuple[str, str]] = []
    cursor = fim
    while cursor >= inicio:
        comeco = max(inicio, cursor - timedelta(days=364))
        saida.append((comeco.strftime("%Y%m%d"), cursor.strftime("%Y%m%d")))
        cursor = comeco - timedelta(days=1)
    return saida


def _inteiro(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def motivo_compra(compra: dict[str, Any]) -> str | None:
    """Filtro de alta precisão aplicado antes de consultar arquivos."""
    orgao = compra.get("orgaoEntidade") or {}
    if orgao.get("esferaId") != "F":
        return "contratação não federal"
    if orgao.get("poderId") != "E":
        return "fora do Poder Executivo federal"
    if _inteiro(compra.get("modalidadeId")) != 6:
        return "modalidade não é Pregão Eletrônico"
    instrumento = normalizar(compra.get("tipoInstrumentoConvocatorioNome", ""))
    if _inteiro(compra.get("tipoInstrumentoConvocatorioCodigo")) != 1 or instrumento != "edital":
        return "instrumento convocatório não é Edital"
    amparo = compra.get("amparoLegal") or {}
    texto_legal = normalizar(f"{amparo.get('nome', '')} {amparo.get('descricao', '')}")
    if _inteiro(amparo.get("codigo")) != 1 or "lei 14 133 2021" not in texto_legal:
        return "fora da Lei 14.133/2021, Art. 28, I"
    if not parece_aquisicao_de_bens(compra.get("objetoCompra") or ""):
        return "objeto não é aquisição de bens no escopo"
    return None


def resumir_compra(compra: dict[str, Any]) -> dict[str, Any]:
    orgao = compra.get("orgaoEntidade") or {}
    unidade = compra.get("unidadeOrgao") or {}
    amparo = compra.get("amparoLegal") or {}
    numero = compra["numeroControlePNCP"]
    cnpj, ano, sequencial = partes_controle(numero)
    objeto = compra.get("objetoCompra") or ""
    return {
        "numero_controle_pncp": numero,
        "cnpj_orgao": cnpj,
        "ano_compra": ano,
        "sequencial_compra": sequencial,
        "orgao": orgao.get("razaoSocial"),
        "esfera": orgao.get("esferaId"),
        "poder": orgao.get("poderId"),
        "unidade": unidade.get("nomeUnidade"),
        "uf": unidade.get("ufSigla"),
        "municipio": unidade.get("municipioNome"),
        "modalidade_id": compra.get("modalidadeId"),
        "modalidade": compra.get("modalidadeNome"),
        "titulo": compra.get("numeroCompra"),
        "objeto": objeto,
        "categoria_objeto": categoria_objeto(objeto),
        "data_publicacao_pncp": compra.get("dataPublicacaoPncp"),
        "data_inicio_proposta": compra.get("dataAberturaProposta"),
        "data_fim_proposta": compra.get("dataEncerramentoProposta"),
        "situacao": compra.get("situacaoCompraNome"),
        "tem_resultado": compra.get("existeResultado"),
        "valor_global": compra.get("valorTotalEstimado"),
        "valor_total_homologado": compra.get("valorTotalHomologado"),
        "processo": compra.get("processo"),
        "srp": compra.get("srp"),
        "amparo_legal_codigo": amparo.get("codigo"),
        "amparo_legal_nome": amparo.get("nome"),
        "amparo_legal_descricao": amparo.get("descricao"),
        "instrumento_convocatorio_codigo": compra.get("tipoInstrumentoConvocatorioCodigo"),
        "instrumento_convocatorio": compra.get("tipoInstrumentoConvocatorioNome"),
        "origem_descoberta": "contratacoes_publicadas_pncp",
    }


def resumir_contrato(contrato: dict[str, Any]) -> dict[str, Any]:
    orgao = contrato.get("orgaoEntidade") or {}
    unidade = contrato.get("unidadeOrgao") or {}
    categoria = contrato.get("categoriaProcesso") or {}
    tipo = contrato.get("tipoContrato") or {}
    return {
        "fonte": "pncp",
        "numero_controle_pncp": contrato["numeroControlePNCP"],
        "numero_controle_pncp_compra": contrato.get("numeroControlePncpCompra"),
        "cnpj_orgao": orgao.get("cnpj"),
        "orgao": orgao.get("razaoSocial"),
        "esfera": orgao.get("esferaId"),
        "uf": unidade.get("ufSigla"),
        "municipio": unidade.get("municipioNome"),
        "ano_contrato": contrato.get("anoContrato"),
        "sequencial_contrato": contrato.get("sequencialContrato"),
        "numero_contrato": contrato.get("numeroContratoEmpenho"),
        "processo": contrato.get("processo"),
        "categoria_processo": categoria.get("nome"),
        "tipo_contrato": tipo.get("nome"),
        "data_assinatura": contrato.get("dataAssinatura"),
        "data_publicacao_pncp": contrato.get("dataPublicacaoPncp"),
        "data_atualizacao_global": contrato.get("dataAtualizacaoGlobal"),
        "numero_retificacao": contrato.get("numeroRetificacao"),
        "vigencia_inicio": contrato.get("dataVigenciaInicio"),
        "vigencia_fim": contrato.get("dataVigenciaFim"),
        "objeto": contrato.get("objetoContrato") or "",
        "fornecedor": contrato.get("nomeRazaoSocialFornecedor"),
        "ni_fornecedor": contrato.get("niFornecedor"),
        "valor_global": contrato.get("valorGlobal"),
        "criterio_vinculo": "numeroControlePncpCompra",
    }


def resumir_arquivo_compra(bruto: dict[str, Any]) -> dict[str, Any]:
    titulo = bruto.get("titulo") or ""
    return {
        "sequencial_documento": bruto.get("sequencialDocumento"),
        "titulo": titulo,
        "tipo_documento_id": bruto.get("tipoDocumentoId"),
        "tipo_documento_pncp": bruto.get("tipoDocumentoNome"),
        "papel": papel_documento(bruto.get("tipoDocumentoId"), titulo),
        "url": bruto.get("url") or bruto.get("uri"),
        "data_publicacao_pncp": bruto.get("dataPublicacaoPncp"),
    }


def resumir_arquivo_contrato(bruto: dict[str, Any]) -> dict[str, Any]:
    titulo = bruto.get("titulo") or ""
    return {
        "sequencial_documento": bruto.get("sequencialDocumento"),
        "titulo": titulo,
        "tipo_documento_id": bruto.get("tipoDocumentoId"),
        "tipo_documento_pncp": bruto.get("tipoDocumentoNome"),
        "papel": papel_documento_contrato(bruto.get("tipoDocumentoNome"), titulo),
        "url": bruto.get("url") or bruto.get("uri"),
        "data_publicacao_pncp": bruto.get("dataPublicacaoPncp"),
    }


def _do_papel(arquivos: Iterable[dict[str, Any]], papel: str) -> list[dict[str, Any]]:
    """Todos os documentos ativos de um papel; o escopo exige exatamente um."""
    return [a for a in arquivos if a.get("papel") == papel and a.get("url")]


def inspecionar_compra(pncp: Pncp, compra_bruta: dict[str, Any]) -> dict[str, Any]:
    """Inspeciona primeiro o trio raro; contrato só é consultado se ele existir."""
    numero = compra_bruta["numeroControlePNCP"]
    cnpj, ano, sequencial = partes_controle(numero)
    compra = resumir_compra(compra_bruta)
    base = {
        "numero_controle_pncp": numero,
        "cnpj": cnpj,
        "categoria": compra["categoria_objeto"],
        "tem_trio": False,
        "candidato": None,
    }

    arquivos = [
        resumir_arquivo_compra(a)
        for a in pncp.arquivos_compra(cnpj, ano, sequencial)
        if a.get("statusAtivo", True)
    ]
    por_papel = {papel: _do_papel(arquivos, papel) for papel in (ETP, TR, EDITAL)}
    faltantes = [papel for papel, encontrados in por_papel.items() if not encontrados]
    if faltantes:
        return {
            **base,
            "status": "SEM_TRIO",
            "motivo": f"documentos da contratação ausentes: {', '.join(faltantes)}",
        }
    base["tem_trio"] = True
    duplicados = [papel for papel, encontrados in por_papel.items() if len(encontrados) > 1]
    if duplicados:
        return {
            **base,
            "status": "DUPLICIDADE_DOCUMENTAL",
            "motivo": f"mais de um documento ativo: {', '.join(duplicados)}",
        }
    escolhidos = {papel: encontrados[0] for papel, encontrados in por_papel.items()}

    contratos = pncp.contratos_da_compra(cnpj, ano, sequencial)
    exatos = [
        contrato
        for contrato in contratos
        if contrato.get("numeroControlePncpCompra") == numero
        and _inteiro((contrato.get("tipoContrato") or {}).get("id")) == 1
        and _inteiro((contrato.get("categoriaProcesso") or {}).get("id")) == 2
    ]
    exatos.sort(key=lambda c: c.get("numeroControlePNCP") or "")
    if not exatos:
        return {**base, "status": "SEM_CONTRATO", "motivo": "sem contrato inicial associado"}
    if len(exatos) > 1:
        return {
            **base,
            "status": "DUPLICIDADE_CONTRATO",
            "motivo": "mais de um contrato inicial associado",
        }

    contrato = exatos[0]
    cnpj_contrato = (contrato.get("orgaoEntidade") or {}).get("cnpj") or cnpj
    ano_contrato = _inteiro(contrato.get("anoContrato"))
    sequencial_contrato = _inteiro(contrato.get("sequencialContrato"))
    if ano_contrato is None or sequencial_contrato is None:
        return {**base, "status": "SEM_CONTRATO", "motivo": "identificador contratual inválido"}
    anexos = [
        resumir_arquivo_contrato(a)
        for a in pncp.arquivos_contrato(cnpj_contrato, ano_contrato, sequencial_contrato)
        if a.get("statusAtivo", True)
    ]
    documentos_contrato = _do_papel(anexos, CONTRATO)
    if not documentos_contrato:
        return {
            **base,
            "status": "SEM_ARQUIVO_CONTRATO",
            "motivo": "contrato associado sem instrumento contratual publicado",
        }
    if len(documentos_contrato) > 1:
        return {
            **base,
            "status": "DUPLICIDADE_DOCUMENTAL",
            "motivo": "mais de um instrumento contratual ativo",
        }
    candidato = {
        "numero_controle_pncp": numero,
        "compra": compra,
        "contratos": [resumir_contrato(contrato)],
        "documentos_compra": [escolhidos[ETP], escolhidos[TR], escolhidos[EDITAL]],
        "documento_contrato": documentos_contrato[0],
    }
    return {**base, "status": "COMPLETO", "motivo": None, "candidato": candidato}


def _consultas_publicador(cnpj: str, inicio: str, fim: str) -> list[Consulta]:
    return [
        Consulta(f"orgao:{cnpj}:{a}:{b}", "ORGAO", a, b, cnpj)
        for a, b in janelas_amplas(inicio, fim)
    ]


def _atingiu_alvo(banco: BancoHarvest, cotas: Cotas, reserva: int) -> bool:
    candidatos = [Candidato(c) for c in banco.candidatos_completos()]
    alvo = Cotas(
        processos=cotas.processos + reserva,
        orgaos_distintos=cotas.orgaos_distintos,
        categorias_distintas=cotas.categorias_distintas,
        max_por_orgao=cotas.max_por_orgao,
    )
    selecionados, deficits = selecionar(candidatos, alvo)
    return len(selecionados) >= alvo.processos and not any(deficits.values())


def descobrir(
    pncp: Pncp,
    destino: Path,
    *,
    data_inicial: str,
    data_final: str,
    cotas: Cotas,
    reserva: int = 5,
    workers: int = 6,
    log: Callable[[str], None] = print,
) -> ResultadoDescoberta:
    """Descobre cadeias completas, priorizando órgãos que publicam ETP/TR."""
    banco = BancoHarvest(destino)
    contratacoes_lidas = 0
    publicadores_varridos: set[str] = set()

    def executar(consulta: Consulta, executor: ThreadPoolExecutor) -> bool:
        nonlocal contratacoes_lidas
        estado = banco.iniciar_consulta(consulta)
        if estado["status"] == "CONCLUIDA":
            return True
        pagina = int(estado["proxima_pagina"])
        paginas_globais_sem_federal = 0
        log(
            f"contratações {consulta.tipo.lower()} {consulta.inicio}–{consulta.fim}"
            f"{f' cnpj={consulta.cnpj}' if consulta.cnpj else ''} página {pagina}"
        )
        try:
            while True:
                dados, total = pncp.pagina_contratacoes_publicadas(
                    consulta.inicio,
                    consulta.fim,
                    pagina=pagina,
                    modalidade=6,
                    cnpj=consulta.cnpj,
                )
                contratacoes_lidas += len(dados)
                federais = [
                    compra
                    for compra in dados
                    if (compra.get("orgaoEntidade") or {}).get("esferaId") == "F"
                    and (compra.get("orgaoEntidade") or {}).get("poderId") == "E"
                ]
                if consulta.tipo == "GLOBAL":
                    paginas_globais_sem_federal = (
                        paginas_globais_sem_federal + 1 if not federais else 0
                    )
                dentro = [compra for compra in federais if motivo_compra(compra) is None]
                numeros = [compra["numeroControlePNCP"] for compra in dentro]
                conhecidos = banco.ja_inspecionados(numeros)
                novas = [c for c in dentro if c["numeroControlePNCP"] not in conhecidos]
                for registro in executor.map(lambda compra: inspecionar_compra(pncp, compra), novas):
                    banco.salvar_inspecao(registro)
                    if registro["tem_trio"]:
                        log(
                            f"  trio {registro['numero_controle_pncp']} → {registro['status']}"
                        )
                concluida = total == 0 or pagina >= total
                banco.avancar_consulta(consulta.chave, pagina + 1, concluida)
                completos = len(banco.candidatos_completos())
                log(
                    f"  página {pagina}/{total or 0}: {len(dados)} registros, "
                    f"{len(novas)} novas inspeções, {completos} cadeias completas"
                )
                if (
                    concluida
                    or _atingiu_alvo(banco, cotas, reserva)
                    or (
                        consulta.cnpj is not None
                        and banco.completos_do_orgao(consulta.cnpj) >= cotas.max_por_orgao
                    )
                ):
                    return True
                if consulta.tipo == "GLOBAL" and paginas_globais_sem_federal >= 3:
                    log(
                        "  pausa rápida: 3 páginas consecutivas sem órgão federal; "
                        "a cauda permanece PENDENTE para retomada futura"
                    )
                    return True
                pagina += 1
        except PncpError as erro:
            banco.falhar_consulta(consulta.chave, str(erro))
            log(f"AVISO: consulta pendente por falha da API: {erro}")
            return False

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Falhas de execuções anteriores são sempre tentadas antes de usar
            # o cache para declarar que o alvo foi atingido.
            for consulta in banco.consultas_com_falha():
                executar(consulta, executor)

            # Depois, órgãos já conhecidos como bons publicadores têm prioridade.
            while not _atingiu_alvo(banco, cotas, reserva):
                produtivos = [
                    cnpj
                    for cnpj in banco.publicadores_produtivos()
                    if cnpj not in publicadores_varridos
                    and banco.completos_do_orgao(cnpj) < cotas.max_por_orgao
                ]
                if not produtivos:
                    break
                for cnpj in produtivos:
                    publicadores_varridos.add(cnpj)
                    for consulta in _consultas_publicador(cnpj, data_inicial, data_final):
                        executar(consulta, executor)
                        if _atingiu_alvo(banco, cotas, reserva):
                            break
                    if _atingiu_alvo(banco, cotas, reserva):
                        break
                if _atingiu_alvo(banco, cotas, reserva):
                    break

            if not _atingiu_alvo(banco, cotas, reserva):
                for inicio, fim in janelas_diarias(data_inicial, data_final):
                    executar(Consulta(f"global:{inicio}", "GLOBAL", inicio, fim), executor)
                    if _atingiu_alvo(banco, cotas, reserva):
                        break

                    # Um trio novo dispara imediatamente a varredura barata do órgão.
                    produtivos = [
                        cnpj
                        for cnpj in banco.publicadores_produtivos()
                        if cnpj not in publicadores_varridos
                        and banco.completos_do_orgao(cnpj) < cotas.max_por_orgao
                    ]
                    for cnpj in produtivos:
                        publicadores_varridos.add(cnpj)
                        for consulta in _consultas_publicador(cnpj, data_inicial, data_final):
                            executar(consulta, executor)
                            if banco.completos_do_orgao(cnpj) >= cotas.max_por_orgao:
                                break
                    if _atingiu_alvo(banco, cotas, reserva):
                        break

        candidatos = banco.candidatos_completos()
        pendentes = banco.quantidade_falhas_pendentes()
        log(
            f"rarest-first concluído: {contratacoes_lidas} contratações lidas nesta execução, "
            f"{banco.quantidade_inspecoes()} compras inspecionadas, "
            f"{len(candidatos)} cadeias completas, {pendentes} falhas pendentes"
        )
        return ResultadoDescoberta(
            candidatos=candidatos,
            contratacoes_lidas=contratacoes_lidas,
            compras_inspecionadas=banco.quantidade_inspecoes(),
            rejeitados=banco.quantidade_rejeitados(),
            falhas_api=pendentes,
        )
    finally:
        banco.close()


def invalidar_download(destino: Path, numero: str, motivo: str) -> None:
    """Remove um candidato ilegível do pool para a descoberta buscar substituto."""
    banco = BancoHarvest(destino)
    try:
        banco.invalidar_download(numero, motivo)
    finally:
        banco.close()
