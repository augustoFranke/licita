"""Schema Pydantic provisório v0.1.0 da representação estruturada de processos.

Coisa provisória: ainda NÃO declara a R2 concluída. A R2 só passará após
conversão manual de cinco processos reais para este schema sem que os campos
verificáveis exijam recorrer de volta ao texto livre.

O texto original é preservado SOMENTE em ``Section.title_original``,
``DocumentBlock.text`` e ``Evidence.quote``; nunca é usado como entrada das
regras.
"""

from collections.abc import Iterator, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from math import isfinite
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "0.1.0"


NonEmptyString = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"\S"),
]

# ---------------------------------------------------------------- enums

class DocumentType(str, Enum):
    DFD = "DFD"
    ETP = "ETP"
    TR = "TR"
    EDITAL = "EDITAL"
    CONTRATO = "CONTRATO"
    PESQUISA_PRECOS = "PESQUISA_PRECOS"
    OUTROS = "OUTROS"


class DocumentFormat(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"


class BlockType(str, Enum):
    PARAGRAPH = "PARAGRAPH"
    TABLE = "TABLE"
    TABLE_CELL = "TABLE_CELL"
    LIST = "LIST"
    HEADER = "HEADER"
    IMAGE = "IMAGE"


class FieldType(str, Enum):
    QUANTITY = "QUANTITY"
    DELIVERY_DEADLINE = "DELIVERY_DEADLINE"
    CONTRACT_TERM = "CONTRACT_TERM"
    WARRANTY_TERM = "WARRANTY_TERM"
    UNIT_PRICE = "UNIT_PRICE"
    TOTAL_PRICE = "TOTAL_PRICE"
    DELIVERY_LOCATION = "DELIVERY_LOCATION"
    RECEIPT_DEADLINE = "RECEIPT_DEADLINE"
    PAYMENT_DEADLINE = "PAYMENT_DEADLINE"


class RequirementOperator(str, Enum):
    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    BETWEEN = "BETWEEN"
    IN = "IN"
    CONTAINS = "CONTAINS"
    EXISTS = "EXISTS"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    INFO = "INFO"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class ReviewStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class FindingCategory(str, Enum):
    STRUCTURE = "STRUCTURE"
    CONSISTENCY = "CONSISTENCY"
    MARKET = "MARKET"
    HISTORY = "HISTORY"
    PRICE = "PRICE"
    EXECUTION = "EXECUTION"
    COMPLIANCE = "COMPLIANCE"


class SchemaModel(BaseModel):
    """Modelo comum com rejeição explícita de campos desconhecidos."""

    model_config = ConfigDict(extra="forbid")


# Valor simples e tipado: número, texto ou data. Unidades ficam como strings
# normalizadas por ora, para evitar enums prematuros.
#
# O ramo ``date`` não transforma strings ISO automaticamente: JSON não permite
# distinguir uma data de um texto sem um discriminador. Assim, strings ISO
# continuam strings; datas só são preservadas quando recebidas como ``date``.
SimpleValue = Union[str, int, float, Decimal, date]
RequirementScalar = Union[SimpleValue, bool]
RequirementValue = Union[RequirementScalar, list[RequirementScalar]]


# ---------------------------------------------------------------- evidence

class Evidence(SchemaModel):
    """Âncora navegável até o trecho original de um documento."""

    document_id: NonEmptyString = Field(..., description="Id do documento de origem.")
    page: StrictInt = Field(..., ge=1, description="Página começando em 1.")
    block_id: NonEmptyString = Field(..., description="Id do bloco no documento.")
    quote: NonEmptyString = Field(..., description="Texto original preservado.")
    attr: NonEmptyString | None = Field(
        default=None,
        description="Atributo ao qual a evidência se refere.",
    )

    @field_validator("page")
    @classmethod
    def _page_nonzero(cls, v: int) -> int:
        if v < 1:
            raise ValueError("páginas começam em 1")
        return v


# ---------------------------------------------------------------- document structure

class DocumentBlock(SchemaModel):
    """Bloco elementar do documento: parágrafo, célula, item de lista etc."""

    id: NonEmptyString = Field(..., description="Id estável do bloco.")
    type: BlockType
    text: NonEmptyString = Field(..., description="Texto original do bloco.")


class Section(SchemaModel):
    """Seção com título original e, opcionalmente, tipo normalizado."""

    id: NonEmptyString
    title_original: NonEmptyString = Field(..., description="Título original da seção.")
    section_type_normalized: NonEmptyString | None = Field(
        default=None,
        description="Tipo normalizado da seção, quando disponível.",
    )
    blocks: list[DocumentBlock] = Field(default_factory=list)
    evidence: Evidence


# ---------------------------------------------------------------- structured content

class FieldValue(SchemaModel):
    """Valor estruturado extraído (quantidade, prazo, valor etc.).

    Quantidades são números positivos e valores monetários são normalizados
    para ``Decimal``. A unidade é opcional no schema; a RULE-002 exige
    quantidade e unidade de fornecimento no item.
    """

    field_type: FieldType
    value: SimpleValue
    unit: NonEmptyString | None = Field(
        default=None,
        description="Unidade normalizada (string), não enum.",
    )
    item_id: NonEmptyString | None = None
    evidence: list[Evidence] = Field(..., min_length=1)
    review_status: ReviewStatus = ReviewStatus.EXTRACTED

    @model_validator(mode="before")
    @classmethod
    def _validate_typed_value(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data

        raw_field_type = data.get("field_type")
        try:
            field_type = FieldType(raw_field_type)
        except (TypeError, ValueError):
            # A validação do enum emitirá a mensagem apropriada depois.
            return data

        raw_value = data.get("value")
        cls._validate_general_value(raw_value, field_type)

        if field_type is FieldType.QUANTITY:
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float, Decimal))
                or not cls._is_positive_finite_number(raw_value)
            ):
                raise ValueError(
                    "FieldValue com field_type=QUANTITY exige um número positivo"
                )

        if field_type in (FieldType.UNIT_PRICE, FieldType.TOTAL_PRICE):
            normalized = cls._to_non_negative_decimal(raw_value, field_type)
            normalized_data = dict(data)
            normalized_data["value"] = normalized
            return normalized_data

        return data

    @staticmethod
    def _validate_general_value(value: Any, field_type: FieldType) -> None:
        if isinstance(value, bool):
            if field_type is FieldType.QUANTITY:
                raise ValueError(
                    "FieldValue com field_type=QUANTITY não aceita bool; "
                    "exige um número positivo"
                )
            raise ValueError(
                f"FieldValue com field_type={field_type.value} não aceita bool"
            )

        if isinstance(value, float) and not isfinite(value):
            if field_type is FieldType.QUANTITY:
                raise ValueError(
                    "FieldValue com field_type=QUANTITY exige um número positivo "
                    "e finito"
                )
            raise ValueError(
                f"FieldValue com field_type={field_type.value} "
                "exige valor numérico finito"
            )

        if isinstance(value, Decimal) and not value.is_finite():
            if field_type is FieldType.QUANTITY:
                raise ValueError(
                    "FieldValue com field_type=QUANTITY exige um número positivo "
                    "e finito"
                )
            raise ValueError(
                f"FieldValue com field_type={field_type.value} "
                "exige valor numérico finito"
            )

        if isinstance(value, str) and not value.strip():
            raise ValueError(
                f"FieldValue com field_type={field_type.value} "
                "exige string não vazia"
            )

    @staticmethod
    def _is_positive_finite_number(value: int | float | Decimal) -> bool:
        if isinstance(value, float) and not isfinite(value):
            return False
        if isinstance(value, Decimal) and not value.is_finite():
            return False
        return value > 0

    @staticmethod
    def _to_non_negative_decimal(value: Any, field_type: FieldType) -> Decimal:
        if isinstance(value, bool):
            raise ValueError(
                f"FieldValue com field_type={field_type.value} não aceita bool"
            )
        try:
            normalized = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(
                f"FieldValue com field_type={field_type.value} exige valor monetário numérico"
            ) from None
        if not normalized.is_finite():
            raise ValueError(
                f"FieldValue com field_type={field_type.value} exige valor monetário finito"
            )
        if normalized < 0:
            raise ValueError(
                f"FieldValue com field_type={field_type.value} não aceita valor negativo"
            )
        return normalized


