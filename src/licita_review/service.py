"""Serviço de negócio de Revisão Humana (Fase R6).

Implementa:
- Importação e persistência de processos;
- Validação estrita da regra FR-013 (evidência obrigatória para confirmação);
- Registro imutável de audit trail (quem, quando, anterior, posterior);
- Preservação dos valores originais em rejeição;
- Filtro de saída para downstream (somente dados CONFIRMED).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from licita_core.schema import (
    Document,
    DocumentType,
    Evidence,
    FieldValue,
    Item,
    ProcurementProcess,
    Requirement,
    ReviewStatus,
)
from licita_review.models import (
    ProcessSummary,
    ReviewActionRequest,
    ReviewActionType,
    ReviewAuditEntry,
    ReviewTargetType,
)


def _pagina_do_bloco(block_id: str, padrao: int) -> int:
    """Lê a página da convenção ``<doc>:p-0001:b-0002`` do id do bloco."""
    achado = re.search(r":p-(\d+):", block_id)
    return int(achado.group(1)) if achado else padrao


def _reancorar(document: Document, quote: str) -> Evidence:
    """Localiza no documento dono do fato o bloco que contém o trecho.

    O trecho tem de ser substring literal de um bloco ingerido **desse**
    documento: é isso que impede uma confirmação de nascer com evidência
    inventada, ou com evidência emprestada do outro documento do par — um
    valor do TR sustentado por texto do ETP faria a R7 comparar o mesmo fato
    consigo mesmo.
    """
    trecho = (quote or "").strip()
    if not trecho:
        raise ValueError(
            "FR-013: editar o valor exige o trecho do documento que sustenta o valor novo"
        )
    for section in document.sections:
        for block in section.blocks:
            if trecho in block.text:
                return Evidence(
                    document_id=document.id,
                    page=_pagina_do_bloco(block.id, section.evidence.page),
                    block_id=block.id,
                    quote=trecho,
                )
    raise ValueError(
        f"Trecho não encontrado em nenhum bloco do documento '{document.id}': "
        f"a evidência precisa ser texto literal do próprio documento do fato"
    )


class ReviewService:
    """Gerenciador de estado de revisão humana e auditoria."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcurementProcess] = {}
        self._audit_trails: dict[str, list[ReviewAuditEntry]] = {}

    def import_process(self, process: ProcurementProcess) -> None:
        """Importa ou atualiza um processo na área de trabalho de revisão."""
        self._processes[process.id] = process
        if process.id not in self._audit_trails:
            self._audit_trails[process.id] = []

    def get_process(self, process_id: str) -> ProcurementProcess:
        """Obtém o processo pelo ID."""
        if process_id not in self._processes:
            raise KeyError(f"Processo '{process_id}' não encontrado")
        return self._processes[process_id]

    def list_processes(self) -> list[ProcessSummary]:
        """Lista os resumos de todos os processos carregados."""
        summaries = []
        for pid, proc in self._processes.items():
            doc_count = len(proc.documents)
            items_count = sum(len(d.items) for d in proc.documents)

            ext_count = 0
            conf_count = 0
            rej_count = 0

            for doc in proc.documents:
                for fv in doc.field_values:
                    if fv.review_status == ReviewStatus.EXTRACTED:
                        ext_count += 1
                    elif fv.review_status == ReviewStatus.CONFIRMED:
                        conf_count += 1
                    elif fv.review_status == ReviewStatus.REJECTED:
                        rej_count += 1
                for it in doc.items:
                    for fv in it.field_values:
                        if fv.review_status == ReviewStatus.EXTRACTED:
                            ext_count += 1
                        elif fv.review_status == ReviewStatus.CONFIRMED:
                            conf_count += 1
                        elif fv.review_status == ReviewStatus.REJECTED:
                            rej_count += 1
                    for req in it.requirements:
                        if req.review_status == ReviewStatus.EXTRACTED:
                            ext_count += 1
                        elif req.review_status == ReviewStatus.CONFIRMED:
                            conf_count += 1
                        elif req.review_status == ReviewStatus.REJECTED:
                            rej_count += 1

            summaries.append(
                ProcessSummary(
                    id=pid,
                    documents_count=doc_count,
                    items_count=items_count,
                    extracted_fields_count=ext_count,
                    confirmed_fields_count=conf_count,
                    rejected_fields_count=rej_count,
                )
            )
        return summaries

    def _find_field_value(
        self, process: ProcurementProcess, target_id: str
    ) -> tuple[FieldValue, Document, Item | None]:
        # Localiza o documento cujo ID é prefixo de target_id
        doc = next((d for d in process.documents if target_id.startswith(f"{d.id}:")), None)
        if not doc:
            raise KeyError(f"Documento correspondente não encontrado para target_id '{target_id}'")

        remainder = target_id[len(doc.id) + 1 :]
        parts = remainder.split(":")

        if len(parts) == 1:
            # doc_id:field_type
            f_type = parts[0]
            fv = next((f for f in doc.field_values if f.field_type.value == f_type), None)
            if not fv:
                raise KeyError(f"Campo '{f_type}' não encontrado no documento '{doc.id}'")
            return fv, doc, None
        elif len(parts) == 2:
            # doc_id:item_id:field_type
            item_id, f_type = parts
            item = next((i for i in doc.items if i.id == item_id), None)
            if not item:
                raise KeyError(f"Item '{item_id}' não encontrado no documento '{doc.id}'")
            fv = next((f for f in item.field_values if f.field_type.value == f_type), None)
            if not fv:
                raise KeyError(f"Campo '{f_type}' não encontrado no item '{item_id}'")
            return fv, doc, item
        else:
            raise ValueError(f"Formato de target_id inválido: '{target_id}'")

    def _find_requirement(
        self, process: ProcurementProcess, target_id: str
    ) -> tuple[Requirement, Document, Item | None]:
        # Localiza o documento cujo ID é prefixo de target_id
        doc = next((d for d in process.documents if target_id.startswith(f"{d.id}:")), None)
        if not doc:
            raise KeyError(f"Documento correspondente não encontrado para target_id '{target_id}'")

        remainder = target_id[len(doc.id) + 1 :]
        parts = remainder.split(":")

        if len(parts) == 2 and parts[0] == "req":
            # doc_id:req:attribute
            attr = parts[1]
            req = next((r for r in doc.requirements if r.attribute.lower() == attr.lower()), None)
            if not req:
                raise KeyError(f"Requisito '{attr}' não encontrado no documento '{doc.id}'")
            return req, doc, None
        elif len(parts) == 3 and parts[1] == "req":
            # doc_id:item_id:req:attribute
            item_id, _, attr = parts
            item = next((i for i in doc.items if i.id == item_id), None)
            if not item:
                raise KeyError(f"Item '{item_id}' não encontrado no documento '{doc.id}'")
            req = next((r for r in item.requirements if r.attribute.lower() == attr.lower()), None)
            if not req:
                raise KeyError(f"Requisito '{attr}' não encontrado no item '{item_id}'")
            return req, doc, item
        else:
            raise ValueError(f"Formato de target_id inválido para requisito: '{target_id}'")

    def review_field_value(
        self,
        process_id: str,
        target_id: str,
        request: ReviewActionRequest,
    ) -> ReviewAuditEntry:
        """Aplica ação de revisão em um FieldValue."""
        proc = self.get_process(process_id)
        fv, doc, item = self._find_field_value(proc, target_id)

        # Regra FR-013: confirmação exige evidência
        if request.action in (ReviewActionType.CONFIRM, ReviewActionType.EDIT_AND_CONFIRM):
            if not fv.evidence or any(not ev.quote or ev.page < 1 for ev in fv.evidence):
                raise ValueError("FR-013: Não é permitido confirmar dado sem evidência vinculada")

        prev_val = fv.value
        prev_status = fv.review_status
        prev_evidence = list(fv.evidence)
        nova_evidencia: list[Evidence] | None = None

        if request.action == ReviewActionType.CONFIRM:
            fv.review_status = ReviewStatus.CONFIRMED
            new_val = fv.value
        elif request.action == ReviewActionType.EDIT_AND_CONFIRM:
            # A evidência anterior sustenta o valor anterior: editar exige
            # reancorar, senão o CONFIRMED nasce apontando para outro fato.
            nova_evidencia = [_reancorar(doc, request.new_evidence_quote or "")]
            if request.new_value is not None:
                fv.value = request.new_value
            if request.new_unit is not None:
                fv.unit = request.new_unit
            fv.evidence = nova_evidencia
            fv.review_status = ReviewStatus.CONFIRMED
            new_val = fv.value
        elif request.action == ReviewActionType.REJECT:
            fv.review_status = ReviewStatus.REJECTED
            new_val = fv.value
        else:
            raise ValueError(f"Ação não suportada: {request.action}")

        entry = ReviewAuditEntry(
            process_id=process_id,
            target_id=target_id,
            target_type=ReviewTargetType.FIELD_VALUE,
            action=request.action,
            user_id=request.user_id,
            previous_value=prev_val,
            new_value=new_val,
            previous_status=prev_status,
            new_status=fv.review_status,
            previous_evidence=prev_evidence,
            new_evidence=nova_evidencia,
            notes=request.notes,
        )
        self._audit_trails[process_id].append(entry)
        return entry

    def review_requirement(
        self,
        process_id: str,
        target_id: str,
        request: ReviewActionRequest,
    ) -> ReviewAuditEntry:
        """Aplica ação de revisão em um Requirement."""
        proc = self.get_process(process_id)
        req, doc, item = self._find_requirement(proc, target_id)

        # Regra FR-013: confirmação exige evidência
        if request.action in (ReviewActionType.CONFIRM, ReviewActionType.EDIT_AND_CONFIRM):
            if not req.evidence or any(not ev.quote or ev.page < 1 for ev in req.evidence):
                raise ValueError("FR-013: Não é permitido confirmar dado sem evidência vinculada")

        prev_val = req.value
        prev_status = req.review_status
        prev_evidence = list(req.evidence)
        nova_evidencia: list[Evidence] | None = None

        if request.action == ReviewActionType.CONFIRM:
            req.review_status = ReviewStatus.CONFIRMED
            new_val = req.value
        elif request.action == ReviewActionType.EDIT_AND_CONFIRM:
            nova_evidencia = [_reancorar(doc, request.new_evidence_quote or "")]
            if request.new_value is not None:
                req.value = request.new_value
            if request.new_unit is not None:
                req.unit = request.new_unit
            req.evidence = nova_evidencia
            req.review_status = ReviewStatus.CONFIRMED
            new_val = req.value
        elif request.action == ReviewActionType.REJECT:
            req.review_status = ReviewStatus.REJECTED
            new_val = req.value
        else:
            raise ValueError(f"Ação não suportada: {request.action}")

        entry = ReviewAuditEntry(
            process_id=process_id,
            target_id=target_id,
            target_type=ReviewTargetType.REQUIREMENT,
            action=request.action,
            user_id=request.user_id,
            previous_value=prev_val,
            new_value=new_val,
            previous_status=prev_status,
            new_status=req.review_status,
            previous_evidence=prev_evidence,
            new_evidence=nova_evidencia,
            notes=request.notes,
        )
        self._audit_trails[process_id].append(entry)
        return entry

    def get_audit_trail(self, process_id: str) -> list[ReviewAuditEntry]:
        """Retorna o histórico de auditoria do processo."""
        if process_id not in self._audit_trails:
            raise KeyError(f"Processo '{process_id}' não encontrado")
        return list(self._audit_trails[process_id])

    def get_confirmed_process(self, process_id: str) -> ProcurementProcess:
        """Exporta uma versão filtrada contendo apenas fatos CONFIRMED (para R7/R8/R9 downstream)."""
        proc = self.get_process(process_id)
        confirmed_docs: list[Document] = []

        for doc in proc.documents:
            c_field_values = [f for f in doc.field_values if f.review_status == ReviewStatus.CONFIRMED]
            c_requirements = [r for r in doc.requirements if r.review_status == ReviewStatus.CONFIRMED]
            c_items: list[Item] = []

            for it in doc.items:
                it_fvs = [f for f in it.field_values if f.review_status == ReviewStatus.CONFIRMED]
                it_reqs = [r for r in it.requirements if r.review_status == ReviewStatus.CONFIRMED]
                # Preserva o item se ele possui dados confirmados ou se o item em si é relevante
                if it_fvs or it_reqs or it.evidence:
                    c_items.append(
                        Item(
                            id=it.id,
                            description=it.description,
                            field_values=it_fvs,
                            requirements=it_reqs,
                            evidence=it.evidence,
                        )
                    )

            confirmed_docs.append(
                Document(
                    id=doc.id,
                    type=doc.type,
                    format=doc.format,
                    title=doc.title,
                    sections=doc.sections,
                    items=c_items,
                    field_values=c_field_values,
                    requirements=c_requirements,
                )
            )

        return ProcurementProcess(
            id=proc.id,
            documents=confirmed_docs,
            findings=proc.findings,
        )
