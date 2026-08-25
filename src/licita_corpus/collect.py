"""Coletor R1 exclusivamente contract-first para o PNCP.

Fluxo único:

``contratos publicados → numeroControlePncpCompra → detalhe da contratação →
arquivos ETP/TR/edital → contratos associados → arquivo do contrato → download``.

Um processo só entra no catálogo depois que os quatro documentos abrem
localmente e entregam texto. Falhas da API interrompem a execução e não são
persistidas como ausência de dados.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Sequence

from . import harvest, reuse
from .catalog import (
    documento_id,
    escrever_json,
    escrever_jsonl,
    estatisticas,
    montar_processo,
    montar_relacoes,
)
from .classify import CONTRATO, EDITAL, ETP, TR
from .pncp import Pncp, partes_controle
from .select import Candidato, Cotas, selecionar
from .store import baixar_documento, processo_id
from .verify import verificar

MAX_RODADAS = 8


def _log(mensagem: str) -> None:
    print(mensagem, flush=True)


@dataclass(frozen=True, slots=True)
class Caminhos:
    raiz: Path

    @property
    def harvest(self) -> Path:
        return self.raiz / "harvest"

    @property
    def documentos(self) -> Path:
        return self.raiz / "documentos"

    @property
    def catalogo(self) -> Path:
        return self.raiz / "catalogo"


@dataclass(slots=True)
class ProcessoBaixado:
    candidato: Candidato
    documentos: list[dict[str, Any]]
    aprovado: bool
    motivo: str | None = None
    descartados: list[dict[str, Any]] = field(default_factory=list)


def _registrar_documento(
    identificador: str,
    processo: str,
    arquivo: dict[str, Any],
    baixado: Any,
    origem: str,
    numero_origem: str,
    raiz: Path,
) -> dict[str, Any]:
    resultado = verificar(baixado.caminho)
    return {
        "documento_id": identificador,
        "processo_id": processo,
        "papel": arquivo["papel"],
        "titulo": arquivo.get("titulo") or "",
        "tipo_documento_pncp": arquivo.get("tipo_documento_pncp"),
        "tipo_documento_id": arquivo.get("tipo_documento_id"),
        "origem": origem,
        "numero_controle_pncp_origem": numero_origem,
        "url_fonte": arquivo.get("url"),
        "data_publicacao_pncp": arquivo.get("data_publicacao_pncp"),
        "arquivo": str(baixado.caminho.relative_to(raiz)),
        "nome_original_pncp": baixado.nome_original,
        "sha256": baixado.sha256,
        "bytes": baixado.bytes,
        "extensao": baixado.extensao,
        "content_type": baixado.content_type,
        "verificacao": {
            "abriu": resultado.abriu,
            "paginas": resultado.paginas,
            "caracteres": resultado.caracteres,
            "precisa_ocr": resultado.precisa_ocr,
            "erro": resultado.erro,
        },
        "_texto": resultado.texto,
    }


def baixar_processo(pncp: Pncp, candidato: Candidato, caminhos: Caminhos) -> ProcessoBaixado:
    """Baixa exatamente um ETP, um TR, um edital e um contrato."""
    numero = candidato.numero
    pid = processo_id(numero)
    destino = caminhos.documentos / pid
    documentos: list[dict[str, Any]] = []

    for ordem, arquivo in enumerate(candidato.documentos_compra, start=1):
        baixado = baixar_documento(
            pncp,
            arquivo["url"],
            destino,
            arquivo["papel"],
            arquivo.get("sequencial_documento"),
            arquivo.get("titulo", ""),
        )
        if baixado is None:
            continue
        documentos.append(
            _registrar_documento(
                documento_id(pid, arquivo["papel"], arquivo.get("sequencial_documento"), ordem),
                pid,
                arquivo,
                baixado,
                "compra",
                numero,
                caminhos.raiz,
            )
        )

    contrato = candidato.contratos[0]
    arquivo = candidato.documento_contrato
    baixado = baixar_documento(
        pncp,
        arquivo["url"],
        destino,
        CONTRATO,
        arquivo.get("sequencial_documento"),
        f"c{contrato['sequencial_contrato']}-{arquivo.get('titulo', '')}",
    )
    if baixado is not None:
        documentos.append(
            _registrar_documento(
                documento_id(pid, CONTRATO, arquivo.get("sequencial_documento"), 4),
                pid,
                arquivo,
                baixado,
                "contrato",
                contrato["numero_controle_pncp"],
                caminhos.raiz,
            )
        )

    aproveitados: list[dict[str, Any]] = []
    descartados: list[dict[str, Any]] = []
    for documento in documentos:
        verificacao = documento["verificacao"]
        if not verificacao["abriu"]:
            descartados.append({**documento, "motivo_descarte": verificacao["erro"] or "não abriu"})
        elif verificacao["precisa_ocr"]:
            descartados.append({**documento, "motivo_descarte": "arquivo sem texto utilizável"})
        else:
            aproveitados.append(documento)

    por_papel = {d["papel"] for d in aproveitados}
    ausentes = [p for p in (ETP, TR, EDITAL, CONTRATO) if p not in por_papel]
    if ausentes:
        return ProcessoBaixado(
            candidato,
            aproveitados,
            False,
            f"documentos não utilizáveis após download: {', '.join(ausentes)}",
            descartados,
        )
    if len(aproveitados) != 4:
        return ProcessoBaixado(
            candidato, aproveitados, False, "cadeia não contém exatamente quatro documentos", descartados
        )
    return ProcessoBaixado(candidato, aproveitados, True, descartados=descartados)


def _extras_do_processo(pncp: Pncp, candidato: Candidato, caminhos: Caminhos) -> dict[str, Any]:
    compra = candidato.compra
    cnpj, ano, sequencial = partes_controle(candidato.numero)
    itens = pncp.itens_compra(cnpj, ano, sequencial)
    arquivo_itens = None
    if itens:
        destino = caminhos.documentos / processo_id(candidato.numero) / "itens.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(itens, ensure_ascii=False, indent=2), encoding="utf-8")
        arquivo_itens = str(destino.relative_to(caminhos.raiz))
    contrato = candidato.contratos[0]
    return {
        "processo_administrativo": compra.get("processo") or contrato.get("processo"),
        "processo_administrativo_fonte": "detalhe_contratacao_pncp",
        "valor_total_estimado_itens": compra.get("valor_global")
        or sum(i.get("valorTotal") or 0 for i in itens)
        or None,
        "quantidade_itens": len(itens) or None,
        "arquivo_itens": arquivo_itens,
    }


def coletar(
    raiz: Path,
    *,
    data_inicial: str = "20240101",
    data_final: str | None = None,
    max_candidatos: int = 100,
    cotas: Cotas = Cotas(),
    log: Callable[[str], None] = _log,
) -> dict[str, Any]:
    caminhos = Caminhos(raiz)
    data_final = data_final or date.today().strftime("%Y%m%d")

    with Pncp() as pncp:
        descoberta = harvest.descobrir(
            pncp,
            caminhos.harvest / "contract_first.jsonl",
            data_inicial=data_inicial,
            data_final=data_final,
            max_candidatos=max_candidatos,
            log=log,
        )
        candidatos = [Candidato(registro) for registro in descoberta.candidatos]
        aprovados: list[Candidato] = []
        documentos: list[dict[str, Any]] = []
        descartados: list[dict[str, Any]] = []
        reprovados: list[dict[str, str]] = []
        banidos: set[str] = set()

        for rodada in range(1, MAX_RODADAS + 1):
            disponiveis = [c for c in candidatos if c.numero not in banidos]
            selecao, deficits = selecionar(disponiveis, cotas, iniciais=aprovados)
            novos = [c for c in selecao if c.numero not in {a.numero for a in aprovados}]
            if not novos:
                log(f"rodada {rodada}: sem substitutos; déficits {deficits}")
                break
            log(f"rodada {rodada}: baixando {len(novos)} cadeias completas")
            for candidato in novos:
                resultado = baixar_processo(pncp, candidato, caminhos)
                if resultado.aprovado:
                    aprovados.append(candidato)
                    documentos.extend(resultado.documentos)
                    descartados.extend(resultado.descartados)
                    log(f"  ok  {candidato.numero}")
                else:
                    banidos.add(candidato.numero)
                    reprovados.append(
                        {"numero_controle_pncp": candidato.numero, "motivo": resultado.motivo or ""}
                    )
                    descartados.extend(resultado.descartados)
                    log(f"  x   {candidato.numero}: {resultado.motivo}")
            _, deficits = selecionar([], cotas, iniciais=aprovados)
            if not any(deficits.values()):
                break

        extras = {c.numero: _extras_do_processo(pncp, c, caminhos) for c in aprovados}

    return montar_catalogo(
        caminhos,
        aprovados,
        documentos,
        extras,
        reprovados,
        descartados,
        cotas,
        descoberta,
        log,
    )


def montar_catalogo(
    caminhos: Caminhos,
    aprovados: Sequence[Candidato],
    documentos: list[dict[str, Any]],
    extras: dict[str, Any],
    reprovados: Sequence[dict[str, str]],
    descartados: Sequence[dict[str, Any]],
    cotas: Cotas,
    descoberta: harvest.ResultadoDescoberta,
    log: Callable[[str], None] = _log,
) -> dict[str, Any]:
    textos = {d["documento_id"]: d.pop("_texto", "") for d in documentos}
    for descartado in descartados:
        descartado.pop("_texto", None)
    por_processo: dict[str, list[dict[str, Any]]] = {}
    for documento in documentos:
        por_processo.setdefault(documento["processo_id"], []).append(documento)

    processos: list[dict[str, Any]] = []
    relacoes: list[dict[str, str]] = []
    for candidato in aprovados:
        pid = processo_id(candidato.numero)
        registro = montar_processo(
            candidato.compra,
            extras.get(candidato.numero),
            por_processo.get(pid, []),
            candidato.contratos,
        )
        processos.append(registro)
        relacoes.extend(montar_relacoes(pid, registro["cadeia"]))
        escrever_json(caminhos.documentos / pid / "metadata.json", registro)

    marcas = reuse.detectar(
        [
            reuse.DocumentoTexto(
                d["documento_id"], d["processo_id"], d["papel"], d["sha256"], textos.get(d["documento_id"], "")
            )
            for d in documentos
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
    for documento in documentos:
        documento["reuso"] = por_documento.get(documento["documento_id"], [])

    escrever_json(caminhos.catalogo / "processos.json", processos)
    escrever_jsonl(caminhos.catalogo / "documentos.jsonl", documentos)
    escrever_json(
        caminhos.catalogo / "relacoes.json",
        {
            "cadeia": relacoes,
            "reuso": [asdict(m) for m in marcas],
            "resumo_reuso": reuse.resumir(marcas),
        },
    )
    escrever_json(
        caminhos.catalogo / "processos_reprovados.json",
        {
            "processos": list(reprovados),
            "documentos": [
                {
                    "documento_id": d["documento_id"],
                    "processo_id": d["processo_id"],
                    "papel": d["papel"],
                    "arquivo": d["arquivo"],
                    "motivo": d["motivo_descarte"],
                }
                for d in descartados
            ],
        },
    )

    resumo = estatisticas(processos, documentos)
    resumo.update(
        {
            "estrategia": "pncp_contract_first",
            "contratos_lidos": descoberta.contratos_lidos,
            "candidatos_inspecionados": descoberta.compras_inspecionadas,
            "candidatos_com_cadeia_publicada": len(descoberta.candidatos),
            "processos_reprovados_no_download": len(reprovados),
            "cotas": asdict(cotas),
            "marcas_de_reuso": reuse.resumir(marcas),
        }
    )
    escrever_json(caminhos.catalogo / "estatisticas.json", resumo)
    log(json.dumps(resumo, ensure_ascii=False, indent=2))
    return resumo


def principal(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Coleta corpus PNCP a partir dos contratos publicados.")
    parser.add_argument("--raiz", type=Path, default=Path("corpus"))
    parser.add_argument("--data-inicial", default="20240101")
    parser.add_argument("--data-final", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--candidatos", type=int, default=100)
    parser.add_argument("--processos", type=int, default=30)
    parser.add_argument("--orgaos", type=int, default=5)
    parser.add_argument("--categorias", type=int, default=3)
    parser.add_argument("--max-por-orgao", type=int, default=6)
    argumentos = parser.parse_args(argv)

    cotas = Cotas(
        processos=argumentos.processos,
        orgaos_distintos=argumentos.orgaos,
        categorias_distintas=argumentos.categorias,
        max_por_orgao=argumentos.max_por_orgao,
    )
    resumo = coletar(
        argumentos.raiz,
        data_inicial=argumentos.data_inicial,
        data_final=argumentos.data_final,
        max_candidatos=argumentos.candidatos,
        cotas=cotas,
    )
    return 0 if resumo["processos"] >= cotas.processos else 1


if __name__ == "__main__":
    sys.exit(principal())