class Requirement(SchemaModel):
    """Requisito estruturado (atributo, operador, valor, unidade, item)."""

    attribute: NonEmptyString
    operator: RequirementOperator
    value: RequirementValue
    unit: NonEmptyString | None = None
    item_id: NonEmptyString | None = None
    evidence: list[Evidence] = Field(..., min_length=1)
    review_status: ReviewStatus = ReviewStatus.EXTRACTED

    @model_validator(mode="before")
    @classmethod
    def _validate_operator_value(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data

        raw_operator = data.get("operator")
        try:
            operator = RequirementOperator(raw_operator)
        except (TypeError, ValueError):
            # A validação do enum emitirá a mensagem apropriada depois.
            return data

        value = data.get("value")
        if operator is RequirementOperator.BETWEEN:
            values = cls._ordered_collection_or_error(value, operator)
            if len(values) != 2:
                raise ValueError(
                    "Requirement com operador BETWEEN exige coleção ordenada "
                    "(list/tuple) com exatamente 2 valores"
                )
            cls._validate_between_values(values, operator)
            normalized_data = dict(data)
            normalized_data["value"] = values
            return normalized_data

        if operator is RequirementOperator.IN:
            values = cls._collection_or_error(value, operator)
            if not values:
                raise ValueError(
                    "Requirement com operador IN exige coleção não vazia"
                )
            cls._ensure_scalar_collection(values, operator)
            normalized_data = dict(data)
            normalized_data["value"] = values
            return normalized_data

        if operator is RequirementOperator.EXISTS:
            if not isinstance(value, bool):
                raise ValueError(
                    "Requirement com operador EXISTS exige valor booleano"
                )
            return data

        if operator in (
            RequirementOperator.GREATER_THAN,
            RequirementOperator.GREATER_THAN_OR_EQUAL,
            RequirementOperator.LESS_THAN,
            RequirementOperator.LESS_THAN_OR_EQUAL,
        ):
            if not cls._is_finite_number_or_date(value):
                raise ValueError(
                    f"Requirement com operador {operator.value} exige valor numérico finito ou date"
                )
            return data

        if operator is RequirementOperator.CONTAINS:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "Requirement com operador CONTAINS exige string não vazia"
                )
            return data

        if not cls._is_valid_scalar(value):
            raise ValueError(
                f"Requirement com operador {operator.value} exige valor escalar válido"
            )
        return data

    @classmethod
    def _validate_between_values(
        cls, values: list[Any], operator: RequirementOperator
    ) -> None:
        if any(isinstance(value, bool) for value in values):
            raise ValueError(
                f"Requirement com operador {operator.value} não aceita bool"
            )
        cls._ensure_scalar_collection(values, operator)
        first, last = values
        try:
            in_order = first <= last
        except (TypeError, ValueError):
            raise ValueError(
                f"Requirement com operador {operator.value} exige valores comparáveis entre si"
            ) from None
        if not in_order:
            raise ValueError(
                f"Requirement com operador {operator.value} exige limite inicial menor ou igual ao limite final"
            )

    @staticmethod
    def _ordered_collection_or_error(
        value: Any, operator: RequirementOperator
    ) -> list[Any]:
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                f"Requirement com operador {operator.value} exige coleção ordenada "
                "(list/tuple)"
            )
        return list(value)

    @staticmethod
    def _collection_or_error(value: Any, operator: RequirementOperator) -> list[Any]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError(
                f"Requirement com operador {operator.value} exige uma coleção"
            )
        return list(value)

    @classmethod
    def _ensure_scalar_collection(
        cls, values: list[Any], operator: RequirementOperator
    ) -> None:
        for value in values:
            if not cls._is_scalar(value):
                raise ValueError(
                    f"Requirement com operador {operator.value} exige valores escalares na coleção"
                )
            if isinstance(value, str) and not value.strip():
                raise ValueError(
                    f"Requirement com operador {operator.value} exige que cada "
                    "string seja não vazia na coleção"
                )
            if cls._is_numeric(value) and not cls._is_finite_numeric(value):
                raise ValueError(
                    f"Requirement com operador {operator.value} não aceita valores numéricos não finitos"
                )

    @classmethod
    def _is_valid_scalar(cls, value: Any) -> bool:
        if isinstance(value, str) and not value.strip():
            return False
        return cls._is_scalar(value) and (
            not cls._is_numeric(value) or cls._is_finite_numeric(value)
        )

    @staticmethod
    def _is_scalar(value: Any) -> bool:
        return isinstance(value, (str, int, float, Decimal, date, bool))

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)

    @staticmethod
    def _is_finite_numeric(value: int | float | Decimal) -> bool:
        if isinstance(value, float):
            return isfinite(value)
        if isinstance(value, Decimal):
            return value.is_finite()
        return True

    @classmethod
    def _is_finite_number_or_date(cls, value: Any) -> bool:
        return isinstance(value, date) or (
            cls._is_numeric(value) and cls._is_finite_numeric(value)
        )


