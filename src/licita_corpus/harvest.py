"""Descoberta exclusivamente contract-first no PNCP.

A lista global de contratos publicados é percorrida por período. O campo
``numeroControlePncpCompra`` fornece o elo oficial para a contratação; somente
depois dele consultamos metadados e anexos. Um candidato só é aprovado no
harvest quando os quatro documentos ETP, TR, edital e contrato estão publicados
e o vínculo contratual é exato.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

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


class LinhasJsonl:
    """JSONL incremental deduplicado; só recebe inspeções concluídas."""

    def __init__(self, caminho: Path, chave: Callable[[dict[str, Any]], str]) -> None:
        self.caminho = caminho
        self._chave = chave
        self._registros: dict[str, dict[str, Any]] = {}
        caminho.parent.mkdir(parents=True, exist_ok=True)
        if caminho.exists():
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    registro = json.loads(linha)
                    self._registros[chave(registro)] = registro

    def __contains__(self, chave: str) -> bool:
        return chave in self._registros

    def obter(self, chave: str) -> dict[str, Any] | None:
        return self._registros.get(chave)

    def ler(self) -> list[dict[str, Any]]:
        return list(self._registros.values())

    def adicionar(self, registro: dict[str, Any]) -> None:
        chave = self._chave(registro)
        if chave in self._registros:
            return
        with self.caminho.open("a", encoding="utf-8") as saida:
            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self._registros[chave] = registro


@dataclass(frozen=True, slots=True)
class ResultadoDescoberta:
    candidatos: list[dict[str, Any]]
    contratos_lidos: int
    compras_inspecionadas: int
    rejeitados: int
    falhas_api: int = 0


def _data(valor: str) -> date:
    return datetime.strptime(valor, "%Y%m%d").date()


def janelas_periodo(data_inicial: str, data_final: str) -> list[tuple[str, str]]:
    """Divide o período em dias, evitando paginações profundas e instáveis.

    Continua sendo a consulta oficial por período; apenas usa períodos diários.
    Isso torna cada página retomável e evita que novas publicações alterem
    milhares de páginas de uma consulta anual durante a execução.
    """
    inicio, fim = _data(data_inicial), _data(data_final)
    if inicio > fim:
        raise ValueError("data inicial posterior à data final")
    dias = (fim - inicio).days
    return [
        (
            (fim - timedelta(days=deslocamento)).strftime("%Y%m%d"),
            (fim - timedelta(days=deslocamento)).strftime("%Y%m%d"),
        )
        for deslocamento in range(dias + 1)
    ]


def _inteiro(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)  # respostas reais alternam número e string entre versões
    except (TypeError, ValueError):
        return None


def motivo_contrato_base(contrato: dict[str, Any]) -> str | None:
    """Triagem barata antes de consultar a contratação de origem."""
    orgao = contrato.get("orgaoEntidade") or {}
    if orgao.get("esferaId") != "F":
        return "órgão não federal"
    if orgao.get("poderId") != "E":
        return "fora do Poder Executivo federal"
    if not contrato.get("numeroControlePncpCompra"):
        return "contrato sem numeroControlePncpCompra"
    tipo = contrato.get("tipoContrato") or {}
    if _inteiro(tipo.get("id")) != 1:
        return "não é contrato inicial"
    categoria = contrato.get("categoriaProcesso") or {}
    if _inteiro(categoria.get("id")) != 2 or normalizar(categoria.get("nome", "")) != "compras":
        return "categoria do processo não é Compras"
    return None


def motivo_compra(compra: dict[str, Any]) -> str | None:
    """Gate normativo e material aplicado ao detalhe oficial da contratação."""
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
    objeto = compra.get("objetoCompra") or ""
    if not parece_aquisicao_de_bens(objeto):
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
        "origem_descoberta": "contratos_publicados_pncp",
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


def _escolher(arquivos: Iterable[dict[str, Any]], papel: str) -> dict[str, Any] | None:
    candidatos = [a for a in arquivos if a.get("papel") == papel and a.get("url")]
    if not candidatos:
        return None
    tipo_preferido = {ETP: 7, TR: 4, EDITAL: 2}.get(papel)
    return min(
        candidatos,
        key=lambda a: (
            0 if tipo_preferido is not None and a.get("tipo_documento_id") == tipo_preferido else 1,
            a.get("sequencial_documento") if isinstance(a.get("sequencial_documento"), int) else 10**9,
            a.get("titulo") or "",
        ),
    )


def _inspecionar_candidato(
    pncp: Pncp, contrato_semente: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Resolve uma semente e informa se a contratação pertence ao escopo."""
    numero_compra = contrato_semente["numeroControlePncpCompra"]
    cnpj, ano, sequencial = partes_controle(numero_compra)
    compra_bruta = pncp.compra(cnpj, ano, sequencial)
    if compra_bruta is None:
        return None, "contratação de origem não encontrada", False
    if compra_bruta.get("numeroControlePNCP") != numero_compra:
        return None, "identificador do detalhe da contratação diverge", False
    motivo = motivo_compra(compra_bruta)
    if motivo:
        return None, motivo, False

    arquivos = [
        resumir_arquivo_compra(a)
        for a in pncp.arquivos_compra(cnpj, ano, sequencial)
        if a.get("statusAtivo", True)
    ]
    escolhidos = {papel: _escolher(arquivos, papel) for papel in (ETP, TR, EDITAL)}
    faltantes = [papel for papel, arquivo in escolhidos.items() if arquivo is None]
    if faltantes:
        return None, f"documentos da contratação ausentes: {', '.join(faltantes)}", True

    contratos_brutos = pncp.contratos_da_compra(cnpj, ano, sequencial)
    exatos = [
        c
        for c in contratos_brutos
        if c.get("numeroControlePncpCompra") == numero_compra
        and _inteiro((c.get("tipoContrato") or {}).get("id")) == 1
    ]
    if not exatos:
        return None, "nenhum contrato inicial confirmado pela contratação", True

    numero_semente = contrato_semente.get("numeroControlePNCP")
    exatos.sort(key=lambda c: (c.get("numeroControlePNCP") != numero_semente, c.get("numeroControlePNCP", "")))
    contrato_escolhido = None
    arquivo_contrato = None
    for contrato in exatos:
        cnpj_contrato = (contrato.get("orgaoEntidade") or {}).get("cnpj") or cnpj
        ano_contrato = contrato.get("anoContrato")
        sequencial_contrato = contrato.get("sequencialContrato")
        if not isinstance(ano_contrato, int) or not isinstance(sequencial_contrato, int):
            continue
        arquivos_contrato = [
            resumir_arquivo_contrato(a)
            for a in pncp.arquivos_contrato(cnpj_contrato, ano_contrato, sequencial_contrato)
            if a.get("statusAtivo", True)
        ]
        escolhido = _escolher(arquivos_contrato, CONTRATO)
        if escolhido:
            contrato_escolhido = resumir_contrato(contrato)
            arquivo_contrato = escolhido
            break
    if contrato_escolhido is None or arquivo_contrato is None:
        return None, "contrato vinculado sem instrumento contratual publicado", True

    compra = resumir_compra(compra_bruta)
    return {
        "numero_controle_pncp": numero_compra,
        "compra": compra,
        "contratos": [contrato_escolhido],
        "documentos_compra": [escolhidos[ETP], escolhidos[TR], escolhidos[EDITAL]],
        "documento_contrato": arquivo_contrato,
    }, None, True


