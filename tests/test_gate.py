"""Gate do R1 — a verificação tem de reprovar quando o disco não confere."""

import json

import pymupdf
import pytest

from licita_corpus.catalog import escrever_json, escrever_jsonl, montar_processo, montar_relacoes
from licita_corpus.gate import conferir


def _pdf(caminho, texto):
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto)
    documento.save(caminho)
    documento.close()


@pytest.fixture
def corpus(tmp_path):
    """Corpus sintético mínimo que passa em todos os critérios."""
    import hashlib

    processos, documentos, relacoes = [], [], []
    for indice in range(30):
        compra = {
            "numero_controle_pncp": f"{indice:014d}-1-{indice:06d}/2026",
            "cnpj_orgao": f"{indice % 6:014d}",
            "ano_compra": 2026,
            "sequencial_compra": indice,
            "orgao": f"ORGAO {indice % 6}",
            "esfera": "F",
            "poder": "E",
            "uf": "DF",
            "objeto": "Aquisição de bens",
            "categoria_objeto": f"categoria_{indice % 4}",
            "modalidade_id": 6,
            "instrumento_convocatorio_codigo": 1,
            "instrumento_convocatorio": "Edital",
            "amparo_legal_codigo": 1,
            "amparo_legal_nome": "Lei 14.133/2021, Art. 28, I",
        }
        identificador = compra["numero_controle_pncp"].replace("/", "-")
        pasta = tmp_path / "documentos" / identificador
        pasta.mkdir(parents=True)

        do_processo = []
        for papel in ("ETP", "TR", "EDITAL", "CONTRATO"):
            arquivo = pasta / f"{papel.lower()}-01.pdf"
            _pdf(arquivo, f"{papel} do processo {indice} com conteúdo textual suficiente para validação local")
            do_processo.append(
                {
                    "documento_id": f"{identificador}#{papel.lower()}-01",
                    "processo_id": identificador,
                    "papel": papel,
                    "arquivo": str(arquivo.relative_to(tmp_path)),
                    "sha256": hashlib.sha256(arquivo.read_bytes()).hexdigest(),
                    "verificacao": {"abriu": True, "paginas": 1, "caracteres": 20, "precisa_ocr": False},
                }
            )
        registro = montar_processo(
            compra,
            None,
            do_processo,
            [
                {
                    "numero_controle_pncp": f"{indice:014d}-2-{indice:06d}/2026",
                    "numero_controle_pncp_compra": compra["numero_controle_pncp"],
                    "criterio_vinculo": "numeroControlePncpCompra",
                }
            ],
        )
        processos.append(registro)
        documentos.extend(do_processo)
        relacoes.extend(montar_relacoes(identificador, registro["cadeia"]))

    escrever_json(tmp_path / "catalogo" / "processos.json", processos)
    escrever_jsonl(tmp_path / "catalogo" / "documentos.jsonl", documentos)
    escrever_json(tmp_path / "catalogo" / "relacoes.json", {"cadeia": relacoes, "reuso": []})
    return tmp_path


def test_corpus_completo_passa(corpus):
    resultado = conferir(corpus)
    assert resultado["passou"] is True
    assert resultado["falhas_de_abertura"] == []


def test_arquivo_ausente_reprova(corpus):
    documentos = (corpus / "catalogo" / "documentos.jsonl").read_text(encoding="utf-8").splitlines()
    (corpus / json.loads(documentos[0])["arquivo"]).unlink()
    resultado = conferir(corpus)
    assert resultado["passou"] is False
    assert resultado["falhas_de_abertura"][0]["erro"] == "arquivo ausente"


def test_arquivo_alterado_reprova_pelo_hash(corpus):
    primeiro = json.loads(
        (corpus / "catalogo" / "documentos.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    (corpus / primeiro["arquivo"]).write_bytes(b"%PDF-1.4 outro conteudo")
    resultado = conferir(corpus)
    assert resultado["passou"] is False
    assert resultado["falhas_de_abertura"][0]["erro"] == "SHA-256 divergente"


def test_processo_sem_contrato_reprova_a_cadeia(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["cadeia"]["CONTRATO"] = []
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    assert resultado["passou"] is False
    criterio = next(c for c in resultado["criterios"] if c["nome"] == "processos com cadeia completa")
    assert criterio["passou"] is False


def test_vinculo_contrato_divergente_reprova(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["contratos"][0]["numero_controle_pncp_compra"] = "outro"
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    criterio = next(
        c
        for c in resultado["criterios"]
        if c["nome"] == "vínculos compra–contrato por numeroControlePncpCompra"
    )
    assert criterio["passou"] is False


def test_documento_duplicado_no_mesmo_papel_reprova(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["cadeia"]["ETP"].append(processos[0]["cadeia"]["ETP"][0])
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    criterio = next(
        c
        for c in resultado["criterios"]
        if c["nome"] == "processos com exatamente um documento por papel"
    )
    assert criterio["passou"] is False


def test_poucos_processos_reprova(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    caminho.write_text(json.dumps(processos[:10], ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    assert resultado["passou"] is False
    criterio = next(c for c in resultado["criterios"] if c["nome"] == "processos")
    assert criterio["obtido"] == "10"