class Item(SchemaModel):
    """Item de fornecimento no documento."""

    id: NonEmptyString
    description: NonEmptyString | None = None
    field_values: list[FieldValue] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_nested_item_ids(self) -> "Item":
        for field_value in self.field_values:
            if field_value.item_id is not None and field_value.item_id != self.id:
                raise ValueError(
                    f"FieldValue.item_id divergente: Item pai {self.id}, "
                    f"referência {field_value.item_id}"
                )
        for requirement in self.requirements:
            if requirement.item_id is not None and requirement.item_id != self.id:
                raise ValueError(
                    f"Requirement.item_id divergente: Item pai {self.id}, "
                    f"referência {requirement.item_id}"
                )
        return self


# ---------------------------------------------------------------- document / process

class Document(SchemaModel):
    """Documento da cadeia (tipos de ``01_REQUIREMENTS.md``)."""

    id: NonEmptyString
    type: DocumentType
    format: DocumentFormat
    title: NonEmptyString | None = None
    sections: list[Section] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    field_values: list[FieldValue] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_document_item_ids(self) -> "Document":
        item_ids = {item.id for item in self.items}
        for field_value in self.field_values:
            if field_value.item_id is not None and field_value.item_id not in item_ids:
                raise ValueError(
                    f"FieldValue.item_id inválido no documento {self.id}: "
                    f"item {field_value.item_id} não encontrado"
                )
        for requirement in self.requirements:
            if requirement.item_id is not None and requirement.item_id not in item_ids:
                raise ValueError(
                    f"Requirement.item_id inválido no documento {self.id}: "
                    f"item {requirement.item_id} não encontrado"
                )
        return self


