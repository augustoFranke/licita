from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from licita_corpus.collect import _normalizar_contrato


TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import _corpus_sync  # noqa: E402  (ferramenta compartilhada, carregada após o path)
import fetch_contratos  # noqa: E402


COMPRA = "12345678000199-1-000001/2025"
CONTRATO = "12345678000199-2-000001/2025"
PID = COMPRA.replace("/", "-")


def _contrato_feed() -> dict[str, object]:
    # O formato oficial usado pelo feed não precisa repetir ano/sequencial do
    # contrato: ambos podem ser derivados do número de controle.
    return {
        "numeroControlePNCP": CONTRATO,
        "numeroControlePNCPCompra": COMPRA,
        "tipoContrato": {"id": 1, "nome": "Contrato"},
        "orgaoEntidadeCnpj": "12345678000199",
    }


def test_promocao_usa_contrato_normalizado_para_listar_anexos(monkeypatch, tmp_path):
    chamadas: list[tuple[str, int, int]] = []

    class FakePncp:
        def arquivos_contrato(self, cnpj, ano, seq):
            chamadas.append((cnpj, ano, seq))
            return [
                {
                    "sequencialDocumento": 1,
                    "tipoDocumentoNome": "Contrato",
                    "titulo": "Contrato assinado",
                    "url": "https://arquivos.test/contrato.pdf",
                    "statusAtivo": True,
                }
            ]

    def baixar(*_args, **_kwargs):
        caminho = tmp_path / "contrato.pdf"
        caminho.write_bytes(b"arquivo")
        return SimpleNamespace(
            caminho=caminho,
            nome_original="contrato.pdf",
            sha256="a" * 64,
            bytes=7,
            extensao="pdf",
            content_type="application/pdf",
        )

    monkeypatch.setattr(fetch_contratos, "baixar_documento", baixar)
    monkeypatch.setattr(
        fetch_contratos,
        "_registrar_documento",
        lambda *_args, **_kwargs: {
            "verificacao": {"abriu": True, "caracteres": 12}
        },
    )

    registro = fetch_contratos.baixar_instrumento(
        FakePncp(), _contrato_feed(), PID, COMPRA
    )

    assert registro is not None
    assert chamadas == [("12345678000199", 2025, 1)]


def test_sincronizar_catalogo_publica_vinculo_da_promocao(
    monkeypatch, tmp_path
):
    processos_path = tmp_path / "processos.json"
    relacoes_path = tmp_path / "relacoes.json"
    processos_path.write_text(
        json.dumps(
            [
                {
                    "processo_id": PID,
                    "numero_controle_pncp": COMPRA,
                    "orgao": {"cnpj": "12345678000199", "esfera": "M"},
                    "contratos": [],
                    "escopo_documental": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    relacoes_path.write_text(json.dumps({"cadeia": []}), encoding="utf-8")
    monkeypatch.setattr(_corpus_sync, "PROCESSOS", processos_path)
    monkeypatch.setattr(_corpus_sync, "RELACOES", relacoes_path)

    documentos = [
        {"processo_id": PID, "documento_id": f"{PID}#{papel.lower()}-01", "papel": papel}
        for papel in ("ETP", "TR", "EDITAL", "CONTRATO")
    ]
    contrato = _normalizar_contrato(
        _contrato_feed(), {"numero_controle_pncp": COMPRA}
    )

    _corpus_sync.sincronizar_catalogo(
        documentos, contratos_por_processo={PID: contrato}
    )

    processo = json.loads(processos_path.read_text(encoding="utf-8"))[0]
    assert processo["contratos"][0]["numero_controle_pncp"] == CONTRATO
    assert processo["contratos"][0]["numero_controle_pncp_compra"] == COMPRA
    assert processo["escopo_documental"]["cadeia_completa"] is True
    assert processo["documentos"] == [d["documento_id"] for d in documentos]
    assert len(json.loads(relacoes_path.read_text(encoding="utf-8"))["cadeia"]) == 3


def test_sincronizar_catalogo_nao_marca_quatro_documentos_sem_vinculo(
    monkeypatch, tmp_path
):
    processos_path = tmp_path / "processos.json"
    relacoes_path = tmp_path / "relacoes.json"
    processos_path.write_text(
        json.dumps(
            [
                {
                    "processo_id": PID,
                    "numero_controle_pncp": COMPRA,
                    "orgao": {"cnpj": "12345678000199", "esfera": "M"},
                    "contratos": [],
                    "escopo_documental": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    relacoes_path.write_text(json.dumps({"cadeia": []}), encoding="utf-8")
    monkeypatch.setattr(_corpus_sync, "PROCESSOS", processos_path)
    monkeypatch.setattr(_corpus_sync, "RELACOES", relacoes_path)

    documentos = [
        {"processo_id": PID, "documento_id": f"{PID}#{papel.lower()}-01", "papel": papel}
        for papel in ("ETP", "TR", "EDITAL", "CONTRATO")
    ]
    _corpus_sync.sincronizar_catalogo(documentos)

    processo = json.loads(processos_path.read_text(encoding="utf-8"))[0]
    assert processo["escopo_documental"]["um_documento_por_papel"] is True
    assert processo["escopo_documental"]["cadeia_completa"] is False
