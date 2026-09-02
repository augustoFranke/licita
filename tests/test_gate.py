"""Gate do R1 — a verificação tem de reprovar quando o disco não confere."""

import json

import pymupdf
import pytest

from licita_corpus.catalog import escrever_json, escrever_jsonl, montar_processo, montar_relacoes
from licita_corpus.gate import _eh_cadeia_nova, conferir


def _pdf(caminho, texto):
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto)
    documento.save(caminho)
    documento.close()


@pytest.fixture
def corpus(tmp_path):
    """Corpus sintético mínimo ETP→TR que passa em todos os critérios."""
    import hashlib

    processos, documentos, relacoes = [], [], []
    for indice in range(30):
        compra = {
            "numero_controle_pncp": f"{indice:014d}-1-{indice:06d}/2026",
            "cnpj_orgao": f"{indice % 6:014d}",
            "ano_compra": 2026,
            "sequencial_compra": indice,
            "orgao": f"ORGAO {indice % 6}",
            "esfera": "M",
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
        for papel in ("ETP", "TR"):
            arquivo = pasta / f"{papel.lower()}-01.pdf"
            _pdf(arquivo, f"{papel} do processo {indice} com conteúdo textual suficiente para validação local")
            do_processo.append(
                {
                    "documento_id": f"{identificador}#{papel.lower()}-01",
                    "processo_id": identificador,
                    "papel": papel,
                    "arquivo": str(arquivo.relative_to(tmp_path)),
                    "sha256": hashlib.sha256(arquivo.read_bytes()).hexdigest(),
                    "sha256_original": hashlib.sha256(arquivo.read_bytes()).hexdigest(),
                    "verificacao": {"abriu": True, "paginas": 1, "caracteres": 20, "precisa_ocr": False},
                }
            )
        registro = montar_processo(compra, None, do_processo, [])
        processos.append(registro)
        documentos.extend(do_processo)
        relacoes.extend(montar_relacoes(identificador, registro["cadeia"]))

    escrever_json(tmp_path / "catalogo" / "processos.json", processos)
    escrever_jsonl(tmp_path / "catalogo" / "documentos.jsonl", documentos)
    escrever_json(tmp_path / "catalogo" / "relacoes.json", {"cadeia": relacoes, "reuso": []})
    return tmp_path


def test_corpus_etp_tr_sem_edital_ou_contrato_passa(corpus):
    resultado = conferir(corpus)
    assert resultado["passou"] is True
    assert resultado["falhas_de_abertura"] == []


def test_edital_no_lote_nao_reprova_e_e_contado(corpus):
    """O lote é de cadeia: um edital acompanhando o par não invalida o processo.

    Trava a decisão de escopo — antes o lote exigia exatamente dois documentos
    (ETP e TR), então qualquer elo a mais reprovava justamente o processo com a
    cadeia mais completa.
    """
    import hashlib

    caminho_docs = corpus / "catalogo" / "documentos.jsonl"
    documentos = [
        json.loads(l) for l in caminho_docs.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    modelo = documentos[0]
    pid = modelo["processo_id"]

    destino = corpus / "documentos" / pid / "edital-01.pdf"
    _pdf(destino, "EDITAL do processo com conteúdo textual suficiente para validação local")
    digesto = hashlib.sha256(destino.read_bytes()).hexdigest()
    edital = dict(modelo)
    edital.update({
        "documento_id": f"{pid}#edital-01",
        "papel": "EDITAL",
        "arquivo": str(destino.relative_to(corpus)),
        "sha256": digesto,
        "sha256_original": digesto,
        "verificacao": {"abriu": True, "paginas": 1, "caracteres": 20, "precisa_ocr": False},
    })
    documentos.append(edital)
    caminho_docs.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in documentos) + "\n",
        encoding="utf-8",
    )

    caminho_proc = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho_proc.read_text(encoding="utf-8"))
    registros = processos["processos"] if isinstance(processos, dict) else processos
    for processo in registros:
        if processo["processo_id"] == pid:
            processo["cadeia"]["EDITAL"] = [edital["documento_id"]]
    caminho_proc.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")

    resultado = conferir(corpus)
    reprovados = [c for c in resultado["criterios"] if not c["passou"]]
    assert resultado["passou"] is True, reprovados
    criterio = next(
        c for c in resultado["criterios"] if c["nome"] == "documentos EDITAL (opcional)"
    )
    assert criterio["obtido"] == "1"


