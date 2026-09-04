"""Gate independente do corpus histórico e das novas cadeias completas."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .catalog import (
    PAPEIS_DO_LOTE,
    PAPEIS_CADEIA_COMPLETA,
    PAPEIS_PAR_ETP_TR,
    _contrato_vincula_processo,
    escrever_json,
    ocr_historico_utilizavel,
)
from .classify import (
    ESFERAS_SUPORTADAS,
    PERFIL_PUBLICO_14133_PREGAO_ELETRONICO_BENS,
    PERFIL_SUPPORTED,
    classificar_perfil_inicial,
)
from .verify import sha256_arquivo, verificar


#: Fonte única das esferas do perfil (ver ``classify.ESFERAS_SUPORTADAS``).
ESFERAS_PERMITIDAS = ESFERAS_SUPORTADAS
POLICY_CADEIA_COMPLETA = "8-cadeia-completa-documentos-utilizaveis"


def _eh_cadeia_nova(processo: Mapping[str, Any]) -> bool:
    """Identifica a regra documental aplicada ao manifesto.

    Apenas a versão vigente prova que o aceite percorreu o fluxo atual de
    quatro documentos. Metadados antigos podem mencionar os quatro papéis,
    mas continuam históricos até serem promovidos pela policy vigente.
    """
    return processo.get("collection_policy_version") == POLICY_CADEIA_COMPLETA


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
    if utilizavel_normal or ocr_historico_utilizavel(documento, abriu=abriu):
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
    esferas: set[str] | frozenset[str] | None = ESFERAS_PERMITIDAS,
    minimo_categorias: int = 3,
) -> dict[str, Any]:
    permitidas = set(ESFERAS_PERMITIDAS) if esferas is None else {
        str(esfera).strip().upper() for esfera in esferas if str(esfera).strip()
    }
    if not permitidas or not permitidas <= set(ESFERAS_PERMITIDAS):
        raise ValueError(
            f"esferas deve ser um subconjunto não vazio de "
            f"{sorted(ESFERAS_PERMITIDAS)}"
        )
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

    # Um catálogo pode preservar processos históricos de ETP/TR que não foram
    # recolhidos sob a regra vigente. Quando o lote novo existe, R1 prova esse
    # lote — os históricos seguem auditáveis, mas não podem reprová-lo nem
    # elevar suas contagens.
    processos_novos_catalogados = [
        processo for processo in processos if _eh_cadeia_nova(processo)
    ]
    avaliar_somente_novos = bool(processos_novos_catalogados)
    processos_do_lote = (
        processos_novos_catalogados if avaliar_somente_novos else processos
    )

    elegiveis: list[dict[str, Any]] = []
    perfis_supported: list[dict[str, Any]] = []
    supported_com_par_exato = 0
    supported_com_documentos_utilizaveis = 0
    documentos_esperados_supported = 0
    supported_com_relacao = 0
    supported_novos_com_cadeia = 0
    novos_com_contrato_vinculado = 0
    documentos_validos_supported = 0
    processos_sem_relacoes: set[str] = set()
    for processo in processos:
        if avaliar_somente_novos and not _eh_cadeia_nova(processo):
            continue
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
        # Registros sem a versão nova são históricos: continuam aprováveis com
        # o contrato documental original de ETP/TR (edital/contrato eram
        # enriquecimentos opcionais). A policy nova exige os quatro elos e um
        # contrato explicitamente vinculado à compra.
        cadeia_nova = _eh_cadeia_nova(processo)
        papeis_obrigatorios = PAPEIS_CADEIA_COMPLETA if cadeia_nova else PAPEIS_PAR_ETP_TR
        papeis_opcionais = () if cadeia_nova else ("EDITAL", "CONTRATO")
        papeis_documentais = set(PAPEIS_DO_LOTE)
        # Papel fora do lote continua barrado, e duplicata de qualquer elo
        # desfaz a correspondência um-a-um.
        exato_na_cadeia = (
            all(len(cadeia.get(papel) or []) == 1 for papel in papeis_obrigatorios)
            and all(len(cadeia.get(papel) or []) <= 1 for papel in papeis_opcionais)
            and all(
                not ids
                for papel, ids in cadeia.items()
                if papel not in papeis_documentais
            )
        )
        papeis_presentes = [papel for papel in PAPEIS_DO_LOTE if cadeia.get(papel)]
        ids_esperados = {
            str((cadeia.get(papel) or [""])[0]) for papel in papeis_presentes
        }
        registros = por_processo.get(pid, [])
        ids_registrados = {str(d.get("documento_id") or "") for d in registros}
        documentos_exatos = (
            len(registros) == len(papeis_presentes)
            and set(papeis_obrigatorios) <= {d.get("papel") for d in registros}
            and {d.get("papel") for d in registros} <= papeis_documentais
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
        # ``montar_relacoes`` liga os elos materiais presentes em sequência.
        # Para a policy nova, confira também TR→EDITAL→CONTRATO; o par ETP/TR
        # continua sendo uma relação independente para catálogos históricos.
        relacoes_processo = {
            (
                str(aresta.get("de") or ""),
                str(aresta.get("para") or ""),
                str(aresta.get("de_papel") or ""),
                str(aresta.get("para_papel") or ""),
            )
            for aresta in relacoes.get("cadeia", [])
            if str(aresta.get("processo_id") or "") == pid
        }
        relacoes_esperadas = []
        for origem, destino in zip(PAPEIS_CADEIA_COMPLETA, PAPEIS_CADEIA_COMPLETA[1:]):
            ids_origem = cadeia.get(origem) or []
            ids_destino = cadeia.get(destino) or []
            if len(ids_origem) == 1 and len(ids_destino) == 1:
                relacoes_esperadas.append(
                    (str(ids_origem[0]), str(ids_destino[0]), origem, destino)
                )
        tem_relacao_cadeia = bool(relacoes_esperadas) and all(
            relacao in relacoes_processo for relacao in relacoes_esperadas
        )
        tem_relacao_documental = tem_relacao_cadeia if cadeia_nova else tem_relacao
        contratos = processo.get("contratos") or []
        contratos_no_processo = [c for c in contratos if isinstance(c, Mapping)]
        contrato_vinculo_exato = bool(contratos_no_processo) and all(
            c.get("numero_controle_pncp_compra") == processo.get("numero_controle_pncp")
            and c.get("criterio_vinculo") == "numeroControlePncpCompra"
            for c in contratos_no_processo
        )
        contrato_exigido_ok = (
            len(contratos_no_processo) == 1 and contrato_vinculo_exato
            if cadeia_nova
            else True
        )
        if exato_na_cadeia and documentos_exatos:
            supported_com_par_exato += 1
            # O total esperado varia por processo: os obrigatórios mais os elos
            # opcionais que o ente publicou. Presumir dois por processo
            # reprovaria justamente quem tem a cadeia mais completa.
            documentos_esperados_supported += len(ids_esperados)
            documentos_validos_supported += sum(
                bool(documentos_validos.get(identificador, False))
                for identificador in ids_esperados
            )
        if exato_na_cadeia and documentos_exatos and utilizaveis:
            supported_com_documentos_utilizaveis += 1
        if exato_na_cadeia and tem_relacao_documental:
            supported_com_relacao += 1
        if cadeia_nova and exato_na_cadeia and documentos_exatos and utilizaveis and tem_relacao_documental:
            supported_novos_com_cadeia += 1
        if cadeia_nova and contrato_exigido_ok:
            novos_com_contrato_vinculado += 1
        if exato_na_cadeia and documentos_exatos and utilizaveis and not tem_relacao_documental:
            processos_sem_relacoes.add(pid)
        if (
            exato_na_cadeia
            and documentos_exatos
            and utilizaveis
            and tem_relacao_documental
            and contrato_exigido_ok
        ):
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
    # registros publicados: uma esfera ausente ou fora das permitidas nunca
    # pode ser ocultada como fora do perfil.
    esferas_obtidas = {
        str((p.get("orgao") or {}).get("esfera") or "").strip().upper()
        or "AUSENTE"
        for p in processos_do_lote
    }
    esfera_ok = bool(processos) and esferas_obtidas <= permitidas

    documentos_elegiveis = [
        documento
        for processo in elegiveis
        for documento in por_processo.get(str(processo.get("processo_id") or ""), [])
    ]
    contratos_no_catalogo = [p for p in processos_do_lote if p.get("contratos")]
    contratos_validos = []
    for processo in contratos_no_catalogo:
        contratos = processo.get("contratos") or []
        if not isinstance(contratos, list) or not all(
            isinstance(contrato, Mapping) for contrato in contratos
        ):
            continue
        if all(
            contrato.get("numero_controle_pncp_compra")
            == processo.get("numero_controle_pncp")
            and contrato.get("criterio_vinculo")
            == "numeroControlePncpCompra"
            for contrato in contratos
        ):
            contratos_validos.append(processo)
    papeis_fora = [
        d for d in documentos_elegiveis if d.get("papel") not in PAPEIS_DO_LOTE
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
        Criterio(
            "esferas permitidas",
            ",".join(sorted(permitidas)),
            ",".join(sorted(esferas_obtidas)) or "—",
            esfera_ok,
        ),
        Criterio(
            f"perfil {PERFIL_PUBLICO_14133_PREGAO_ELETRONICO_BENS}",
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
            and documentos_validos_supported == documentos_esperados_supported,
        ),
        Criterio(
            "relações documentais catalogadas",
            f"{len(perfis_supported)} processos",
            f"{supported_com_relacao} processos",
            bool(perfis_supported) and supported_com_relacao == len(perfis_supported),
        ),
        Criterio(
            "novas coletas com cadeia completa",
            str(sum(
                1
                for p in perfis_supported
                if _eh_cadeia_nova(p)
            )),
            str(supported_novos_com_cadeia),
            supported_novos_com_cadeia
            == sum(
                1
                for p in perfis_supported
                if _eh_cadeia_nova(p)
            ),
        ),
        Criterio(
            "vínculos válidos dos contratos presentes",
            str(len(contratos_no_catalogo)),
            str(len(contratos_validos)),
            len(contratos_validos) == len(contratos_no_catalogo),
        ),
        Criterio(
            "novas coletas com instrumento contratual vinculado",
            str(sum(
                1
                for p in perfis_supported
                if _eh_cadeia_nova(p)
            )),
            str(novos_com_contrato_vinculado),
            novos_com_contrato_vinculado
            == sum(
                1
                for p in perfis_supported
                if _eh_cadeia_nova(p)
            ),
        ),
        Criterio(
            "somente documentos da cadeia (ETP/TR/EDITAL/CONTRATO)",
            "0 extras",
            str(len(papeis_fora)),
            not papeis_fora,
        ),
    ]
    tem_coleta_nova = any(_eh_cadeia_nova(p) for p in perfis_supported)
    processos_novos = [p for p in perfis_supported if _eh_cadeia_nova(p)]
    ids_novos = {
        str(p.get("processo_id") or "") for p in processos_novos
    }
    if tem_coleta_nova:
        # Em um catálogo misto, os processos históricos não podem aumentar o
        # piso de Edital/Contrato das cadeias novas. A regra documental nova é
        # verificada por processo nos critérios acima e aqui conferimos que
        # cada elo aparece exatamente uma vez em cada cadeia marcada como nova.
        for papel in PAPEIS_CADEIA_COMPLETA:
            quantos = sum(
                1
                for documento in documentos
                if str(documento.get("processo_id") or "") in ids_novos
                and documento.get("papel") == papel
            )
            criterios.append(
                Criterio(
                    f"documentos {papel} (cadeias novas)",
                    f"={len(processos_novos)}",
                    str(quantos),
                    quantos == len(processos_novos),
                )
            )
        # Os elos enriquecedores seguem opcionais somente para os processos
        # históricos; mantemos a informação sem transformá-la em piso.
        ids_historicos = {
            str(p.get("processo_id") or "")
            for p in perfis_supported
            if not _eh_cadeia_nova(p)
        }
        for papel in ("EDITAL", "CONTRATO"):
            quantos = sum(
                1
                for documento in documentos
                if str(documento.get("processo_id") or "") in ids_historicos
                and documento.get("papel") == papel
            )
            criterios.append(
                Criterio(
                    f"documentos {papel} (históricos, opcional)",
                    "sem piso",
                    str(quantos),
                    True,
                )
            )
    else:
        for papel in PAPEIS_PAR_ETP_TR:
            quantos = sum(1 for d in documentos_elegiveis if d.get("papel") == papel)
            criterios.append(
                Criterio(
                    f"documentos {papel}",
                    f"≥{minimo_processos}",
                    str(quantos),
                    quantos >= minimo_processos,
                )
            )
        for papel in ("EDITAL", "CONTRATO"):
            quantos = sum(1 for d in documentos_elegiveis if d.get("papel") == papel)
            criterios.append(
                Criterio(f"documentos {papel} (opcional)", "sem piso", str(quantos), True)
            )

    return {
        "passou": all(c.passou for c in criterios),
        "perfil_id": PERFIL_PUBLICO_14133_PREGAO_ELETRONICO_BENS,
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
        "# Gate do corpus de cadeias documentais",
        "",
        f"**Resultado: {'PASSOU' if resultado['passou'] else 'NÃO PASSOU'}**",
        "",
        "Verificação independente: cada arquivo catalogado foi reaberto a partir",
        "do disco e conferido pelo SHA-256 original. Texto OCR histórico só conta",
        "quando possui idioma, versão do pipeline e SHA-256 do derivado auditável.",
        "Novas coletas exigem ETP, TR, edital e instrumento contratual. Processos",
        "históricos de ETP/TR são avaliados sob a versão documental preservada.",
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
        "| # | Processo | Órgão | UF | Categoria | Escopo | ETP | TR | Edital | Contrato |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    elegiveis_ids = set(resultado.get("processos_elegiveis_ids") or [])
    for posicao, processo in enumerate(
        sorted(processos, key=lambda p: p["processo_id"]), start=1
    ):
        cadeia = processo["cadeia"]
        compra = processo.get("compra") or {}
        perfil_atual = _perfil_atual(processo)
        filtro_codigos = (
            _int(compra.get("instrumento_convocatorio_codigo")) == 1
            and _int(compra.get("amparo_legal_codigo")) == 1
        )
        if processo.get("processo_id") in elegiveis_ids:
            escopo = "SUPPORTED"
        elif _eh_cadeia_nova(processo):
            escopo = "REPROVADO"
        elif perfil_atual == PERFIL_SUPPORTED and filtro_codigos:
            escopo = "HISTÓRICO"
        else:
            escopo = "OUT_OF_SCOPE"
        linhas.append(
            f"| {posicao} | [{processo['numero_controle_pncp']}]"
            f"({processo['fontes']['portal_pncp']}) | "
            f"{processo['orgao'].get('razao_social') or '—'} | "
            f"{processo['orgao'].get('uf') or '—'} | "
            f"{processo.get('categoria_objeto') or '—'} | "
            f"{escopo} | "
            f"{len(cadeia.get('ETP') or [])} | {len(cadeia.get('TR') or [])} | "
            f"{len(cadeia.get('EDITAL') or [])} | {len(cadeia.get('CONTRATO') or [])} |"
        )
    if resultado["falhas_de_abertura"]:
        linhas += ["", "## Documentos que não abriram", ""]
        for falha in resultado["falhas_de_abertura"]:
            linhas.append(f"- `{falha['documento_id']}`: {falha['erro']}")
    linhas += ["", f"Total de documentos: **{len(documentos)}**.", ""]
    return "\n".join(linhas)


def principal(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verifica o corpus local de cadeias documentais completas."
    )
    parser.add_argument("--raiz", type=Path, default=Path("corpus"))
    parser.add_argument("--processos", type=int, default=15)
    parser.add_argument("--orgaos", type=int, default=5)
    parser.add_argument("--max-por-orgao", type=int, default=5)
    parser.add_argument("--categorias", type=int, default=3)
    parser.add_argument(
        "--esferas",
        default=",".join(sorted(ESFERAS_PERMITIDAS)),
        help="esferas admitidas, separadas por vírgula (F,E,D,M)",
    )
    argumentos = parser.parse_args(argv)
    resultado = conferir(
        argumentos.raiz,
        minimo_processos=argumentos.processos,
        max_por_orgao=argumentos.max_por_orgao,
        minimo_orgaos=argumentos.orgaos,
        esferas={e.strip().upper() for e in argumentos.esferas.split(",") if e.strip()},
        minimo_categorias=argumentos.categorias,
    )
    escrever_json(argumentos.raiz / "catalogo" / "gate.json", resultado)
    markdown = como_markdown(argumentos.raiz, resultado)
    (argumentos.raiz / "GATE_R1.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if resultado["passou"] else 1


if __name__ == "__main__":
    raise SystemExit(principal())
