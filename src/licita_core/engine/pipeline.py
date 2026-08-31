"""Pipeline principal do Requirements Engine (R5).

Converte documentos físicos brutos (PDF/DOCX) em uma instância estruturada e validada de
``ProcurementProcess``, com itens, valores e requisitos totalmente ancorados (R3 -> R2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from licita_core.engine.field_extractor import (
    extract_document_fields,
    extract_prose_items,
)
from licita_core.engine.table_extractor import extract_items_from_tables
from licita_core.r2_skeleton import esboco_documento
from licita_core.schema import (
    Document,
    DocumentFormat,
    DocumentType,
    Evidence,
    Item,
    ProcurementProcess,
)
from licita_ingest.extractor import StructuredDocument, extract_document


class RequirementsEngine:
    """Motor de extração automática de requisitos e dados estruturados (R5)."""

    def __init__(self, version: str = "1.0.0") -> None:
        self.version = version

    def process_procurement(
        self,
        process_id: str,
        documents: Sequence[tuple[str | Path, DocumentType]],
    ) -> ProcurementProcess:
        """Processa um processo licitatório completo a partir dos arquivos físicos dos seus documentos."""
        if not documents:
            raise ValueError(f"Processo {process_id} sem documentos informados")

        extracted_docs: dict[DocumentType, tuple[StructuredDocument, Document]] = {}
        for file_path, doc_type_in in documents:
            doc_type = (
                doc_type_in
                if isinstance(doc_type_in, DocumentType)
                else DocumentType(str(doc_type_in).upper())
            )
            doc_id = f"{process_id}:{doc_type.value.lower()}"
            path = Path(file_path)
            doc_ext = extract_document(path, document_id=doc_id)
            base_doc = esboco_documento(
                path,
                document_id=doc_id,
                document_type=doc_type,
            )
            extracted_docs[doc_type] = (doc_ext, base_doc)

        # 1. Determina onde extrair itens principais:
        # Prioridade para o TR se houver itens estruturados nele; caso contrário, busca no ETP.
        tr_items: list[Item] = []
        etp_items: list[Item] = []

        if DocumentType.TR in extracted_docs:
            tr_ext, _ = extracted_docs[DocumentType.TR]
            tr_id = f"{process_id}:tr"
            tr_items = extract_items_from_tables(tr_ext, document_id=tr_id)
            if not tr_items:
                tr_items = extract_prose_items(tr_ext, document_id=tr_id)

        if DocumentType.ETP in extracted_docs:
            etp_ext, _ = extracted_docs[DocumentType.ETP]
            etp_id = f"{process_id}:etp"
            etp_items = extract_items_from_tables(etp_ext, document_id=etp_id)
            if not etp_items:
                etp_items = extract_prose_items(etp_ext, document_id=etp_id)

        # Se o TR tiver itens, o TR é o documento vinculante da licitação para a lista de itens.
        # Apenas se o TR não contiver itens estruturados, recorre ao ETP.
        final_tr_items: list[Item] = []
        final_etp_items: list[Item] = []

        if tr_items:
            final_tr_items = tr_items
            final_etp_items = []
        elif etp_items:
            final_etp_items = etp_items
            final_tr_items = []

        processed_docs: list[Document] = []
        for file_path, doc_type_in in documents:
            doc_type = (
                doc_type_in
                if isinstance(doc_type_in, DocumentType)
                else DocumentType(str(doc_type_in).upper())
            )
            doc_ext, base_doc = extracted_docs[doc_type]
            doc_id = f"{process_id}:{doc_type.value.lower()}"

            # Atribui itens conforme decisão de partição
            if doc_type == DocumentType.TR:
                items_to_assign = final_tr_items
            elif doc_type == DocumentType.ETP:
                items_to_assign = final_etp_items
            else:
                items_to_assign = []

            # Extrai campos de nível de documento (prazos, orçamento)
            doc_fields = extract_document_fields(doc_ext, document_id=doc_id)

            processed_doc = Document(
                id=doc_id,
                type=doc_type,
                format=base_doc.format,
                title=base_doc.title,
                sections=base_doc.sections,
                items=items_to_assign,
                field_values=doc_fields,
                requirements=[],
            )
            processed_docs.append(processed_doc)

        proc = ProcurementProcess(
            id=process_id,
            documents=processed_docs,
            findings=[],
        )
        return proc


def extract_procurement_process(
    process_id: str,
    documents: Sequence[tuple[str | Path, DocumentType]],
) -> ProcurementProcess:
    """Função de conveniência para extrair um ProcurementProcess completo."""
    engine = RequirementsEngine()
    return engine.process_procurement(process_id, documents)
