"""Download e organização física dos documentos do corpus.

Layout em disco — um diretório por processo, nome de arquivo autoexplicativo:

    corpus/documentos/<processo_id>/<papel>-<sequencial>-<titulo>.<ext>

O nome do arquivo carrega papel e sequencial porque o gate do R1 é "abrir os
processos localmente": quem abrir a pasta precisa ver a cadeia sem consultar o
catálogo. A extensão vem do conteúdo (assinatura binária), não do
``content-type`` do PNCP, que devolve ``application/octet-stream`` para tudo.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classify import papel_documento_contrato
from .pncp import Pncp, PncpNotFound

#: Assinaturas binárias → extensão. Ordem irrelevante: os prefixos não colidem.
_ASSINATURAS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc"),  # OLE2: .doc/.xls legados
    (b"{\\rtf", "rtf"),
)

#: Extensões que a v1 ingere (scope.md, nível documental).
EXTENSOES_SUPORTADAS = frozenset({"pdf", "docx"})


def identificar_extensao(conteudo: bytes, nome_original: str | None) -> str:
    """Extensão real do arquivo, a partir do conteúdo."""
    for assinatura, extensao in _ASSINATURAS:
        if conteudo.startswith(assinatura):
            return extensao
    if conteudo.startswith(b"PK\x03\x04"):
        # Todo OOXML é um zip; só é DOCX se trouxer o corpo do Word dentro.
        return "docx" if b"word/document.xml" in conteudo[:8192] or _zip_tem_word(conteudo) else "zip"
    if nome_original and "." in nome_original:
        return nome_original.rsplit(".", 1)[1].lower()[:8]
    return "bin"


def _zip_tem_word(conteudo: bytes) -> bool:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            return "word/document.xml" in arquivo.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def slug(texto: str, limite: int = 60) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    limpo = re.sub(r"[^A-Za-z0-9]+", "-", sem_acento).strip("-").lower()
    return (limpo[:limite].rstrip("-")) or "sem-titulo"


def processo_id(numero_controle_pncp: str) -> str:
    """``<cnpj>-1-000070/2025`` → ``<cnpj>-1-000070-2025`` (seguro em disco)."""
    return numero_controle_pncp.replace("/", "-")


@dataclass(slots=True)
class Baixado:
    caminho: Path
    sha256: str
    bytes: int
    extensao: str
    content_type: str | None
    nome_original: str | None
    ja_existia: bool


def baixar_documento(
    pncp: Pncp,
    url: str,
    destino_dir: Path,
    papel: str,
    sequencial: int | None,
    titulo: str,
    reaproveitar: bool = True,
) -> Baixado | None:
    """Baixa um documento. ``None`` quando o PNCP não entrega o arquivo.

    Com ``reaproveitar``, um arquivo já presente em disco com o mesmo nome-base
    é reusado sem nova requisição. O nome-base é determinado por papel,
    sequencial e título — todos conhecidos antes do download — então repetir a
    coleta não rebaixa centenas de megabytes só para reescrever o catálogo.
    """
    base = f"{papel.lower()}-{sequencial or 0:02d}-{slug(titulo)}"
    if reaproveitar:
        existentes = sorted(destino_dir.glob(f"{base}.*"))
        if len(existentes) == 1:
            return _do_disco(existentes[0])

    try:
        conteudo, content_type, nome_original = pncp.baixar(url)
    except PncpNotFound:
        return None
    if not conteudo:
        return None

    extensao = identificar_extensao(conteudo, nome_original)
    destino_dir.mkdir(parents=True, exist_ok=True)
    caminho = destino_dir / f"{base}.{extensao}"
    digesto = hashlib.sha256(conteudo).hexdigest()

    ja_existia = caminho.exists() and hashlib.sha256(caminho.read_bytes()).hexdigest() == digesto
    if not ja_existia:
        caminho.write_bytes(conteudo)

    return Baixado(
        caminho=caminho,
        sha256=digesto,
        bytes=len(conteudo),
        extensao=extensao,
        content_type=content_type,
        nome_original=nome_original,
        ja_existia=ja_existia,
    )


def _do_disco(caminho: Path) -> Baixado:
    conteudo = caminho.read_bytes()
    return Baixado(
        caminho=caminho,
        sha256=hashlib.sha256(conteudo).hexdigest(),
        bytes=len(conteudo),
        extensao=caminho.suffix.lstrip("."),
        content_type=None,
        nome_original=None,
        ja_existia=True,
    )


def baixar_contrato_documentos(
    pncp: Pncp, contrato: dict[str, Any], destino_dir: Path, apenas_contrato: bool = True
) -> list[tuple[dict[str, Any], Baixado]]:
    # O sequencial do documento reinicia em cada contrato, então o sequencial do
    # próprio contrato entra no nome do arquivo para evitar colisão quando uma
    # contratação gera mais de um contrato.
    """Baixa os arquivos publicados do contrato.

    Por padrão só o instrumento contratual em si: notas de empenho, termos
    aditivos e apostilamentos ficam de fora porque não são o elo ``contrato`` da
    cadeia que a v1 compara com o TR.
    """
    brutos = pncp.arquivos_contrato(
        contrato["cnpj_orgao"], contrato["ano_contrato"], contrato["sequencial_contrato"]
    )
    saida: list[tuple[dict[str, Any], Baixado]] = []
    for bruto in brutos:
        if not bruto.get("statusAtivo", True):
            continue
        url = bruto.get("url") or bruto.get("uri")
        if not url:
            continue
        papel = papel_documento_contrato(bruto.get("tipoDocumentoNome"), bruto.get("titulo", ""))
        if apenas_contrato and papel != "CONTRATO":
            continue
        baixado = baixar_documento(
            pncp,
            url,
            destino_dir,
            papel,
            bruto.get("sequencialDocumento"),
            f"c{contrato['sequencial_contrato']}-{bruto.get('titulo', '')}",
        )
        if baixado:
            saida.append(({**bruto, "papel": papel}, baixado))
    return saida
