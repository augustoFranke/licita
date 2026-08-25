"""Seleção entre candidatos contract-first, todos com cadeia completa."""

from licita_corpus.select import Candidato, Cotas, selecionar


def candidato(numero: str, orgao: str, categoria: str, data: str = "2025-01-01") -> Candidato:
    return Candidato(
        {
            "numero_controle_pncp": numero,
            "compra": {"cnpj_orgao": orgao, "categoria_objeto": categoria},
            "contratos": [{"data_publicacao_pncp": data}],
            "documentos_compra": [
                {"papel": "ETP"},
                {"papel": "TR"},
                {"papel": "EDITAL"},
            ],
            "documento_contrato": {"papel": "CONTRATO"},
        }
    )


def pool(quantidade=60, orgaos=10, categorias=5):
    return [
        candidato(f"n{i:03d}", f"org{i % orgaos}", f"cat{i % categorias}")
        for i in range(quantidade)
    ]


def test_seleciona_trinta_cadeias_completas():
    selecionados, falta = selecionar(pool(), Cotas())
    assert len(selecionados) == 30
    assert falta == {"processos": 0, "orgaos": 0, "categorias": 0}


def test_prioriza_diversidade_do_corpus():
    selecionados, _ = selecionar(pool(), Cotas())
    assert len({c.orgao for c in selecionados}) >= 5
    assert len({c.categoria for c in selecionados}) >= 3


def test_respeita_teto_por_orgao_quando_existe_oferta():
    selecionados, _ = selecionar(pool(orgaos=20), Cotas(max_por_orgao=2))
    contagens = {orgao: sum(c.orgao == orgao for c in selecionados) for orgao in {c.orgao for c in selecionados}}
    assert max(contagens.values()) <= 2


def test_relata_oferta_insuficiente_sem_inventar():
    selecionados, falta = selecionar(pool(12), Cotas())
    assert len(selecionados) == 12
    assert falta["processos"] == 18


def test_aprovados_anteriores_contam_e_nao_sao_duplicados():
    candidatos = pool()
    aprovados = candidatos[:7]
    selecionados, falta = selecionar(candidatos, Cotas(), iniciais=aprovados)
    assert len(selecionados) == 30
    assert len({c.numero for c in selecionados}) == 30
    assert falta["processos"] == 0