def test_papel_fora_da_cadeia_reprova(corpus):
    """DFD e pesquisa de preços seguem fora do lote."""
    import hashlib

    caminho_docs = corpus / "catalogo" / "documentos.jsonl"
    documentos = [
        json.loads(l) for l in caminho_docs.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    modelo = documentos[0]
    pid = modelo["processo_id"]
    destino = corpus / "documentos" / pid / "dfd-01.pdf"
    _pdf(destino, "DFD do processo com conteúdo textual suficiente para validação local")
    digesto = hashlib.sha256(destino.read_bytes()).hexdigest()
    intruso = dict(modelo)
    intruso.update({
        "documento_id": f"{pid}#dfd-01",
        "papel": "DFD",
        "arquivo": str(destino.relative_to(corpus)),
        "sha256": digesto,
        "sha256_original": digesto,
        "verificacao": {"abriu": True, "paginas": 1, "caracteres": 20, "precisa_ocr": False},
    })
    documentos.append(intruso)
    caminho_docs.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in documentos) + "\n",
        encoding="utf-8",
    )
    caminho_proc = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho_proc.read_text(encoding="utf-8"))
    registros = processos["processos"] if isinstance(processos, dict) else processos
    for processo in registros:
        if processo["processo_id"] == pid:
            processo["cadeia"]["DFD"] = [intruso["documento_id"]]
    caminho_proc.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")

    resultado = conferir(corpus, minimo_processos=30)
    assert resultado["passou"] is False


def test_arquivo_ausente_reprova(corpus):
    documentos = (corpus / "catalogo" / "documentos.jsonl").read_text(encoding="utf-8").splitlines()
    (corpus / json.loads(documentos[0])["arquivo"]).unlink()
    resultado = conferir(corpus, minimo_processos=30)
    assert resultado["passou"] is False
    assert resultado["processos_elegiveis"] == 29
    assert resultado["falhas_de_abertura"][0]["erro"] == "arquivo ausente"