class Finding(SchemaModel):
    """Achado/risco para revisão humana. Nunca 'aprovado'/'reprovado'."""

    id: NonEmptyString | None = None
    rule_id: NonEmptyString
    category: FindingCategory | None = None
    severity: Severity
    confidence: float | None = Field(default=None, ge=0, le=1)
    title: NonEmptyString | None = None
    message: NonEmptyString
    item_id: NonEmptyString | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(..., min_length=1)
    status: FindingStatus = FindingStatus.OPEN

    @model_validator(mode="after")
    def _default_title(self) -> "Finding":
        if self.title is None:
            self.title = self.message
        return self


class ProcurementProcess(SchemaModel):
    """Raiz do modelo estruturado de um processo."""

    id: NonEmptyString
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    documents: list[Document] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_process_integrity(self) -> "ProcurementProcess":
        documents_by_id: dict[str, Document] = {}
        blocks_by_document: dict[str, dict[str, DocumentBlock]] = {}
        item_ids_by_document: dict[str, set[str]] = {}
        seen_block_ids: set[str] = set()

        for document in self.documents:
            if document.id in documents_by_id:
                raise ValueError(f"ID de documento duplicado: {document.id}")
            documents_by_id[document.id] = document

            item_ids: set[str] = set()
            for item in document.items:
                if item.id in item_ids:
                    raise ValueError(
                        f"ID de item duplicado no documento {document.id}: {item.id}"
                    )
                item_ids.add(item.id)

            document_blocks: dict[str, DocumentBlock] = {}
            for section in document.sections:
                for block in section.blocks:
                    if block.id in seen_block_ids:
                        raise ValueError(f"ID de bloco duplicado: {block.id}")
                    seen_block_ids.add(block.id)
                    document_blocks[block.id] = block
            blocks_by_document[document.id] = document_blocks
            item_ids_by_document[document.id] = item_ids

        for evidence in self._iter_evidence():
            if evidence.document_id not in documents_by_id:
                raise ValueError(
                    f"Evidence.document_id inválido: documento não encontrado "
                    f"({evidence.document_id})"
                )
            block = blocks_by_document[evidence.document_id].get(evidence.block_id)
            if block is None:
                raise ValueError(
                    f"Evidence.block_id inválido: bloco {evidence.block_id} "
                    f"não encontrado no documento {evidence.document_id}"
                )
            if evidence.quote not in block.text:
                raise ValueError(
                    f"Evidence.quote inválida: quote não encontrado no block_id "
                    f"{evidence.block_id} do documento {evidence.document_id}"
                )

        for finding in self.findings:
            if finding.item_id is None:
                continue
            evidence_document_ids = {evidence.document_id for evidence in finding.evidence}
            if not any(
                finding.item_id in item_ids_by_document[document_id]
                for document_id in evidence_document_ids
            ):
                referenced_documents = ", ".join(sorted(evidence_document_ids))
                raise ValueError(
                    f"Finding.item_id inválido: item {finding.item_id} não encontrado "
                    f"em nenhum documento das evidências ({referenced_documents})"
                )

        return self

    def _iter_evidence(self) -> Iterator[Evidence]:
        for finding in self.findings:
            yield from finding.evidence

        for document in self.documents:
            for section in document.sections:
                yield section.evidence
            for field_value in document.field_values:
                yield from field_value.evidence
            for requirement in document.requirements:
                yield from requirement.evidence
            for item in document.items:
                yield from item.evidence
                for field_value in item.field_values:
                    yield from field_value.evidence
                for requirement in item.requirements:
                    yield from requirement.evidence