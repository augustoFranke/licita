"""Gate independente do lote municipal de pares ETP→TR."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .catalog import PAPEIS_OBRIGATORIOS, escrever_json
from .classify import (
    PERFIL_MUNICIPAL_14133_PREGAO_ELETRONICO_BENS,
    PERFIL_SUPPORTED,
    classificar_perfil_inicial,
)
from .verify import sha256_arquivo, verificar


ESFERAS_MUNICIPAIS = frozenset({"M"})


@dataclass(slots=True)
class Criterio:
    nome: str
    exigido: str
    obtido: str
    passou: bool


def _ler(
    raiz: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    catalogo = raiz / "catalogo"
    processos = json.loads((catalogo / "processos.json").read_text(encoding="utf-8"))
    documentos = [
        json.loads(linha)
        for linha in (catalogo / "documentos.jsonl").read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]
    relacoes = json.loads((catalogo / "relacoes.json").read_text(encoding="utf-8"))
    return processos, documentos, relacoes


def _int(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _atributo(resultado: Any, nome: str, padrao: Any = None) -> Any:
    if isinstance(resultado, Mapping):
        return resultado.get(nome, padrao)
    return getattr(resultado, nome, padrao)


def _metadados(documento: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    verificacao_bruta = documento.get("verificacao")
    verificacao = verificacao_bruta if isinstance(verificacao_bruta, Mapping) else {}
    ocr_bruto = verificacao.get("ocr") or documento.get("ocr")
    ocr = ocr_bruto if isinstance(ocr_bruto, Mapping) else {}
    return verificacao, ocr


def _ocr_historico_utilizavel(documento: Mapping[str, Any], *, abriu: bool) -> bool:
    verificacao, ocr = _metadados(documento)
    cache_bruto = verificacao.get("ocr_cache") or documento.get("ocr_cache")
    cache = cache_bruto if isinstance(cache_bruto, Mapping) else {}
    texto_sha256 = str(cache.get("texto_sha256") or "").strip().lower()
    derivado_auditavel = bool(
        re.fullmatch(r"[0-9a-f]{64}", texto_sha256)
        and str(cache.get("pipeline_version") or "").strip()
        and str(cache.get("idioma") or "").strip()
    )
    usado = bool(
        verificacao.get("ocr_usado")
        or documento.get("ocr_usado")
        or ocr.get("usado")
    )
    try:
        caracteres = int(
            verificacao.get("caracteres", documento.get("caracteres", 0)) or 0
        )
    except (TypeError, ValueError):
        caracteres = 0
    texto = (
        documento.get("_texto")
        or verificacao.get("texto")
        or documento.get("texto")
        or ""
    )
    precisa_ocr = bool(
        verificacao.get("precisa_ocr", documento.get("precisa_ocr", False))
    )
    return bool(
        abriu
        and usado
        and derivado_auditavel
        and (caracteres > 0 or str(texto).strip())
        and not precisa_ocr
    )


def _validar_documento(
    raiz: Path, documento: Mapping[str, Any]
) -> tuple[bool, str | None]:
    relativo = documento.get("arquivo")
    if not relativo:
        return False, "arquivo ausente"
    caminho = Path(str(relativo))
    if not caminho.is_absolute():
        caminho = raiz / caminho
    if not caminho.exists() or not caminho.is_file():
        return False, "arquivo ausente"

    # O original é autoritativo. Os campos sem sufixo existem apenas como
    # fallback para catálogos anteriores à preservação explícita do original.
    esperado = (
        documento.get("sha256_original")
        or documento.get("hash_original")
        or documento.get("sha256")
        or documento.get("hash")
    )
    if not esperado or sha256_arquivo(caminho) != str(esperado):
        return False, "SHA-256 divergente"

    try:
        resultado = verificar(caminho)
    except Exception as erro:  # falha do parser também é falha de abertura
        return False, str(erro) or "não abriu"
    abriu = bool(_atributo(resultado, "abriu", False))
    if not abriu:
        return False, _atributo(resultado, "erro") or "não abriu"

    utilizavel_normal = bool(_atributo(resultado, "utilizavel", False))
    if utilizavel_normal or _ocr_historico_utilizavel(documento, abriu=abriu):
        return True, None
    return False, "arquivo sem texto utilizável"


def _perfil_atual(processo: Mapping[str, Any]) -> str:
    compra = processo.get("compra") or {}
    orgao = processo.get("orgao") or {}
    return classificar_perfil_inicial(
        esfera=orgao.get("esfera"),
        amparo_legal_nome=compra.get("amparo_legal_nome"),
        modalidade_id=compra.get("modalidade_id"),
        objeto=processo.get("objeto") or "",
    )


def conferir(
    raiz: Path,
    minimo_processos: int = 15,
    max_por_orgao: int | None = 5,
    minimo_orgaos: int = 5,
    esferas: set[str] | frozenset[str] | None = ESFERAS_MUNICIPAIS,
    minimo_categorias: int = 3,
) -> dict[str, Any]:
    permitidas = {"M"} if esferas is None else {
        str(esfera).strip().upper() for esfera in esferas if str(esfera).strip()
    }
    if permitidas != {"M"}:
        raise ValueError("esferas deve conter somente M")
    if minimo_categorias < 1:
        raise ValueError("minimo_categorias deve ser positivo")

    processos, documentos, relacoes = _ler(raiz)
    falhas: list[dict[str, str]] = []
    documentos_validos: dict[str, bool] = {}
    por_processo: dict[str, list[dict[str, Any]]] = {}
    for documento in documentos:
        identificador = str(documento.get("documento_id") or "")
        valido, erro = _validar_documento(raiz, documento)
        documentos_validos[identificador] = valido
        pid = str(documento.get("processo_id") or "")
        por_processo.setdefault(pid, []).append(documento)
        if erro:
            falhas.append({"documento_id": identificador, "erro": erro})

    arestas_etp_tr: dict[str, set[tuple[str, str]]] = {}
    for aresta in relacoes.get("cadeia", []):
        if aresta.get("de_papel") != "ETP" or aresta.get("para_papel") != "TR":
            continue
        arestas_etp_tr.setdefault(str(aresta.get("processo_id") or ""), set()).add(
            (str(aresta.get("de") or ""), str(aresta.get("para") or ""))
        )

    elegiveis: list[dict[str, Any]] = []
    perfis_supported: list[dict[str, Any]] = []
    supported_com_par_exato = 0
    supported_com_documentos_utilizaveis = 0
    supported_com_relacao = 0
    documentos_validos_supported = 0
    processos_sem_relacoes: set[str] = set()
    for processo in processos:
        pid = str(processo.get("processo_id") or "")
        compra = processo.get("compra") or {}
        perfil = _perfil_atual(processo)  # nunca confie no valor persistido
        filtro_codigos = (
            _int(compra.get("instrumento_convocatorio_codigo")) == 1
            and _int(compra.get("amparo_legal_codigo")) == 1
        )
        if perfil != PERFIL_SUPPORTED or not filtro_codigos:
            continue
        perfis_supported.append(processo)

        cadeia = processo.get("cadeia") or {}
        exato_na_cadeia = all(
            len(cadeia.get(papel) or []) == 1 for papel in PAPEIS_OBRIGATORIOS
        ) and all(
            not ids
            for papel, ids in cadeia.items()
            if papel not in PAPEIS_OBRIGATORIOS
        )
        ids_esperados = {
            str((cadeia.get(papel) or [""])[0])
            for papel in PAPEIS_OBRIGATORIOS
            if cadeia.get(papel)
        }
        registros = por_processo.get(pid, [])
        ids_registrados = {str(d.get("documento_id") or "") for d in registros}
        documentos_exatos = (
            len(registros) == 2
            and {d.get("papel") for d in registros} == set(PAPEIS_OBRIGATORIOS)
            and ids_registrados == ids_esperados
        )
        utilizaveis = documentos_exatos and all(
            documentos_validos.get(identificador, False)
            for identificador in ids_esperados
        )
        etp_ids = cadeia.get("ETP") or []
        tr_ids = cadeia.get("TR") or []
        aresta_esperada = (
            str(etp_ids[0]) if len(etp_ids) == 1 else "",
            str(tr_ids[0]) if len(tr_ids) == 1 else "",
        )
        tem_relacao = aresta_esperada in arestas_etp_tr.get(pid, set())
        if exato_na_cadeia and documentos_exatos:
            supported_com_par_exato += 1
            documentos_validos_supported += sum(
                bool(documentos_validos.get(identificador, False))
                for identificador in ids_esperados
            )
        if exato_na_cadeia and documentos_exatos and utilizaveis:
            supported_com_documentos_utilizaveis += 1
        if tem_relacao:
            supported_com_relacao += 1
        if exato_na_cadeia and documentos_exatos and utilizaveis and not tem_relacao:
            processos_sem_relacoes.add(pid)
        if exato_na_cadeia and documentos_exatos and utilizaveis and tem_relacao:
            elegiveis.append(processo)

    orgaos = {
        p.get("orgao", {}).get("cnpj")
        for p in elegiveis
        if p.get("orgao", {}).get("cnpj")
    }
    por_orgao = Counter(
        p.get("orgao", {}).get("cnpj")
        for p in elegiveis
        if p.get("orgao", {}).get("cnpj")
    )
    maior_orgao = max(por_orgao.values(), default=0)
    categorias = {
        p.get("categoria_objeto")
        for p in elegiveis
        if p.get("categoria_objeto")
    }

    # Diferentemente dos denominadores de qualidade, a esfera cobre todos os
    # registros publicados: ausente ou F/E/D nunca pode ser ocultado como fora
    # do perfil.
    esferas_obtidas = {
        str((p.get("orgao") or {}).get("esfera") or "").strip().upper()
        or "AUSENTE"
        for p in processos
    }
    esfera_ok = bool(processos) and esferas_obtidas == {"M"}

    documentos_elegiveis = [
        documento
        for processo in elegiveis
        for documento in por_processo.get(str(processo.get("processo_id") or ""), [])
    ]
    contratos_no_catalogo = [p for p in processos if p.get("contratos")]
    contratos_validos = [
        p
        for p in contratos_no_catalogo
        if all(
            contrato.get("numero_controle_pncp_compra")
            == p.get("numero_controle_pncp")
            and contrato.get("criterio_vinculo")
            == "numeroControlePncpCompra"
            for contrato in p.get("contratos") or []
        )
    ]
    papeis_fora = [
        d for d in documentos_elegiveis if d.get("papel") not in PAPEIS_OBRIGATORIOS
    ]

    criterios = [
        Criterio("processos", f"≥{minimo_processos}", str(len(elegiveis)), len(elegiveis) >= minimo_processos),
        Criterio("órgãos distintos", f"≥{minimo_orgaos}", str(len(orgaos)), len(orgaos) >= minimo_orgaos),
        Criterio(
            "máximo por órgão",
            "sem limite" if max_por_orgao is None else f"≤{max_por_orgao}",
            str(maior_orgao),
            max_por_orgao is None or (bool(elegiveis) and maior_orgao <= max_por_orgao),
        ),
        Criterio("categorias distintas", f"≥{minimo_categorias}", str(len(categorias)), len(categorias) >= minimo_categorias),
        Criterio("esferas permitidas", "M", ",".join(sorted(esferas_obtidas)) or "—", esfera_ok),
        Criterio(
            f"perfil {PERFIL_MUNICIPAL_14133_PREGAO_ELETRONICO_BENS}",
            f"≥{minimo_processos}",
            str(len(perfis_supported)),
            len(perfis_supported) >= minimo_processos,
        ),
        Criterio("processos no filtro Lei 14.133/Pregão/bens", f"≥{minimo_processos}", str(len(elegiveis)), len(elegiveis) >= minimo_processos),
        Criterio(
            "processos SUPPORTED com exatamente um ETP e um TR",
            str(len(perfis_supported)),
            str(supported_com_par_exato),
            bool(perfis_supported) and supported_com_par_exato == len(perfis_supported),
        ),
        Criterio(
            "processos SUPPORTED com documentos utilizáveis localmente",
            str(len(perfis_supported)),
            str(supported_com_documentos_utilizaveis),
            bool(perfis_supported)
            and supported_com_documentos_utilizaveis == len(perfis_supported)
            and documentos_validos_supported == 2 * len(perfis_supported),
        ),
        Criterio(
            "relações ETP→TR catalogadas",
            f"{len(perfis_supported)} processos",
            f"{supported_com_relacao} processos",
            bool(perfis_supported) and supported_com_relacao == len(perfis_supported),
        ),
        Criterio(
            "vínculos válidos dos contratos presentes",
            str(len(contratos_no_catalogo)),
            str(len(contratos_validos)),
            len(contratos_validos) == len(contratos_no_catalogo),
        ),
        Criterio("somente documentos ETP/TR", "0 extras", str(len(papeis_fora)), not papeis_fora),
        Criterio("sem contratos no lote", "0", str(len(contratos_no_catalogo)), not contratos_no_catalogo),
    ]
    for papel in PAPEIS_OBRIGATORIOS:
        quantos = sum(1 for d in documentos_elegiveis if d.get("papel") == papel)
        criterios.append(Criterio(f"documentos {papel}", f"≥{minimo_processos}", str(quantos), quantos >= minimo_processos))

    return {
        "passou": all(c.passou for c in criterios),
        "perfil_id": PERFIL_MUNICIPAL_14133_PREGAO_ELETRONICO_BENS,
        "processos_elegiveis": len(elegiveis),
        "processos_elegiveis_ids": sorted(
            str(processo.get("processo_id") or "") for processo in elegiveis
        ),
        "processos_out_of_scope_ids": sorted(
            str(processo.get("processo_id") or "")
            for processo in processos
            if processo not in elegiveis
        ),
        "criterios": [asdict(c) for c in criterios],
        "falhas_de_abertura": falhas,
        "processos_sem_relacoes": sorted(processos_sem_relacoes),
    }


def como_markdown(raiz: Path, resultado: dict[str, Any]) -> str:
    processos, documentos, _ = _ler(raiz)
    linhas = [
        "# Gate do lote ETP→TR",
        "",
        f"**Resultado: {'PASSOU' if resultado['passou'] else 'NÃO PASSOU'}**",
        "",
        "Verificação independente: cada arquivo catalogado foi reaberto a partir",
        "do disco e conferido pelo SHA-256 original. Texto OCR histórico só conta",
        "quando possui idioma, versão do pipeline e SHA-256 do derivado auditável.",
        "Este lote não baixa editais nem consulta contratos.",
        "",
        "| Critério | Exigido | Obtido | |",
        "|---|---|---|---|",
    ]
    for criterio in resultado["criterios"]:
        marca = "✅" if criterio["passou"] else "❌"
        linhas.append(
            f"| {criterio['nome']} | {criterio['exigido']} | {criterio['obtido']} | {marca} |"
        )

    linhas += [
        "",
        "## Processos",
        "",
        "| # | Processo | Órgão | UF | Categoria | Escopo | ETP | TR |",
        "|---|---|---|---|---|---|---|---|",
    ]
    elegiveis_ids = set(resultado.get("processos_elegiveis_ids") or [])
    for posicao, processo in enumerate(
        sorted(processos, key=lambda p: p["processo_id"]), start=1
    ):
        cadeia = processo["cadeia"]
        linhas.append(
            f"| {posicao} | [{processo['numero_controle_pncp']}]"
            f"({processo['fontes']['portal_pncp']}) | "
            f"{processo['orgao'].get('razao_social') or '—'} | "
            f"{processo['orgao'].get('uf') or '—'} | "
            f"{processo.get('categoria_objeto') or '—'} | "
            f"{'SUPPORTED' if processo.get('processo_id') in elegiveis_ids else 'OUT_OF_SCOPE'} | "
            f"{len(cadeia.get('ETP') or [])} | {len(cadeia.get('TR') or [])} |"
        )
    if resultado["falhas_de_abertura"]:
        linhas += ["", "## Documentos que não abriram", ""]
        for falha in resultado["falhas_de_abertura"]:
            linhas.append(f"- `{falha['documento_id']}`: {falha['erro']}")
    linhas += ["", f"Total de documentos: **{len(documentos)}**.", ""]
    return "\n".join(linhas)


def principal(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verifica o lote municipal local de pares ETP→TR.")
    parser.add_argument("--raiz", type=Path, default=Path("corpus"))
    parser.add_argument("--processos", type=int, default=15)
    parser.add_argument("--orgaos", type=int, default=5)
    parser.add_argument("--max-por-orgao", type=int, default=5)
    parser.add_argument("--categorias", type=int, default=3)
    parser.add_argument("--esferas", choices=("M",), default="M")
    argumentos = parser.parse_args(argv)
    resultado = conferir(
        argumentos.raiz,
        minimo_processos=argumentos.processos,
        max_por_orgao=argumentos.max_por_orgao,
        minimo_orgaos=argumentos.orgaos,
        esferas={argumentos.esferas},
        minimo_categorias=argumentos.categorias,
    )
    escrever_json(argumentos.raiz / "catalogo" / "gate.json", resultado)
    markdown = como_markdown(argumentos.raiz, resultado)
    (argumentos.raiz / "GATE_R1.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if resultado["passou"] else 1


if __name__ == "__main__":
    raise SystemExit(principal())
