"""Publicação de um elo opcional da cadeia no corpus (catálogo + estado).

Compartilhado por ``fetch_editais.py`` e ``fetch_contratos.py``. Existe porque
a gravação correta tem uma sutileza que não pode ser duplicada: o coletor
reconstrói ``documentos.jsonl`` a partir do **banco de estado**, não do
catálogo. Um documento gravado só no catálogo é apagado na primeira coleta
seguinte. Toda ferramenta que acrescenta um elo precisa, portanto:

1. escrever no catálogo (para o corpus ficar utilizável de imediato);
2. refazer ``cadeia`` e ``relacoes`` (o gate lê a cadeia do processo);
3. anexar o registro ao aceite da política vigente no estado.

Omitir o passo 3 foi o defeito que derrubou os editais de 22 para 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from licita_corpus.catalog import CADEIA, montar_relacoes
from licita_corpus.collect import POLICY_VERSION
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


def sincronizar_catalogo(catalogo: list[dict[str, Any]]) -> None:
    """Refaz ``cadeia`` e relações a partir do catálogo de documentos.

    O documento sozinho não basta: o gate lê a cadeia do processo e as arestas
    de ``relacoes.json``. Sem isto o catálogo fica internamente inconsistente —
    documento presente em disco e ausente da cadeia.
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
        for documento in por_processo.get(pid, []):
            if documento.get("papel") in cadeia:
                cadeia[documento["papel"]].append(documento["documento_id"])
        processo["cadeia"] = cadeia
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


def registrar_no_estado(novos_por_processo: dict[str, dict[str, Any]]) -> None:
    """Anexa os elos baixados aos aceites do coletor, na política vigente.

    O registro guardado no estado conserva ``_texto`` (a catalogação o usa) e
    não leva ``reuso``, que é campo do catálogo.
    """
    if not novos_por_processo:
        return
    if not ESTADO.exists():
        print(f"[estado] ausente em {ESTADO.relative_to(ROOT)}: nada a registrar")
        return

    anexados = 0
    sem_aceite: list[str] = []
    with EstadoColeta(ESTADO, 0, policy_version=POLICY_VERSION) as estado:
        aceitos = {
            str(candidato.get("numero_controle_pncp") or ""): (candidato, documentos)
            for candidato, documentos in estado.aceitos()
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
            estado.salvar_aceito(candidato, [*documentos, registro])
            anexados += 1

    print(f"[estado] {anexados} elo(s) anexado(s) ao aceite da política {POLICY_VERSION}")
    if sem_aceite:
        print(
            f"[estado] {len(sem_aceite)} processo(s) sem aceite nesta política "
            f"(o elo vive só no catálogo até a próxima coleta): {sem_aceite[:5]}"
        )


def publicar(novos: list[dict[str, Any]], para_estado: dict[str, dict[str, Any]]) -> None:
    """Escreve os elos novos no catálogo, sincroniza a cadeia e grava o estado."""
    if not novos:
        print("\nNenhum elo novo adicionado.")
        return
    catalogo = carregar_catalogo()
    catalogo.extend(novos)
    gravar_catalogo(catalogo)
    sincronizar_catalogo(catalogo)
    registrar_no_estado(para_estado)
    print(f"\n{len(novos)} elo(s) adicionado(s) ao catálogo ({CATALOG.relative_to(ROOT)}).")
