"""Validação de anotações manuais e cobertura observável do schema R2.

Este módulo valida arquivos JSON com ``ProcurementProcess`` e conta os campos
estruturados já representados. Cobertura é um diagnóstico, não um gate: um
campo ausente no relatório não torna uma anotação inválida e este módulo não
declara a R2 concluída.

Uso direto, sem novo entry point no projeto::

    python -m licita_core.r2_annotations anotacao-1.json anotacao-2.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from licita_core.schema import (
    Document,
    DocumentType,
    FieldType,
    ProcurementProcess,
)

REQUIREMENT_COVERAGE_FIELD = "REQUIREMENT"
V1_COVERAGE_FIELDS: tuple[str, ...] = tuple(
    field_type.value for field_type in FieldType
) + (REQUIREMENT_COVERAGE_FIELD,)


def _empty_field_counts() -> dict[str, int]:
    return {field_type.value: 0 for field_type in FieldType}


def _represented_and_missing(counts: dict[str, int]) -> tuple[list[str], list[str]]:
    represented = [name for name in V1_COVERAGE_FIELDS if counts[name] > 0]
    missing = [name for name in V1_COVERAGE_FIELDS if counts[name] == 0]
    return represented, missing


@dataclass(frozen=True)
class DocumentCoverage:
    """Contagens de anotações estruturadas em um documento."""

    document_id: str
    document_type: str
    item_count: int
    field_value_counts: dict[str, int]
    requirement_count: int
    quantity_with_unit_count: int
    quantity_without_unit_count: int
    evidence_count: int

    @property
    def field_value_count(self) -> int:
        return sum(self.field_value_counts.values())

    @property
    def v1_counts(self) -> dict[str, int]:
        return self.field_value_counts | {
            REQUIREMENT_COVERAGE_FIELD: self.requirement_count
        }

    def to_dict(self) -> dict[str, object]:
        represented, missing = _represented_and_missing(self.v1_counts)
        return {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "items": self.item_count,
            "field_values": {
                "total": self.field_value_count,
                "by_type": dict(self.field_value_counts),
            },
            "requirements": self.requirement_count,
            "quantity_units": {
                "with_unit": self.quantity_with_unit_count,
                "without_unit": self.quantity_without_unit_count,
            },
            "evidence_anchors": self.evidence_count,
            "v1_fields": {
                "counts": self.v1_counts,
                "represented": represented,
                "unrepresented": missing,
            },
        }


@dataclass(frozen=True)
class ProcessCoverage:
    """Cobertura de uma anotação ``ProcurementProcess`` validada."""

    source: str
    process_id: str
    schema_version: str
    documents: tuple[DocumentCoverage, ...]
    finding_count: int

    @property
    def field_value_counts(self) -> dict[str, int]:
        counts = _empty_field_counts()
        for document in self.documents:
            for field_type, count in document.field_value_counts.items():
                counts[field_type] += count
        return counts

    @property
    def requirement_count(self) -> int:
        return sum(document.requirement_count for document in self.documents)

    @property
    def v1_counts(self) -> dict[str, int]:
        return self.field_value_counts | {
            REQUIREMENT_COVERAGE_FIELD: self.requirement_count
        }

    def to_dict(self) -> dict[str, object]:
        represented, missing = _represented_and_missing(self.v1_counts)
        field_counts = self.field_value_counts
        return {
            "source": self.source,
            "process_id": self.process_id,
            "schema_version": self.schema_version,
            "documents": [document.to_dict() for document in self.documents],
            "totals": {
                "documents": len(self.documents),
                "items": sum(document.item_count for document in self.documents),
                "field_values": {
                    "total": sum(field_counts.values()),
                    "by_type": field_counts,
                },
                "requirements": self.requirement_count,
                "findings": self.finding_count,
                "quantity_units": {
                    "with_unit": sum(
                        document.quantity_with_unit_count
                        for document in self.documents
                    ),
                    "without_unit": sum(
                        document.quantity_without_unit_count
                        for document in self.documents
                    ),
                },
                "evidence_anchors": sum(
                    document.evidence_count for document in self.documents
                ),
                "v1_fields": {
                    "counts": self.v1_counts,
                    "represented": represented,
                    "unrepresented": missing,
                },
            },
        }


@dataclass(frozen=True)
class AnnotationErrorDetail:
    location: str
    message: str
    error_type: str

    def to_dict(self) -> dict[str, str]:
        return {
            "location": self.location,
            "message": self.message,
            "type": self.error_type,
        }


@dataclass(frozen=True)
class AnnotationIssue:
    source: str
    kind: Literal["io", "json", "schema"]
    details: tuple[AnnotationErrorDetail, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "kind": self.kind,
            "details": [detail.to_dict() for detail in self.details],
        }


@dataclass(frozen=True)
class AnnotationReport:
    """Resultado em lote; ``valid`` significa apenas validade de arquivo/schema."""

    requested_count: int
    annotations: tuple[ProcessCoverage, ...]
    issues: tuple[AnnotationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return (
            self.requested_count > 0
            and not self.issues
            and len(self.annotations) == self.requested_count
        )

    def _aggregate_coverage(self) -> dict[str, object]:
        documents = [
            document
            for annotation in self.annotations
            for document in annotation.documents
        ]
        field_counts = _empty_field_counts()
        document_types = {document_type.value: 0 for document_type in DocumentType}
        for document in documents:
            document_types[document.document_type] += 1
            for field_type, count in document.field_value_counts.items():
                field_counts[field_type] += count

        requirement_count = sum(document.requirement_count for document in documents)
        v1_counts = field_counts | {
            REQUIREMENT_COVERAGE_FIELD: requirement_count
        }
        represented, missing = _represented_and_missing(v1_counts)
        return {
            "processes": len(self.annotations),
            "documents": {
                "total": len(documents),
                "by_type": document_types,
            },
            "items": sum(document.item_count for document in documents),
            "field_values": {
                "total": sum(field_counts.values()),
                "by_type": field_counts,
            },
            "requirements": requirement_count,
            "findings": sum(
                annotation.finding_count for annotation in self.annotations
            ),
            "quantity_units": {
                "with_unit": sum(
                    document.quantity_with_unit_count for document in documents
                ),
                "without_unit": sum(
                    document.quantity_without_unit_count for document in documents
                ),
            },
            "evidence_anchors": sum(
                document.evidence_count for document in documents
            ),
            "v1_fields": {
                "counts": v1_counts,
                "represented": represented,
                "unrepresented": missing,
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "validation": {
                "valid": self.is_valid,
                "scope": "ProcurementProcess schema only",
                "requested_files": self.requested_count,
                "validated_files": len(self.annotations),
                "invalid_files": len(self.issues),
            },
            "coverage": {
                "totals": self._aggregate_coverage(),
                "annotations": [
                    annotation.to_dict() for annotation in self.annotations
                ],
            },
            "errors": [issue.to_dict() for issue in self.issues],
        }


def load_annotation(path: str | Path) -> ProcurementProcess:
    """Carrega e valida um JSON de anotação; erros permanecem tipados."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    return ProcurementProcess.model_validate(payload)