def inspecionar_candidato(
    pncp: Pncp, contrato_semente: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Interface pública da inspeção; o terceiro estado é usado pelo harvest."""
    candidato, motivo, _no_escopo = _inspecionar_candidato(pncp, contrato_semente)
    return candidato, motivo


def descobrir(
    pncp: Pncp,
    destino: Path,
    *,
    data_inicial: str,
    data_final: str,
    max_candidatos: int = 100,
    log: Callable[[str], None] = print,
) -> ResultadoDescoberta:
    """Inspeciona até ``max_candidatos`` contratações semeadas por contratos."""
    cache = LinhasJsonl(destino, lambda r: r["numero_controle_pncp"])
    arquivo_falhas = destino.with_name("contract_first_falhas_api.jsonl")
    vistos: set[str] = set()
    contratos_lidos = 0
    inspecionadas = 0
    candidatos_no_escopo = 0
    rejeitados = 0
    falhas_api = 0

    parar = False
    for inicio, fim in janelas_periodo(data_inicial, data_final):
        log(f"contratos publicados: janela {inicio}–{fim}")
        try:
            for contrato in pncp.contratos_publicados(inicio, fim):
                contratos_lidos += 1
                if motivo_contrato_base(contrato):
                    continue
                numero = contrato["numeroControlePncpCompra"]
                if numero in vistos:
                    continue
                vistos.add(numero)

                existente = cache.obter(numero)
                if existente is None:
                    candidato, motivo, no_escopo = _inspecionar_candidato(pncp, contrato)
                    registro = {
                        "numero_controle_pncp": numero,
                        "no_escopo": no_escopo,
                        "aprovado": candidato is not None,
                        "motivo": motivo,
                        "contrato_semente": contrato.get("numeroControlePNCP"),
                        "data_publicacao_semente": contrato.get("dataPublicacaoPncp"),
                        "candidato": candidato,
                    }
                    cache.adicionar(registro)
                    existente = registro
                    inspecionadas += 1
                if existente.get("no_escopo"):
                    candidatos_no_escopo += 1
                    if not existente.get("aprovado"):
                        rejeitados += 1
                    if candidatos_no_escopo % 10 == 0:
                        completos = sum(1 for r in cache.ler() if r.get("aprovado"))
                        log(
                            f"contract-first: {candidatos_no_escopo}/{max_candidatos} candidatos "
                            f"no escopo; {completos} cadeias completas em cache"
                        )
                    if candidatos_no_escopo >= max_candidatos:
                        parar = True
                        break
        except PncpError as erro:
            # Uma janela indisponível permanece explicitamente pendente, mas
            # não impede inspecionar períodos independentes mais antigos.
            # Nunca é transformada em lista vazia nem checkpoint concluído.
            falhas_api += 1
            registro_falha = {
                "data_inicial": inicio,
                "data_final": fim,
                "instante": datetime.now().astimezone().isoformat(),
                "erro": str(erro),
            }
            arquivo_falhas.parent.mkdir(parents=True, exist_ok=True)
            with arquivo_falhas.open("a", encoding="utf-8") as saida:
                saida.write(json.dumps(registro_falha, ensure_ascii=False) + "\n")
            log(f"AVISO: janela {inicio}–{fim} pendente por falha da API: {erro}")
            continue
        if parar:
            break

    candidatos = [
        r["candidato"]
        for r in cache.ler()
        if r.get("aprovado") and isinstance(r.get("candidato"), dict)
    ]
    candidatos.sort(
        key=lambda c: (
            c["contratos"][0].get("data_publicacao_pncp") or "",
            c["numero_controle_pncp"],
        )
    )
    log(
        f"contract-first concluído: {contratos_lidos} contratos lidos, "
        f"{candidatos_no_escopo} contratações no escopo, "
        f"{len(candidatos)} cadeias completas, {falhas_api} janelas pendentes"
    )
    return ResultadoDescoberta(
        candidatos, contratos_lidos, candidatos_no_escopo, rejeitados, falhas_api
    )
