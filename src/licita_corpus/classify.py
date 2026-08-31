"""Classificação de objetos de compra e de tipos documentais do PNCP.

Duas decisões independentes vivem aqui:

- ``papel_documento`` — tipo do pack (``01``): ``DFD``, ``ETP``, ``TR``,
  ``EDITAL``, ``CONTRATO``, ``PESQUISA_PRECOS``, ``OUTROS``. O
  ``tipoDocumentoId`` do PNCP é autoritativo quando existe; o título é usado
  apenas para resgatar arquivos publicados como "Outros Documentos".
- ``categoria_objeto`` — a categoria de bem, usada para satisfazer o mínimo de
  três categorias exigido pelo R1.
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------- texto


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e com espaçamento colapsado."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


# ------------------------------------------------------------ papel do doc

DFD = "DFD"
ETP = "ETP"
TR = "TR"
EDITAL = "EDITAL"
CONTRATO = "CONTRATO"
PESQUISA_PRECOS = "PESQUISA_PRECOS"
OUTROS = "OUTROS"
OUTRO = OUTROS  # alias legado
AVISO_DIRETA = OUTROS  # PNCP tipo 1 não é tipo do pack
MINUTA_CONTRATO = OUTROS  # PNCP tipo 3 não é tipo do pack

MUNICIPAL_14133_PREGAO_ELETRONICO_BENS = (
    "MUNICIPAL_14133_PREGAO_ELETRONICO_BENS"
)
PERFIL_MUNICIPAL_14133_PREGAO_ELETRONICO_BENS = (
    MUNICIPAL_14133_PREGAO_ELETRONICO_BENS
)
PERFIL_SUPPORTED = "SUPPORTED"
PERFIL_FORA = "FORA_DO_PERFIL"

#: ``tipoDocumentoId`` do PNCP → tipo do pack.
TIPO_PNCP_PARA_PAPEL = {
    1: OUTROS,
    2: EDITAL,
    3: OUTROS,
    4: TR,
    7: ETP,
    12: CONTRATO,
}

#: Regras de título, aplicadas em ordem — a primeira que casar vence.
_REGRAS_TITULO: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        DFD,
        re.compile(
            r"(?<![a-z0-9])(?:documento de formalizacao da demanda|dfd)(?![a-z0-9])"
        ),
    ),
    (
        ETP,
        re.compile(
            r"(?<![a-z0-9])(?:estudos? tecnicos? preliminar(?:es)?|etp)(?![a-z0-9])"
        ),
    ),
    (
        TR,
        re.compile(
            r"(?<![a-z0-9])(?:termos? de referencias?|termos? referencias?|tr)(?![a-z0-9])"
        ),
    ),
    (
        PESQUISA_PRECOS,
        re.compile(r"pesquisa de precos?"),
    ),
    (CONTRATO, re.compile(r"\bcontrato\b")),
    (EDITAL, re.compile(r"\bedital\b")),
)

#: Títulos que contêm a palavra-chave mas não são o documento em si.
_TITULO_NEGATIVO = re.compile(
    r"\b(errata|retificacao|adendo|esclarecimento|impugnacao|recurso|"
    r"resultado|ata de (sessao|realizacao)|homologacao|adjudicacao|"
    r"aviso de licitacao|extrato|publicacao|comprovante)\b"
)


def papel_documento(tipo_id: int | str | None, titulo: str) -> str:
    """Papel do arquivo na cadeia documental.

    O ``tipoDocumentoId`` prevalece. Só caímos no título quando o PNCP
    classificou o arquivo como genérico (``16 — Outros Documentos``) ou não
    informou tipo. Algumas integrações devolvem o código como texto, por isso
    a conversão é feita antes da consulta à tabela oficial.
    """
    try:
        codigo = None if tipo_id is None else int(tipo_id)
    except (TypeError, ValueError):
        codigo = None
    if codigo in TIPO_PNCP_PARA_PAPEL:
        return TIPO_PNCP_PARA_PAPEL[codigo]
    if codigo not in (None, 16):
        return OUTROS
    alvo = normalizar(titulo)
    if _TITULO_NEGATIVO.search(alvo):
        return OUTROS
    for papel, padrao in _REGRAS_TITULO:
        if padrao.search(alvo):
            return papel
    return OUTROS


#: Tipos do pack. O lote R1 só baixa ETP e TR.
PAPEIS_DA_CADEIA = (DFD, ETP, TR, EDITAL, CONTRATO, PESQUISA_PRECOS)
PAPEIS_MATERIAIS = (ETP, TR, EDITAL, CONTRATO)


# ------------------------------------------------------- categoria do objeto

#: Categoria → termos que a caracterizam. Ordem importa: a primeira categoria
#: com algum termo presente vence, então as mais específicas vêm antes.
_CATEGORIAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "medicamentos_e_insumos_farmaceuticos",
        (
            "medicamento", "medicamentos", "farmaco", "farmacos",
            "insumo farmaceutico", "insumos farmaceuticos", "soro", "soros",
            "vacina", "vacinas", "psicotropico", "psicotropicos",
        ),
    ),
    (
        "equipamentos_medico_hospitalares",
        (
            "equipamento medico", "equipamentos medicos",
            "equipamento hospitalar", "equipamentos hospitalares",
            "equipamentos medico hospitalares", "equipamentos medicos hospitalares",
            "aspirador cirurgico", "aspiradores cirurgicos", "cadeira de rodas",
            "cadeiras de rodas", "desfibrilador", "desfibriladores",
            "monitor multiparametro", "monitores multiparametros", "autoclave",
            "autoclaves",
        ),
    ),
    (
        "material_medico_hospitalar",
        (
            "material medico", "materiais medicos", "medico hospitalar",
            "medicos hospitalares", "hospitalar", "odontologico", "odontologica",
            "odontologicos", "odontologicas", "laboratorial", "laboratoriais",
            "seringa", "seringas", "luva de procedimento", "luvas de procedimento",
            "cateter", "cateteres", "curativo", "curativos", "material penso",
            "materiais penso", "correlato", "correlatos",
        ),
    ),
    (
        "generos_alimenticios",
        (
            "genero alimenticio", "generos alimenticios", "alimenticio", "alimenticios",
            "alimentacao escolar", "merenda", "merendas", "hortifrut", "carne", "carnes",
            "leite", "leites", "cesta basica", "cestas basicas", "panificacao", "paes",
        ),
    ),
    (
        "material_de_limpeza_e_higiene",
        (
            "material de limpeza", "materiais de limpeza", "produto de limpeza",
            "produtos de limpeza", "higiene", "higienes", "higiene bucal",
            "higienes bucais", "higienizacao", "saneante", "saneantes", "descartavel",
            "descartaveis", "copa e cozinha",
        ),
    ),
    (
        "material_de_expediente_e_escritorio",
        (
            "material de expediente", "materiais de expediente", "material de escritorio",
            "materiais de escritorio", "papelaria", "papel a4", "suprimento de informatica",
            "suprimentos de informatica", "cartucho", "cartuchos", "toner", "toners",
            "material grafico", "materiais graficos",
        ),
    ),
    (
        "mobiliario",
        (
            "mobiliario", "movel", "moveis", "cadeira", "cadeiras", "mesa", "mesas",
            "armario", "armarios", "estante", "estantes", "longarina", "longarinas",
            "poltrona", "poltronas",
        ),
    ),
    (
        "equipamentos_de_informatica",
        (
            "informatica", "computador", "computadores", "notebook", "notebooks",
            "microcomputador", "microcomputadores", "impressora", "impressoras", "scanner",
            "scanners", "servidor de rede", "servidores de rede", "switch", "switches",
            "nobreak", "nobreaks", "monitor de video", "monitores de video", "tablet",
            "tablets", "licenciamento de software", "software", "softwares",
        ),
    ),
    (
        "eletrodomesticos_e_eletroeletronicos",
        (
            "eletrodomestico", "eletrodomesticos", "eletroeletronico", "eletroeletronicos",
            "ar condicionado", "ares condicionados", "condicionador de ar",
            "condicionadores de ar", "refrigerador", "refrigeradores", "freezer", "freezers",
            "televisor", "televisores", "bebedouro", "bebedouros", "ventilador", "ventiladores",
            "fogao", "fogoes",
        ),
    ),
    (
        "veiculos_pecas_e_combustiveis",
        (
            "veiculo", "veiculos", "automovel", "automoveis", "caminhao", "caminhoes",
            "onibus", "ambulancia", "ambulancias", "pneu", "pneus", "peca automotiva",
            "pecas automotivas", "combustivel", "combustiveis", "oleo lubrificante",
            "oleos lubrificantes", "motocicleta", "motocicletas",
        ),
    ),
    (
        "material_de_construcao_e_ferramentas",
        (
            "material de construcao", "materiais de construcao", "hidraulica", "hidraulico",
            "hidraulicas", "hidraulicos", "ferramenta", "ferramentas", "cimento", "cimentos",
            "tinta", "tintas", "asfalto", "asfaltos", "asfalto frio", "asfaltos frios",
            "material eletrico", "materiais eletricos", "iluminacao publica", "lampada", "lampadas",
        ),
    ),
    (
        "epi_uniformes_e_textil",
        (
            "epi", "equipamento de protecao individual", "equipamentos de protecao individual",
            "uniforme", "uniformes", "fardamento", "fardamentos", "vestuario", "enxoval",
            "textil", "texteis", "calcado", "calcados",
        ),
    ),
    (
        "material_agropecuario_e_jardinagem",
        (
            "agropecuario", "agropecuaria", "agropecuarios", "agropecuarias", "agricola",
            "agricolas", "implemento agricola", "implementos agricolas", "semente", "sementes",
            "muda", "mudas", "fertilizante", "fertilizantes", "racao", "racoes", "adubo",
            "adubos", "calcario", "calcarios", "jardinagem",
        ),
    ),
    (
        "material_didatico_e_esportivo",
        (
            "material didatico", "materiais didaticos", "material escolar", "materiais escolares",
            "livro", "livros", "brinquedo", "brinquedos", "material esportivo",
            "materiais esportivos", "instrumento musical", "instrumentos musicais",
        ),
    ),
)


def _contem_termo_de_categoria(alvo: str, termo: str) -> bool:
    """Casa um termo inteiro, sem aceitar prefixos ou palavras embutidas."""
    termo_normalizado = normalizar(termo)
    if not termo_normalizado:
        return False
    padrao = rf"(?<![a-z0-9]){re.escape(termo_normalizado)}(?![a-z0-9])"
    return re.search(padrao, alvo) is not None


def categoria_objeto(objeto: str) -> str:
    alvo = normalizar(objeto)
    for categoria, termos in _CATEGORIAS:
        if any(_contem_termo_de_categoria(alvo, termo) for termo in termos):
            return categoria
    return "outros_bens"


# ------------------------------------------------- filtro de aquisição de bens

_AQUISICAO = re.compile(
    r"\b(aquisicao|aquisicoes|compra|fornecimento|registro de precos para (a )?aquisicao)\b"
)

#: Marcadores de objeto fora do escopo da v1 (serviços, obras, engenharia).
_FORA_DE_ESCOPO = re.compile(
    r"(?<![a-z0-9])(?:"
    r"prestacao de servicos?|servicos?|obra|obras|engenharia|reformas?|"
    r"internac(?:ao|oes) hospitalar(?:es)?|exames? laborator(?:ial|iais)|"
    r"consultas?|procedimentos?|atendimentos?|construcao de|ampliacao de|"
    r"pavimentacao|locac(?:ao|oes)|aluguel de|"
    r"contratacao de empresa (especializada )?para (a )?(prestacao|execucao|realizacao)|"
    r"mao de obra|terceirizacao|manutenc(?:ao|oes)|consultoria|assessoria|capacitacao|"
    r"treinamento|seguro|transporte escolar|coleta de residuos?|show|artistic(?:o|a|os|as)?|"
    r"leilao|credenciamento|instalacao de|implantacao de|desenvolvimento de|"
    r"suporte tecnico|energia(?: eletrica)?"
    r")(?![a-z0-9])"
)


def parece_aquisicao_de_bens(objeto: str) -> bool:
    """Heurística de triagem para "aquisição de bens comuns".

    É deliberadamente conservadora: prefere descartar um objeto ambíguo a
    admitir um serviço no corpus. Não substitui a decisão de escopo do
    ``scope.md`` — é apenas o filtro de coleta.
    """
    alvo = normalizar(objeto)
    if _FORA_DE_ESCOPO.search(alvo):
        return False
    if _AQUISICAO.search(alvo):
        return True

    # Alguns órgãos publicam apenas uma lista inequívoca de bens (por
    # exemplo, "cateteres periféricos" ou "SRP informática"), sem verbo de
    # aquisição. Uma categoria conhecida é evidência suficiente; texto
    # genérico continua rejeitado.
    return categoria_objeto(alvo) != "outros_bens"


def classificar_perfil_inicial(
    *,
    esfera: str | None,
    amparo_legal_nome: str | None,
    modalidade_id: int | str | None,
    objeto: str | None,
) -> str:
    """Classifica o perfil municipal de bens comuns do Pregão Eletrônico."""
    esfera_n = (esfera or "").strip().upper()
    amparo = normalizar(amparo_legal_nome or "")
    try:
        modalidade = int(modalidade_id) if not isinstance(modalidade_id, bool) else None
    except (TypeError, ValueError):
        modalidade = None
    lei = "lei 14 133" in amparo
    if (
        esfera_n == "M"
        and lei
        and modalidade == 6
        and parece_aquisicao_de_bens(objeto or "")
    ):
        return PERFIL_SUPPORTED
    return PERFIL_FORA


#: ``tipoDocumentoNome`` dos anexos de contrato → papel. Esses anexos vêm com
#: ``tipoDocumentoId`` nulo no PNCP, então só o nome está disponível.
_TIPO_ANEXO_CONTRATO = {
    "contrato": CONTRATO,
    "termo de contrato": CONTRATO,
    "termo aditivo": OUTROS,
    "nota de empenho": OUTROS,
    "termo de rescisao": OUTROS,
    "termo de apostilamento": OUTROS,
}


def papel_documento_contrato(tipo_nome: str | None, titulo: str) -> str:
    """Papel de um arquivo publicado sob um contrato do PNCP."""
    chave = normalizar(tipo_nome or "")
    if chave in _TIPO_ANEXO_CONTRATO:
        return _TIPO_ANEXO_CONTRATO[chave]
    return papel_documento(None, titulo)