def _document_coverage(
    document: Document,
    *,
    finding_evidence_count: int = 0,
) -> DocumentCoverage:
    field_values = [
        *document.field_values,
        *(
            field_value
            for item in document.items
            for field_value in item.field_values
        ),
    ]
    requirements = [
        *document.requirements,
        *(requirement for item in document.items for requirement in item.requirements),
    ]

    field_counter = Counter(field_value.field_type.value for field_value in field_values)
    field_counts = {
        field_type.value: field_counter[field_type.value] for field_type in FieldType
    }
    quantities = [
        field_value
        for field_value in field_values
        if field_value.field_type is FieldType.QUANTITY
    ]
    evidence_count = (
        len(document.sections)
        + sum(len(item.evidence) for item in document.items)
        + sum(len(field_value.evidence) for field_value in field_values)
        + sum(len(requirement.evidence) for requirement in requirements)
        + finding_evidence_count
    )

    return DocumentCoverage(
        document_id=document.id,
        document_type=document.type.value,
        item_count=len(document.items),
        field_value_counts=field_counts,
        requirement_count=len(requirements),
        quantity_with_unit_count=sum(
            quantity.unit is not None for quantity in quantities
        ),
        quantity_without_unit_count=sum(
            quantity.unit is None for quantity in quantities
        ),
        evidence_count=evidence_count,
    )


def build_coverage(
    process: ProcurementProcess,
    *,
    source: str | Path = "<memory>",
) -> ProcessCoverage:
    """Conta a cobertura de um processo que já passou pelo schema."""

    finding_evidence_by_document = Counter(
        evidence.document_id
        for finding in process.findings
        for evidence in finding.evidence
    )
    documents = tuple(
        _document_coverage(
            document,
            finding_evidence_count=finding_evidence_by_document[document.id],
        )
        for document in process.documents
    )
    return ProcessCoverage(
        source=str(source),
        process_id=process.id,
        schema_version=process.schema_version,
        documents=documents,
        finding_count=len(process.findings),
    )


def validate_annotation(path: str | Path) -> ProcessCoverage:
    """Valida um arquivo e retorna sua cobertura ou propaga o erro tipado."""

    return build_coverage(load_annotation(path), source=path)


def _validation_issue(path: Path, error: ValidationError) -> AnnotationIssue:
    details = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "$"
        details.append(
            AnnotationErrorDetail(
                location=location,
                message=item["msg"],
                error_type=item["type"],
            )
        )
    return AnnotationIssue(str(path), "schema", tuple(details))


def validate_annotations(paths: Iterable[str | Path]) -> AnnotationReport:
    """Valida vários arquivos sem interromper o lote no primeiro erro."""

    requested = tuple(Path(path) for path in paths)
    annotations: list[ProcessCoverage] = []
    issues: list[AnnotationIssue] = []

    for path in requested:
        try:
            annotations.append(validate_annotation(path))
        except json.JSONDecodeError as error:
            issues.append(
                AnnotationIssue(
                    str(path),
                    "json",
                    (
                        AnnotationErrorDetail(
                            location=f"line {error.lineno}, column {error.colno}",
                            message=error.msg,
                            error_type="json_invalid",
                        ),
                    ),
                )
            )
        except ValidationError as error:
            issues.append(_validation_issue(path, error))
        except (OSError, UnicodeError) as error:
            issues.append(
                AnnotationIssue(
                    str(path),
                    "io",
                    (
                        AnnotationErrorDetail(
                            location="$",
                            message=str(error),
                            error_type=type(error).__name__,
                        ),
                    ),
                )
            )

    return AnnotationReport(
        requested_count=len(requested),
        annotations=tuple(annotations),
        issues=tuple(issues),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Valida anotações ProcurementProcess e relata cobertura; "
            "não avalia o gate da R2."
        )
    )
    parser.add_argument("annotations", nargs="+", type=Path)
    args = parser.parse_args(argv)

    report = validate_annotations(args.annotations)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.is_valid else 1


if __name__ == "__main__":  # pragma: no cover - exercitado via ``main`` nos testes
    raise SystemExit(main())
