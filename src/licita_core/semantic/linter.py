"""Linter Semântico de Termos Vagos, Marcas e Restrições (Fase R9)."""

from __future__ import annotations

import re
from uuid import uuid4

from licita_core.schema import (
    Document,
    Evidence,
    Finding,
    FindingCategory,
    FindingStatus,
    Item,
    ProcurementProcess,
    Severity,
)

# Catálogo de termos vagos proibidos pelo art. 40, § 1º, I da Lei 14.133/2021
_VAGUE_PATTERNS = [
    (r"\b(?:de\s+)?primeira\s+linha\b", "primeira linha"),
    (r"\b(?:de\s+)?primeira\s+qualidade\b", "primeira qualidade"),
    (r"\b(?:de\s+)?alta\s+qualidade\b", "alta qualidade"),
    (r"\b(?:de\s+)?[óo]tima\s+qualidade\b", "ótima qualidade"),
    (r"\bmarca\s+de\s+renome\b", "marca de renome"),
    (r"\brenomad[ao]\s+no\s+mercado\b", "renomada no mercado"),
    (r"\bmarcas?\s+consagrada[s]?\b", "marca consagrada"),
    (r"\bexcelente\s+(?:acabamento|desempenho|durabilidade)\b", "excelente acabamento/durabilidade"),
    (r"\balto\s+padr[ãa]o\b", "alto padrão"),
    (r"\bm[áa]ximo\s+rendimento\b", "máximo rendimento"),
    (r"\bboa\s+qualidade\b", "boa qualidade"),
]

# Amostra de marcas conhecidas para verificação de direcionamento
_KNOWN_BRANDS = [
    "chevrolet", "fiat", "volkswagen", "toyota", "ford", "jeep", "renault", "honda", "hyundai", "chery",
    "dell", "lenovo", "hp", "epson", "samsung", "lg", "apple", "asus",
    "tramontina", "tigre", "amanco", "suvinil", "coral", "votoran", "cauê", "gerdau",
    "stihl", "husqvarna", "bosch", "makita", "dewalt", "3m",
]


class SemanticLinter:
    """Linter semântico para identificação de vícios de redação e restrições indevidas no TR."""

    def run(self, process: ProcurementProcess) -> list[Finding]:
        findings: list[Finding] = []

        for doc in process.documents:
            # 1. Analisa itens
            for item in doc.items:
                findings.extend(self._lint_item(item, doc))

            # 2. Analisa seções e blocos do documento
            for sec in doc.sections:
                for block in sec.blocks:
                    findings.extend(self._lint_block(block.text, doc.id, block.id, sec.evidence))

        return findings

    def _lint_item(self, item: Item, doc: Document) -> list[Finding]:
        findings: list[Finding] = []
        text = item.description or ""
        if not text:
            return findings

        ev_base = item.evidence[0] if item.evidence else None

        # SEM-001: Termos vagos e subjetivos
        for pattern, label in _VAGUE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                quote = match.group(0)
                ev = Evidence(
                    document_id=doc.id,
                    page=ev_base.page if ev_base else 1,
                    block_id=ev_base.block_id if ev_base else f"{doc.id}:p-0001:b-0001",
                    quote=quote,
                )
                findings.append(
                    Finding(
                        id=f"finding-sem-001-{uuid4().hex[:8]}",
                        rule_id="SEM-001",
                        category=FindingCategory.COMPLIANCE,
                        severity=Severity.HIGH,
                        status=FindingStatus.OPEN,
                        title=f"Termo Vago ou Subjetivo no Item ({item.id})",
                        message=(
                            f"Identificada expressão imprecisa/subjetiva '{quote}' na descrição do Item {item.id}. "
                            "A Lei nº 14.133/2021 (art. 40, § 1º, I) veda especificações genéricas ou subjetivas "
                            "que não permitam aferição objetiva de conformidade técnica."
                        ),
                        item_id=item.id,
                        evidence=[ev],
                        attrs={"legal_basis": "Lei nº 14.133/2021, art. 40, § 1º, I"},
                    )
                )

        # SEM-002: Indicação de Marca sem "ou equivalente"
        for brand in _KNOWN_BRANDS:
            brand_pattern = rf"\b{re.escape(brand)}\b"
            match = re.search(brand_pattern, text, re.IGNORECASE)
            if match:
                # Verifica se há cláusula permissiva de similaridade no texto
                has_equivalent = bool(
                    re.search(
                        r"(?:ou\s+(?:similar|equivalente|de\s+melhor\s+qualidade)|refer[êe]ncia|similar|equivalente)",
                        text,
                        re.IGNORECASE,
                    )
                )
                if not has_equivalent:
                    quote = match.group(0)
                    ev = Evidence(
                        document_id=doc.id,
                        page=ev_base.page if ev_base else 1,
                        block_id=ev_base.block_id if ev_base else f"{doc.id}:p-0001:b-0001",
                        quote=quote,
                    )
                    findings.append(
                        Finding(
                            id=f"finding-sem-002-{uuid4().hex[:8]}",
                            rule_id="SEM-002",
                            category=FindingCategory.COMPLIANCE,
                            severity=Severity.HIGH,
                            status=FindingStatus.OPEN,
                            title=f"Indicação de Marca sem 'ou similar/equivalente' no Item ({item.id})",
                            message=(
                                f"Identificada indicação de marca comercial '{quote}' sem a ressalva legal obrigatória "
                                "('ou equivalente', 'ou similar' ou 'ou de melhor qualidade'). "
                                "A Lei nº 14.133/2021 (art. 41, I) veda a exigência de marca exclusiva sem processo "
                                "formal de padronização prévia."
                            ),
                            item_id=item.id,
                            evidence=[ev],
                            attrs={"legal_basis": "Lei nº 14.133/2021, art. 41, I"},
                        )
                    )

        return findings

    def _lint_block(
        self, text: str, doc_id: str, block_id: str, sec_evidence: Evidence | None
    ) -> list[Finding]:
        findings: list[Finding] = []
        if not text:
            return findings

        # SEM-001 em blocos de texto
        for pattern, label in _VAGUE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                quote = match.group(0)
                ev = Evidence(
                    document_id=doc_id,
                    page=sec_evidence.page if sec_evidence else 1,
                    block_id=block_id,
                    quote=quote,
                )
                findings.append(
                    Finding(
                        id=f"finding-sem-001-{uuid4().hex[:8]}",
                        rule_id="SEM-001",
                        category=FindingCategory.COMPLIANCE,
                        severity=Severity.HIGH,
                        status=FindingStatus.OPEN,
                        title="Termo Vago ou Subjetivo no Documento",
                        message=(
                            f"Identificada expressão imprecisa/subjetiva '{quote}'. "
                            "A Lei nº 14.133/2021 (art. 40, § 1º, I) veda exigências que impeçam a aferição objetiva."
                        ),
                        evidence=[ev],
                        attrs={"legal_basis": "Lei nº 14.133/2021, art. 40, § 1º, I"},
                    )
                )

        return findings
