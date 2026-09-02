"""Publicação de um elo opcional da cadeia no corpus (catálogo + estado).

Compartilhado por ``fetch_editais.py`` e ``fetch_contratos.py``. Existe porque
a gravação correta tem uma sutileza que não pode ser duplicada: o coletor
reconstrói ``documentos.jsonl`` a partir do **banco de estado**, não do
catálogo. Um documento gravado só no catálogo é apagado na primeira coleta
seguinte. Toda ferramenta que acrescenta um elo precisa, portanto:

1. escrever no catálogo (para o corpus ficar utilizável de imediato);
2. refazer ``cadeia`` e ``relacoes`` (o gate lê a cadeia do processo);
3. anexar o registro ao aceite da política vigente no estado; quando o elo é
   um contrato, preservar também seu vínculo normalizado para que uma
   promoção que complete os quatro papéis passe pelo gate novo.

Omitir o passo 3 foi o defeito que derrubou os editais de 22 para 1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from licita_corpus.catalog import (
    CADEIA,
    PAPEIS_CADEIA_COMPLETA,
    PAPEIS_MATERIAIS,
    PAPEIS_PAR_ETP_TR,
    _contrato_vincula_processo,
    montar_relacoes,
)
from licita_corpus.collect import POLICY_VERSION
from licita_corpus.pncp import url_contrato
from licita_corpus.state import EstadoColeta
from licita_corpus.store import processo_id as pid_de_controle

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CATALOG = CORPUS / "catalogo" / "documentos.jsonl"
PROCESSOS = CORPUS / "catalogo" / "processos.json"
RELACOES = CORPUS / "catalogo" / "relacoes.json"
ESTADO = CORPUS / "estado" / "etp_tr.sqlite3"


def carregar_catalogo() -> list[dict[str, Any]]:
    return [
        json.loads(linha)
        for linha in CATALOG.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]


def para_publico(registro: dict[str, Any]) -> dict[str, Any]:
    """Forma persistida no catálogo: sem campos internos, com ``reuso``."""
    publico = {k: v for k, v in registro.items() if k not in ("_texto", "ocr_cache")}
    publico["reuso"] = []
    return publico


def gravar_catalogo(catalogo: list[dict[str, Any]]) -> None:
    with CATALOG.open("w", encoding="utf-8") as saida:
        for registro in catalogo:
            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _contrato_publico(contrato: Mapping[str, Any]) -> dict[str, Any]:
    """Projeta o contrato normalizado para o formato de ``processos.json``."""
    numero = str(contrato.get("numero_controle_pncp") or "")
    return {
        "numero_controle_pncp": numero,
        "numero_controle_pncp_compra": contrato.get(
            "numero_controle_pncp_compra"
        ),
        "numero_contrato": contrato.get("numero_contrato"),
        "processo_administrativo": contrato.get("processo"),
        "categoria_processo": contrato.get("categoria_processo"),
        "tipo_contrato": contrato.get("tipo_contrato"),
        "fornecedor": contrato.get("fornecedor"),
        "ni_fornecedor": contrato.get("ni_fornecedor"),
        "data_assinatura": contrato.get("data_assinatura"),
        "data_atualizacao_global": contrato.get("data_atualizacao_global"),
        "numero_retificacao": contrato.get("numero_retificacao"),
        "vigencia_inicio": contrato.get("vigencia_inicio"),
        "vigencia_fim": contrato.get("vigencia_fim"),
        "valor_global": contrato.get("valor_global"),
        "objeto": contrato.get("objeto"),
        "fonte": contrato.get("fonte", "pncp"),
        "criterio_vinculo": contrato.get(
            "criterio_vinculo", "numeroControlePncpCompra"
        ),
        "url_portal": url_contrato(numero),
    }


def sincronizar_catalogo(
    catalogo: list[dict[str, Any]],
    *,
    contratos_por_processo: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Refaz ``cadeia`` e relações a partir do catálogo de documentos.

    O documento sozinho não basta: o gate lê a cadeia do processo, os vínculos
    de contrato e as arestas de ``relacoes.json``. Sem isto o catálogo fica
    internamente inconsistente — documento presente em disco e ausente da
    cadeia, ou instrumento sem compra vinculada. Quando a promoção recebe
    ``contratos_por_processo``, o vínculo normalizado é projetado no processo
    na mesma operação.
    """
    por_processo: dict[str, list[dict[str, Any]]] = {}
    for documento in catalogo:
        por_processo.setdefault(documento["processo_id"], []).append(documento)

    processos = json.loads(PROCESSOS.read_text(encoding="utf-8"))
    registros = processos["processos"] if isinstance(processos, dict) else processos
    cadeias: dict[str, dict[str, list[str]]] = {}
    for processo in registros:
        pid = processo["processo_id"]
        cadeia: dict[str, list[str]] = {papel: [] for papel in CADEIA}
        documentos_processo = por_processo.get(pid, [])
        for documento in documentos_processo:
            if documento.get("papel") in cadeia:
                cadeia[documento["papel"]].append(documento["documento_id"])
        processo["cadeia"] = cadeia
        # ``processos.json`` é a entrada do gate e dos consumidores do corpus;
        # uma promoção de CONTRATO precisa publicar o vínculo normalizado aqui
        # na mesma operação que acrescenta o documento ao catálogo. Sem essa
        # projeção o elo existiria apenas no SQLite até a próxima coleta.
        if contratos_por_processo and pid in contratos_por_processo:
            contrato = contratos_por_processo[pid]
            if isinstance(contrato, Mapping):
                processo["contratos"] = [_contrato_publico(contrato)]
                if not processo.get("processo_administrativo") and contrato.get(
                    "processo"
                ):
                    processo["processo_administrativo"] = contrato.get("processo")
                    processo["processo_administrativo_fonte"] = "contrato_pncp"

        processo["documentos"] = [
            documento["documento_id"]
            for documento in documentos_processo
            if documento.get("documento_id")
        ]
        escopo = processo.get("escopo_documental")
        if not isinstance(escopo, dict):
            escopo = {}
        escopo.update(
            {
                "par_etp_tr_valido": all(
                    len(cadeia[papel]) == 1 for papel in PAPEIS_PAR_ETP_TR
                ),
                "um_documento_por_papel": all(
                    len(cadeia[papel]) == 1 for papel in PAPEIS_MATERIAIS
                ),
                "cadeia_completa": all(
                    len(cadeia[papel]) == 1 for papel in PAPEIS_CADEIA_COMPLETA
                ) and _contrato_vincula_processo(processo),
                "contagem": {papel: len(cadeia[papel]) for papel in CADEIA},
            }
        )
        processo["escopo_documental"] = escopo
        cadeias[pid] = cadeia
    PROCESSOS.write_text(
        json.dumps(processos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    relacoes = json.loads(RELACOES.read_text(encoding="utf-8"))
    arestas: list[dict[str, str]] = []
    for pid, cadeia in cadeias.items():
        arestas.extend(montar_relacoes(pid, cadeia))
    relacoes["cadeia"] = arestas
    RELACOES.write_text(
        json.dumps(relacoes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"catálogo sincronizado: {len(arestas)} arestas de cadeia")


def registrar_no_estado(
    novos_por_processo: dict[str, dict[str, Any]],
    *,
    contratos_por_processo: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Anexa os elos baixados aos aceites do coletor, na política vigente.

    O registro guardado no estado conserva ``_texto`` (a catalogação o usa) e
    não leva ``reuso``, que é campo do catálogo.
    """
    if not novos_por_processo:
        return
    contratos_por_processo = contratos_por_processo or {}
    if not ESTADO.exists():
        print(f"[estado] ausente em {ESTADO.relative_to(ROOT)}: nada a registrar")
        return

    anexados = 0
    sem_aceite: list[str] = []
    with EstadoColeta(ESTADO, 0, policy_version=POLICY_VERSION) as estado:
        # Uma promoção pode começar em qualquer policy histórica. ``None``
        # lê todas as versões; a iteração ordenada mantém a aceitação mais
        # recente quando o mesmo processo já foi migrado parcialmente.
        aceitos = {
            str(candidato.get("numero_controle_pncp") or ""): (candidato, documentos)
            for candidato, documentos in estado.aceitos(None)
        }
        por_pid = {pid_de_controle(numero): numero for numero in aceitos}
        for pid, registro in novos_por_processo.items():
            numero = por_pid.get(pid)
            if numero is None:
                sem_aceite.append(pid)
                continue
            candidato, documentos = aceitos[numero]
            if any(d.get("documento_id") == registro["documento_id"] for d in documentos):
                continue
            candidato_atual = dict(candidato)
            contrato = contratos_por_processo.get(pid)
            if isinstance(contrato, Mapping):
                contratos = candidato_atual.get("contratos")
                if not isinstance(contratos, list):
                    contratos = []
                contratos_atualizados = [
                    dict(item) for item in contratos if isinstance(item, Mapping)
                ]
                numero_contrato = str(
                    contrato.get("numero_controle_pncp") or ""
                )
                if numero_contrato and not any(
                    item.get("numero_controle_pncp") == numero_contrato
                    for item in contratos_atualizados
                ):
                    contratos_atualizados.append(dict(contrato))
                candidato_atual["contratos"] = contratos_atualizados
                candidato_atual["contrato"] = dict(contrato)
            documentos_atualizados = [*documentos, registro]
            papeis = [
                str(item.get("papel") or "")
                for item in documentos_atualizados
            ]
            if (
                len(documentos_atualizados) == len(PAPEIS_CADEIA_COMPLETA)
                and set(papeis) == set(PAPEIS_CADEIA_COMPLETA)
                and _contrato_vincula_processo(candidato_atual)
            ):
                # O marcador só é escrito quando a promoção já tem os quatro
                # documentos e o vínculo normalizado do instrumento.
                candidato_atual["cadeia_completa_exigida"] = True
            estado.salvar_aceito(candidato_atual, documentos_atualizados)
            anexados += 1

    print(f"[estado] {anexados} elo(s) anexado(s) ao aceite da política {POLICY_VERSION}")
    if sem_aceite:
        print(
            f"[estado] {len(sem_aceite)} processo(s) sem aceite nesta política "
            f"(o elo vive só no catálogo até a próxima coleta): {sem_aceite[:5]}"
        )


def publicar(
    novos: list[dict[str, Any]],
    para_estado: dict[str, dict[str, Any]],
    *,
    contratos_por_processo: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Escreve os elos novos no catálogo, sincroniza a cadeia e grava o estado."""
    if not novos:
        print("\nNenhum elo novo adicionado.")
        return
    catalogo = carregar_catalogo()
    catalogo.extend(novos)
    gravar_catalogo(catalogo)
    sincronizar_catalogo(
        catalogo, contratos_por_processo=contratos_por_processo
    )
    registrar_no_estado(
        para_estado, contratos_por_processo=contratos_por_processo
    )
    print(f"\n{len(novos)} elo(s) adicionado(s) ao catálogo ({CATALOG.relative_to(ROOT)}).")