def test_arquivo_alterado_reprova_pelo_hash(corpus):
    primeiro = json.loads(
        (corpus / "catalogo" / "documentos.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    (corpus / primeiro["arquivo"]).write_bytes(b"%PDF-1.4 outro conteudo")
    resultado = conferir(corpus, minimo_processos=30)
    assert resultado["passou"] is False
    assert resultado["processos_elegiveis"] == 29
    assert resultado["falhas_de_abertura"][0]["erro"] == "SHA-256 divergente"


def test_processo_sem_tr_reprova_o_par(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["cadeia"]["TR"] = []
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    assert resultado["passou"] is False
    assert resultado["processos_elegiveis"] == 29
    criterio = next(
        c
        for c in resultado["criterios"]
        if c["nome"] == "processos SUPPORTED com exatamente um ETP e um TR"
    )
    assert criterio["passou"] is False


def test_vinculo_contrato_divergente_reprova(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["contratos"] = [
        {
            "numero_controle_pncp_compra": "outro",
            "criterio_vinculo": "numeroControlePncpCompra",
        }
    ]
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    criterio = next(
        c
        for c in resultado["criterios"]
        if c["nome"] == "vínculos válidos dos contratos presentes"
    )
    assert criterio["passou"] is False


def test_quatro_papeis_sem_vinculo_exato_continuam_historicos():
    processo = {
        "numero_controle_pncp": "12345678000199-1-000001/2025",
        "cadeia": {
            "ETP": ["etp"],
            "TR": ["tr"],
            "EDITAL": ["edital"],
            "CONTRATO": ["contrato"],
        },
        "escopo_documental": {"cadeia_completa": True},
        "contratos": [],
    }

    # A presença de quatro IDs (inclusive um escopo marcado por catálogo
    # antigo) não cria uma cadeia nova sem o vínculo contrato→compra.
    assert _eh_cadeia_nova(processo) is False


def test_documento_duplicado_no_mesmo_papel_reprova(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["cadeia"]["ETP"].append(processos[0]["cadeia"]["ETP"][0])
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus, minimo_processos=30)
    assert resultado["passou"] is False
    assert resultado["processos_elegiveis"] == 29


def test_poucos_processos_reprova(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    caminho.write_text(json.dumps(processos[:10], ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    assert resultado["passou"] is False
    criterio = next(c for c in resultado["criterios"] if c["nome"] == "processos")
    assert criterio["obtido"] == "10"


def test_um_processo_fora_do_filtro_de_bens_nao_derruba_o_lote(corpus):
    caminho = corpus / "catalogo" / "processos.json"
    processos = json.loads(caminho.read_text(encoding="utf-8"))
    processos[0]["objeto"] = "Contratação de empresa para fornecimento de energia elétrica"
    caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
    resultado = conferir(corpus)
    assert resultado["passou"] is True
    criterio = next(
        c
        for c in resultado["criterios"]
        if c["nome"] == "processos no filtro Lei 14.133/Pregão/bens"
    )
    assert criterio["passou"] is True
    assert criterio["obtido"] == "29"


def test_esfera_ausente_ou_desconhecida_reprova_catalogo_aprovado(corpus):
    """Esfera é obrigatória: ausente ou fora da tabela reprova o lote."""
    caminho = corpus / "catalogo" / "processos.json"
    originais = json.loads(caminho.read_text(encoding="utf-8"))
    for esfera in (None, "", "X"):
        processos = json.loads(json.dumps(originais))
        processos[0]["orgao"]["esfera"] = esfera
        processos[0]["perfil_inicial"] = "SUPPORTED"  # persistido não é confiável
        caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
        resultado = conferir(corpus)
        criterio = next(c for c in resultado["criterios"] if c["nome"] == "esferas permitidas")
        assert criterio["passou"] is False


def test_esferas_federal_estadual_e_distrital_sao_aceitas(corpus):
    """A esfera deixou de restringir o perfil: F/E/D não reprovam o lote."""
    caminho = corpus / "catalogo" / "processos.json"
    originais = json.loads(caminho.read_text(encoding="utf-8"))
    for esfera in ("F", "E", "D"):
        processos = json.loads(json.dumps(originais))
        processos[0]["orgao"]["esfera"] = esfera
        caminho.write_text(json.dumps(processos, ensure_ascii=False), encoding="utf-8")
        resultado = conferir(corpus)
        criterio = next(c for c in resultado["criterios"] if c["nome"] == "esferas permitidas")
        assert criterio["passou"] is True, f"esfera {esfera} deveria ser aceita"


def test_minimo_de_categorias_conta_somente_elegiveis(corpus):
    resultado = conferir(corpus, minimo_categorias=5)
    criterio = next(c for c in resultado["criterios"] if c["nome"] == "categorias distintas")
    assert criterio["obtido"] == "4"
    assert criterio["passou"] is False


def test_hash_original_tem_precedencia_sobre_sha_legado(corpus):
    caminho = corpus / "catalogo" / "documentos.jsonl"
    documentos = [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]
    documentos[0]["sha256_original"] = "0" * 64
    escrever_jsonl(caminho, documentos)
    resultado = conferir(corpus)
    assert any(f["erro"] == "SHA-256 divergente" for f in resultado["falhas_de_abertura"])


def test_ocr_historico_e_utilizavel_quando_hash_original_confere(monkeypatch, corpus):
    import licita_corpus.gate as gate_module

    caminho = corpus / "catalogo" / "documentos.jsonl"
    documentos = [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]
    documentos[0]["verificacao"] = {
        "abriu": True,
        "caracteres": 120,
        "precisa_ocr": False,
        "ocr": {"usado": True},
        "ocr_cache": {
            "idioma": "por",
            "pipeline_version": "verify-pymupdf-tesseract-v1",
            "texto_sha256": "a" * 64,
        },
    }
    escrever_jsonl(caminho, documentos)
    real = gate_module.verificar

    def sem_texto(arquivo):
        resultado = real(arquivo)
        if arquivo == corpus / documentos[0]["arquivo"]:
            resultado.caracteres = 0
            resultado.precisa_ocr = True
        return resultado

    monkeypatch.setattr(gate_module, "verificar", sem_texto)
    resultado = conferir(corpus)
    assert not any(
        f["documento_id"] == documentos[0]["documento_id"]
        for f in resultado["falhas_de_abertura"]
    )

    documentos[0]["verificacao"].pop("ocr_cache")
    escrever_jsonl(caminho, documentos)
    resultado_sem_derivado = conferir(corpus)
    assert any(
        f["documento_id"] == documentos[0]["documento_id"]
        for f in resultado_sem_derivado["falhas_de_abertura"]
    )
