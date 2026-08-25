"""Classificação de objetos de compra e de tipos documentais do PNCP.

Duas decisões independentes vivem aqui:

- ``papel_documento`` — a que elo da cadeia ``ETP → TR → edital → contrato`` um
  arquivo pertence. O ``tipoDocumentoId`` do PNCP é autoritativo quando existe;
  o título é usado apenas para resgatar arquivos publicados como "Outros
  Documentos", que é onde a maior parte dos TRs municipais aparece.
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

ETP = "ETP"
TR = "TR"
EDITAL = "EDITAL"
CONTRATO = "CONTRATO"
AVISO_DIRETA = "AVISO_CONTRATACAO_DIRETA"
MINUTA_CONTRATO = "MINUTA_CONTRATO"
OUTRO = "OUTRO"

#: ``tipoDocumentoId`` do PNCP → papel na cadeia documental da v1.
TIPO_PNCP_PARA_PAPEL = {
    1: AVISO_DIRETA,
    2: EDITAL,
    3: MINUTA_CONTRATO,
    4: TR,
    7: ETP,
    12: CONTRATO,
}

#: Regras de título, aplicadas em ordem — a primeira que casar vence.
_REGRAS_TITULO: tuple[tuple[str, re.Pattern[str]], ...] = (
    (ETP, re.compile(r"\b(estudo(s)? tecnico(s)? preliminar|\betp\b)")),
    (TR, re.compile(r"\b(termo de referencia|termo referencia|\btr\b)")),
    (MINUTA_CONTRATO, re.compile(r"\bminuta.{0,20}\b(contrato|contratual)")),
    (CONTRATO, re.compile(r"\bcontrato\b")),
    (AVISO_DIRETA, re.compile(r"\baviso de contratacao direta\b")),
    (EDITAL, re.compile(r"\bedital\b")),
)

#: Títulos que contêm a palavra-chave mas não são o documento em si.
_TITULO_NEGATIVO = re.compile(
    r"\b(errata|retificacao|adendo|esclarecimento|impugnacao|recurso|"
    r"resultado|ata de (sessao|realizacao)|homologacao|adjudicacao|"
    r"aviso de licitacao|extrato|publicacao|comprovante)\b"
)


def papel_documento(tipo_id: int | None, titulo: str) -> str:
    """Papel do arquivo na cadeia documental.

    O ``tipoDocumentoId`` prevalece. Só caímos no título quando o PNCP
    classificou o arquivo como genérico (``16 — Outros Documentos``) ou não
    informou tipo.
    """
    if tipo_id in TIPO_PNCP_PARA_PAPEL:
        return TIPO_PNCP_PARA_PAPEL[tipo_id]
    if tipo_id not in (None, 16):
        return OUTRO
    alvo = normalizar(titulo)
    if _TITULO_NEGATIVO.search(alvo):
        return OUTRO
    for papel, padrao in _REGRAS_TITULO:
        if padrao.search(alvo):
            return papel
    return OUTRO


#: Papéis que a v1 ingere (scope.md, nível documental).
PAPEIS_DA_CADEIA = (ETP, TR, EDITAL, CONTRATO)


# ------------------------------------------------------- categoria do objeto

#: Categoria → termos que a caracterizam. Ordem importa: a primeira categoria
#: com algum termo presente vence, então as mais específicas vêm antes.
_CATEGORIAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "medicamentos_e_insumos_farmaceuticos",
        ("medicamento", "farmaco", "insumo farmaceutico", "soro", "vacina", "psicotropico"),
    ),
    (
        "material_medico_hospitalar",
        (
            "material medico", "medico hospitalar", "hospitalar", "odontologic",
            "laboratorial", "seringa", "luva de procedimento", "cateter", "curativo",
            "material penso", "correlato",
        ),
    ),
    (
        "equipamentos_medico_hospitalares",
        ("equipamento medico", "equipamento hospitalar", "aspirador cirurgic",
         "cadeira de rodas", "desfibrilador", "monitor multiparametro", "autoclave"),
    ),
    (
        "generos_alimenticios",
        ("genero alimenticio", "alimenticio", "alimentacao escolar", "merenda",
         "hortifrut", "carne", "leite", "cesta basica", "panificacao", "paes"),
    ),
    (
        "material_de_limpeza_e_higiene",
        ("material de limpeza", "produto de limpeza", "higiene", "higienizacao",
         "saneante", "descartavel", "copa e cozinha"),
    ),
    (
        "material_de_expediente_e_escritorio",
        ("material de expediente", "material de escritorio", "papelaria", "papel a4",
         "suprimento de informatica", "cartucho", "toner", "material grafico"),
    ),
    (
        "mobiliario",
        ("mobiliario", "movel", "moveis", "cadeira", "mesa", "armario", "estante",
         "longarina", "poltrona"),
    ),
    (
        "equipamentos_de_informatica",
        ("informatica", "computador", "notebook", "microcomputador", "impressora",
         "scanner", "servidor de rede", "switch", "nobreak", "monitor de video",
         "tablet", "licenciamento de software", "software"),
    ),
    (
        "eletrodomesticos_e_eletroeletronicos",
        ("eletrodomestico", "eletroeletronic", "ar condicionado", "ar-condicionado",
         "condicionador de ar", "refrigerador", "freezer", "televisor", "bebedouro",
         "ventilador", "fogao"),
    ),
    (
        "veiculos_pecas_e_combustiveis",
        ("veiculo", "automovel", "caminhao", "onibus", "ambulancia", "pneu",
         "peca automotiva", "combustivel", "oleo lubrificante", "motocicleta"),
    ),
    (
        "material_de_construcao_e_ferramentas",
        ("material de construcao", "hidraulic", "ferramenta", "cimento", "tinta",
         "material eletrico", "iluminacao publica", "lampada"),
    ),
    (
        "epi_uniformes_e_textil",
        ("epi", "equipamento de protecao individual", "uniforme", "fardamento",
         "vestuario", "enxoval", "textil", "calcado"),
    ),
    (
        "material_agropecuario_e_jardinagem",
        ("agropecuar", "semente", "muda", "fertilizante", "racao", "adubo",
         "calcario", "jardinagem"),
    ),
    (
        "material_didatico_e_esportivo",
        ("material didatico", "material escolar", "livro", "brinquedo",
         "material esportivo", "instrumento musical"),
    ),
)


def categoria_objeto(objeto: str) -> str:
    alvo = normalizar(objeto)
    for categoria, termos in _CATEGORIAS:
        if any(normalizar(t) in alvo for t in termos):
            return categoria
    return "outros_bens"


# ------------------------------------------------- filtro de aquisição de bens

_AQUISICAO = re.compile(
    r"\b(aquisicao|aquisicoes|compra|fornecimento|registro de precos para (a )?aquisicao)\b"
)

#: Marcadores de objeto fora do escopo da v1 (serviços, obras, engenharia).
_FORA_DE_ESCOPO = re.compile(
    r"\b(prestacao de servico|servicos de|servico de|obra|obras|engenharia|reforma|"
    r"construcao de|ampliacao de|pavimentacao|locacao de|aluguel de|"
    r"contratacao de empresa (especializada )?para (a )?(prestacao|execucao|realizacao)|"
    r"mao de obra|terceirizacao|manutencao (preventiva|corretiva)|consultoria|"
    r"assessoria|capacitacao|treinamento|seguro|transporte escolar|"
    r"coleta de residuo|show|artistic|leilao|credenciamento)\b"
)


def parece_aquisicao_de_bens(objeto: str) -> bool:
    """Heurística de triagem para "aquisição de bens comuns".

    É deliberadamente conservadora: prefere descartar um objeto ambíguo a
    admitir um serviço no corpus. Não substitui a decisão de escopo do
    ``scope.md`` — é apenas o filtro de coleta.
    """
    alvo = normalizar(objeto)
    if not _AQUISICAO.search(alvo):
        return False
    return not _FORA_DE_ESCOPO.search(alvo)


#: ``tipoDocumentoNome`` dos anexos de contrato → papel. Esses anexos vêm com
#: ``tipoDocumentoId`` nulo no PNCP, então só o nome está disponível.
_TIPO_ANEXO_CONTRATO = {
    "contrato": CONTRATO,
    "termo de contrato": CONTRATO,
    "termo aditivo": OUTRO,       # altera o contrato; não é o instrumento inicial
    "nota de empenho": OUTRO,     # substitui o contrato em alguns casos, mas não é ele
    "termo de rescisao": OUTRO,
    "termo de apostilamento": OUTRO,
}


def papel_documento_contrato(tipo_nome: str | None, titulo: str) -> str:
    """Papel de um arquivo publicado sob um contrato do PNCP."""
    chave = normalizar(tipo_nome or "")
    if chave in _TIPO_ANEXO_CONTRATO:
        return _TIPO_ANEXO_CONTRATO[chave]
    return papel_documento(None, titulo)
