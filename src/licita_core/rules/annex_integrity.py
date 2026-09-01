"""RULE-006 — Referência a anexo ou apêndice do TR não resolvida no pacote documental.

Controle de integridade documental (ADVISORY / INTEGRITY).
"""

from __future__ import annotations

import re

from licita_core.rules.base import Rule, RuleContext
from licita_core.rules.common import (
    extract_first_evidence,
    int_to_roman,
    is_placeholder,
    normalize_anchor,
    normalize_text,
    roman_to_int,
)
from licita_core.schema import (
    Document,
    DocumentType,
    Evidence,
    Finding,
    FindingCategory,
    Severity,
)


class AnnexIntegrityRule(Rule):
    rule_id = "RULE-006"
    version = "1.0.0"
    rule_class = "ADVISORY"
    category = FindingCategory.CONSISTENCY
    description = (
        "Referência a anexo ou apêndice do TR não resolvida no pacote "
        "documental disponível."
    )
    scope = (
        "Referências que afirmam integrar o TR. O arquivo referido pode estar "
        "incorporado ao TR ou separado no mesmo pacote. Não resolve anexos de "
        "edital, ETP, contrato ou ata declarados como outros instrumentos."
    )
    legal_basis = (
        "não se aplica — controle de integridade documental, sem conclusão de "
        "compliance normativo."
    )
    severity = Severity.MEDIUM

    def applies(self, context: RuleContext) -> bool:
        doc = context.target_document
        return (
            doc is not None
            and doc.type == DocumentType.TR
            and context.profile_id == "PUBLICO_14133_PREGAO_ELETRONICO_BENS"
        )

    def detect(self, context: RuleContext) -> list[Finding]:
        if not self.applies(context):
            return []
        doc = context.target_document
        assert doc is not None

        # Coleta âncoras presentes no próprio TR
        embedded_anchors = self._collect_embedded_anchors(doc)

        # Coleta âncoras presentes no pacote
        package_anchors = self._collect_package_anchors(context)

        # Busca menções a anexos no texto do TR
        mentions = self._find_annex_references(doc)

        findings: list[Finding] = []
        seen_unresolved: set[str] = set()

        for anchor_raw, ev in mentions:
            variants = self._anchor_variants(anchor_raw)
            resolved = any(
                v in embedded_anchors or v in package_anchors for v in variants
            )
            if not resolved and anchor_raw not in seen_unresolved:
                seen_unresolved.add(anchor_raw)
                findings.append(
                    Finding(
                        id=f"FIND-RULE-006-{anchor_raw}",
                        rule_id=self.rule_id,
                        title="Anexo não resolvido no pacote",
                        message=(
                            f"Referência ao Anexo {anchor_raw} não resolvida no "
                            "pacote documental disponível."
                        ),
                        category=self.category,
                        confidence=1.0,
                        severity=self.severity,
                        attrs={
                            "anchor": anchor_raw,
                            "rule_class": "ADVISORY",
                            "category": "INTEGRITY",
                            "profile_id": context.profile_id,
                        },
                        evidence=[ev],
                    )
                )

        return findings

    @staticmethod
    def _anchor_variants(anchor: str) -> set[str]:
        clean = anchor.strip().upper()
        variants = {clean, clean.lower()}
        num = roman_to_int(clean)
        if num is not None:
            variants.add(str(num))
            roman = int_to_roman(num)
            if roman:
                variants.add(roman)
                variants.add(roman.lower())
        elif clean.isdigit():
            variants.add(clean)
            roman = int_to_roman(int(clean))
            if roman:
                variants.add(roman)
                variants.add(roman.lower())
        return variants

    @classmethod
    def _collect_embedded_anchors(cls, doc: Document) -> set[str]:
        anchors: set[str] = set()
        heading_pat = re.compile(
            r"^(?:#+\s*)?(?:ANEXO|AP[EÊ]NDICE)\s+([IVXLCDM]+|\d+|[A-Z])\b",
            re.IGNORECASE,
        )
        for section in doc.sections:
            match = heading_pat.search(section.title_original.strip())
            if match:
                anchors.update(cls._anchor_variants(match.group(1)))
            for block in section.blocks:
                text_strip = block.text.strip()
                if block.type.value == "HEADER" or text_strip.startswith("#"):
                    m = heading_pat.search(text_strip)
                    if m:
                        anchors.update(cls._anchor_variants(m.group(1)))
                elif re.match(r"^(?:ANEXO|AP[EÊ]NDICE)\s+([IVXLCDM]+|\d+|[A-Z])(?:\s*[-–—:]|$)", text_strip, re.IGNORECASE):
                    m = heading_pat.search(text_strip)
                    if m:
                        anchors.update(cls._anchor_variants(m.group(1)))
        return anchors

    @classmethod
    def _collect_package_anchors(cls, context: RuleContext) -> set[str]:
        anchors: set[str] = set()
        # 1. De package_files (nomes de arquivos)
        pat = re.compile(r"anexo[-_]?([ivxlcdm]+|\d+|[a-z])", re.IGNORECASE)
        for fname in context.package_files:
            match = pat.search(fname)
            if match:
                anchors.update(cls._anchor_variants(match.group(1)))

        # 2. De package_anchors explícito
        for file_anchors in context.package_anchors.values():
            for a in file_anchors:
                match = re.search(r"(?:ANEXO|AP[EÊ]NDICE)\s+([IVXLCDM]+|\d+|[A-Z])\b", a, re.IGNORECASE)
                if match:
                    anchors.update(cls._anchor_variants(match.group(1)))
                else:
                    anchors.update(cls._anchor_variants(a))

        # 3. De outros documentos no processo
        for other_doc in context.process.documents:
            if other_doc.id != context.target_document_id:
                for match in pat.finditer(other_doc.id):
                    anchors.update(cls._anchor_variants(match.group(1)))
                if other_doc.title:
                    for match in pat.finditer(other_doc.title):
                        anchors.update(cls._anchor_variants(match.group(1)))

        return anchors

    @classmethod
    def _find_annex_references(cls, doc: Document) -> list[tuple[str, Evidence]]:
        references: list[tuple[str, Evidence]] = []
        pat = re.compile(
            r"\b(?:Anexo|Ap[eê]ndice)\s+([IVXLCDM]+|\d+|[A-Z])\b",
            re.IGNORECASE,
        )

        for section in doc.sections:
            for block in section.blocks:
                if is_placeholder(block.text):
                    continue
                # Se for um título de anexo em si, não é referência
                if block.text.strip().startswith("#") and "ANEXO" in block.text.upper():
                    continue

                for match in pat.finditer(block.text):
                    anchor_raw = match.group(1).upper()
                    start_idx = match.start()
                    snippet = block.text[max(0, start_idx - 30):min(len(block.text), start_idx + 80)]
                    snippet_norm = normalize_text(snippet)

                    # Ignora se expressamente declarado como outro instrumento
                    if any(
                        kw in snippet_norm
                        for kw in ["do etp", "do edital", "nao integra este tr", "anexos, se houver", "se houver"]
                    ):
                        continue

                    ev = Evidence(
                        document_id=doc.id,
                        page=section.evidence.page if section.evidence else 1,
                        block_id=block.id,
                        quote=block.text,
                    )
                    references.append((anchor_raw, ev))

        return references
