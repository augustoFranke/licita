"""Marcação de cópia/reuso — o R1 pede que seja marcada quando identificável."""

from licita_corpus.reuse import DocumentoTexto, detectar, jaccard, resumir, shingles

BASE = " ".join(
    f"a clausula {palavra} do termo de referencia fixa prazo de entrega e garantia contratual"
    for palavra in "alfa beta gama delta epsilon zeta eta teta iota kapa lambda mi ni xi omicron pi".split()
)


def documento(id_, processo, papel, sha, texto):
    return DocumentoTexto(id_, processo, papel, sha, texto)


class TestImpressaoTextual:
    def test_texto_curto_nao_produz_shingles(self):
        assert shingles("apenas tres palavras") == frozenset()

    def test_numeros_sao_ignorados(self):
        assert shingles(BASE) == shingles(BASE.replace("prazo", "prazo 30"))

    def test_jaccard_de_conjuntos_vazios_e_zero(self):
        assert jaccard(frozenset(), frozenset({1})) == 0.0


class TestDeteccao:
    def test_arquivo_identico_e_marcado_pelo_hash(self):
        marcas = detectar(
            [
                documento("d1", "p1", "TR", "hash-igual", BASE),
                documento("d2", "p2", "TR", "hash-igual", BASE),
            ]
        )
        assert [m.tipo for m in marcas] == ["arquivo_identico"]
        assert marcas[0].mesmo_processo is False

    def test_texto_quase_identico_entre_orgaos(self):
        marcas = detectar(
            [
                documento("d1", "p1", "TR", "h1", BASE),
                documento("d2", "p2", "TR", "h2", BASE + " paragrafo final adicional"),
            ]
        )
        assert [m.tipo for m in marcas] == ["texto_quase_identico"]

    def test_tr_embutido_no_edital_e_marcado_como_contido(self):
        edital = "preambulo do edital " + BASE + " " + " ".join(
            f"disposicao geral numero {p} sobre recursos e sancoes administrativas aplicaveis"
            for p in "um dois tres quatro cinco seis sete oito nove dez".split()
        )
        marcas = detectar(
            [
                documento("tr", "p1", "TR", "h1", BASE),
                documento("ed", "p1", "EDITAL", "h2", edital),
            ]
        )
        assert [m.tipo for m in marcas] == ["contido_em"]
        marca = marcas[0]
        assert marca.documento_id == "tr" and marca.outro_documento_id == "ed"
        assert marca.mesmo_processo is True

    def test_documentos_sem_parentesco_nao_geram_marca(self):
        outro = " ".join(
            f"o objeto contempla pneus radiais medida {p} para a frota oficial do orgao"
            for p in "a b c d e f g h i j k l m n o p".split()
        )
        marcas = detectar(
            [
                documento("d1", "p1", "TR", "h1", BASE),
                documento("d2", "p2", "TR", "h2", outro),
            ]
        )
        assert marcas == []

    def test_hash_igual_nao_gera_marca_textual_duplicada(self):
        marcas = detectar(
            [
                documento("d1", "p1", "TR", "h", BASE),
                documento("d2", "p2", "TR", "h", BASE),
            ]
        )
        assert len(marcas) == 1

    def test_resumo_separa_intra_e_entre_processos(self):
        marcas = detectar(
            [
                documento("d1", "p1", "TR", "h", BASE),
                documento("d2", "p1", "EDITAL", "h", BASE),
                documento("d3", "p2", "TR", "h", BASE),
            ]
        )
        resumo = resumir(marcas)
        assert resumo["arquivo_identico:intra_processos"] == 1
        assert resumo["arquivo_identico:entre_processos"] == 2


def test_impressao_e_estavel_entre_processos():
    """Marcas de cópia precisam ser reproduzíveis; hash() embutido não é."""
    import subprocess
    import sys

    codigo = (
        "from licita_corpus.reuse import shingles;"
        "print(sorted(shingles('um texto suficientemente longo para gerar varios shingles "
        "distintos neste teste de estabilidade'))[:3])"
    )
    saidas = {
        subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": semente, "PATH": ""},
        ).stdout
        for semente in ("0", "1", "2")
    }
    assert len(saidas) == 1
