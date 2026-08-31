"""Representação imutável dos blocos produzidos pela ingestão da R3.

Os modelos deste módulo são deliberadamente separados de ``licita_core``. A
R2 modela requisitos e evidências; a R3 ainda não interpreta o conteúdo e
precisa manter a estrutura física e o texto retornado pelas bibliotecas de
leitura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping


class DocumentFormat(str, Enum):
    """Formato de arquivo suportado pelo primeiro extrator da R3."""

    PDF = "PDF"
    DOCX = "DOCX"


class BlockType(str, Enum):
    """Tipos de bloco que o extrator consegue preservar sem interpretação."""

    PARAGRAPH = "PARAGRAPH"
    TABLE = "TABLE"
    TABLE_CELL = "TABLE_CELL"
    LIST = "LIST"
    HEADER = "HEADER"
    IMAGE = "IMAGE"


# ``BlockKind`` é um nome conveniente para consumidores que não usam o nome
# ``type`` do schema da R2. Os valores continuam alinhados ao ``BlockType`` do
# core sem importar o módulo de R2.
BlockKind = BlockType


class PageKind(str, Enum):
    """Origem do número de página guardado em um bloco."""

    PHYSICAL = "PHYSICAL"
    LOGICAL = "LOGICAL"


BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class StructuredBlock:
    """Um bloco navegável até o documento de origem.

    O texto de parágrafos e células nunca é normalizado, aparado ou convertido
    em minúsculas. Para PDF, ele é o texto devolvido pelo PyMuPDF (incluindo
    quebras que a API devolver); para DOCX, é o texto devolvido por
    ``python-docx``. O ``text`` do contêiner de tabela é uma agregação
    determinística das células e vem marcado como derivado em ``metadata``.

    Tabelas são blocos de primeiro nível e carregam células em ``children``.
    As células, por sua vez, podem carregar os parágrafos que existem dentro
    delas. Assim o consumidor pode navegar pelo bloco de tabela ou chegar ao
    trecho de uma célula/parágrafo sem perder a localização.
    """

    document_id: str
    id: str
    type: BlockType
    text: str
    page: int | None
    index: int
    page_kind: PageKind | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    parent_id: str | None = None
    bbox: BBox | None = None
    style_name: str | None = None
    children: tuple["StructuredBlock", ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id não pode ser vazio")
        if not self.id.strip():
            raise ValueError("id do bloco não pode ser vazio")
        if self.page is not None and self.page < 1:
            raise ValueError("páginas começam em 1")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("bbox deve conter x0, y0, x1 e y1")

    @property
    def block_id(self) -> str:
        """Alias para o nome usado por ``Evidence.block_id`` na R2."""

        return self.id

    @property
    def kind(self) -> BlockType:
        """Alias legível para ``type``."""

        return self.type

    @property
    def block_type(self) -> BlockType:
        """Alias compatível com consumidores que evitam o nome ``type``."""

        return self.type

    @property
    def original_text(self) -> str:
        """Texto preservado do bloco (sem qualquer normalização)."""

        return self.text

    @property
    def cells(self) -> tuple["StructuredBlock", ...]:
        """Células diretas de um bloco de tabela."""

        return tuple(child for child in self.children if child.type is BlockType.TABLE_CELL)

    def iter_blocks(self, *, include_self: bool = True) -> Iterator["StructuredBlock"]:
        """Percorre o bloco e seus descendentes em ordem documental."""

        if include_self:
            yield self
        for child in self.children:
            yield from child.iter_blocks()

    def to_dict(self) -> dict[str, Any]:
        """Converte o bloco para uma estrutura JSON-serializável."""

        return {
            "document_id": self.document_id,
            "id": self.id,
            "type": self.type.value,
            "text": self.text,
            "page": self.page,
            "page_kind": self.page_kind.value if self.page_kind is not None else None,
            "index": self.index,
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "parent_id": self.parent_id,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "style_name": self.style_name,
            "children": [child.to_dict() for child in self.children],
            "metadata": dict(self.metadata),
        }

    # O nome acompanha a convenção dos modelos Pydantic existentes sem tornar
    # a ingestão dependente da R2.
    model_dump = to_dict


# Nome explícito para quem quer tratar o resultado como ``DocumentBlock`` sem
# importar o modelo da R2. A classe permanece a mesma, não uma cópia.
DocumentBlock = StructuredBlock


@dataclass(frozen=True, slots=True)
class StructuredPage:
    """Página física de um PDF e os blocos de primeiro nível nela encontrados."""

    document_id: str
    number: int
    text: str
    blocks: tuple[StructuredBlock, ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id não pode ser vazio")
        if self.number < 1:
            raise ValueError("páginas começam em 1")

    @property
    def page(self) -> int:
        """Alias para ``number`` ao navegar por uma evidência."""

        return self.number

    @property
    def original_text(self) -> str:
        """Texto bruto devolvido pelo PyMuPDF para esta página."""

        return self.text

    def iter_blocks(self) -> Iterator[StructuredBlock]:
        for block in self.blocks:
            yield from block.iter_blocks()

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "number": self.number,
            "text": self.text,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    model_dump = to_dict


@dataclass(frozen=True, slots=True)
class StructuredDocument:
    """Resultado de ``documento → structured blocks``.

    ``pages`` contém páginas físicas quando o formato oferece essa informação
    (PDF). DOCX não guarda a paginação renderizada de forma confiável no
    arquivo XML; nele ``page`` é uma página lógica, iniciada em 1 e avançada
    somente por quebras de página explícitas. O tipo em ``page_kind`` deixa
    essa diferença visível para não apresentar uma estimativa como paginação
    física.
    """

    document_id: str
    format: DocumentFormat
    source: str
    sha256: str
    blocks: tuple[StructuredBlock, ...] = ()
    pages: tuple[StructuredPage, ...] = ()
    page_count: int | None = None
    page_kind: PageKind | None = None
    logical_page_count: int | None = None
    ocr_required_pages: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id não pode ser vazio")
        if not self.source.strip():
            raise ValueError("source não pode ser vazio")
        if len(self.sha256) != 64:
            raise ValueError("sha256 deve ser um digest hexadecimal de 64 caracteres")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValueError("sha256 deve ser hexadecimal") from exc
        if self.page_count is not None and self.page_count < 0:
            raise ValueError("page_count não pode ser negativo")

    @property
    def id(self) -> str:
        """Alias de ``document_id`` para a nomenclatura da R2."""

        return self.document_id

    @property
    def name(self) -> str:
        return Path(self.source).name

    @property
    def source_path(self) -> Path:
        return Path(self.source)

    @property
    def paragraphs(self) -> tuple[StructuredBlock, ...]:
        return tuple(
            block
            for block in self.iter_blocks()
            if block.type is BlockType.PARAGRAPH
        )

    @property
    def tables(self) -> tuple[StructuredBlock, ...]:
        return tuple(
            block for block in self.iter_blocks() if block.type is BlockType.TABLE
        )

    @property
    def text(self) -> str:
        """Texto agregado para consulta.

        Em PDF a concatenação é exata em relação às páginas extraídas. Em
        DOCX não há um fluxo textual único no OOXML; nesse caso a propriedade
        é apenas uma conveniência derivada dos blocos de primeiro nível.
        """

        if self.pages:
            return "".join(page.text for page in self.pages)
        return "\n".join(block.text for block in self.blocks)

    @property
    def original_text(self) -> str:
        """Alias de ``text`` para APIs que usam o nome da R2."""

        return self.text

    def iter_blocks(self, *, include_children: bool = True) -> Iterator[StructuredBlock]:
        """Percorre blocos em ordem documental.

        Por padrão células e parágrafos aninhados em tabelas também aparecem.
        ``include_children=False`` devolve apenas os blocos de primeiro nível.
        """

        for block in self.blocks:
            if include_children:
                yield from block.iter_blocks()
            else:
                yield block

    def get_block(self, block_id: str) -> StructuredBlock:
        """Encontra um bloco pelo id ou informa claramente que ele não existe."""

        for block in self.iter_blocks():
            if block.id == block_id:
                return block
        raise KeyError(block_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "format": self.format.value,
            "source": self.source,
            "sha256": self.sha256,
            "page_count": self.page_count,
            "page_kind": self.page_kind.value if self.page_kind is not None else None,
            "logical_page_count": self.logical_page_count,
            "ocr_required_pages": list(self.ocr_required_pages),
            "blocks": [block.to_dict() for block in self.blocks],
            "pages": [page.to_dict() for page in self.pages],
        }

    model_dump = to_dict


__all__ = [
    "BBox",
    "BlockKind",
    "BlockType",
    "DocumentBlock",
    "DocumentFormat",
    "PageKind",
    "StructuredBlock",
    "StructuredDocument",
    "StructuredPage",
]
