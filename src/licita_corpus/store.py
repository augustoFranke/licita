"""Download e organização física dos documentos do corpus.

Layout em disco — um diretório por processo, nome de arquivo autoexplicativo:

    corpus/documentos/<processo_id>/<papel>-<sequencial>-<titulo>.<ext>

O nome do arquivo carrega papel e sequencial porque o gate do R1 é "abrir os
processos localmente": quem abrir a pasta precisa ver a cadeia sem consultar o
catálogo. A extensão vem do conteúdo (assinatura binária), não do
``content-type`` do PNCP, que devolve ``application/octet-stream`` para tudo.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import tempfile
import threading
import unicodedata
import xml.etree.ElementTree as ET
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # ``fcntl`` só existe nos sistemas Unix.
    import fcntl
except ImportError:  # pragma: no cover - exercitado em plataformas sem Unix
    fcntl = None  # type: ignore[assignment]

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
    """Identifica o formato e mantém fallback seguro para o nome original.

    O fallback existe por compatibilidade com consumidores desta função. O
    download nunca o usa para decidir se um arquivo pertence ao escopo.
    """
    extensao_real = _identificar_extensao_real(conteudo)
    if extensao_real is not None:
        return extensao_real

    for assinatura, extensao in _ASSINATURAS:
        if conteudo.startswith(assinatura):
            return extensao
    if conteudo.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x06\x06")):
        return "zip"
    return _extensao_do_nome(nome_original)


def _extensao_do_nome(nome_original: str | None) -> str:
    if not isinstance(nome_original, str) or "." not in nome_original:
        return "bin"
    candidato = nome_original.rsplit(".", 1)[1].lower()
    candidato = re.sub(r"[^a-z0-9]", "", candidato)
    return candidato[:8] or "bin"


def _identificar_extensao_real(conteudo: bytes) -> str | None:
    if conteudo.startswith(b"%PDF"):
        return "pdf"
    if _zip_tem_word(conteudo):
        return "docx"
    return None


def _xml_bem_formado(conteudo: bytes) -> bool:
    """Valida a sintaxe XML sem exigir namespaces declarados.

    Alguns arquivos publicados pelo PNCP usam ``w:document`` sem declarar o
    prefixo. Isso ainda é XML sintaticamente bem formado (embora não seja
    *namespace-well-formed*), e os consumidores históricos deste módulo aceitam
    esse documento mínimo. O primeiro parser mantém a validação normal; o
    fallback sem processamento de namespaces conserva essa compatibilidade e
    continua rejeitando XML truncado ou com lixo.
    """
    from xml.parsers import expat

    try:
        ET.fromstring(conteudo)
    except ET.ParseError as erro:
        if "unbound prefix" not in str(erro).lower():
            return False
        try:
            parser = expat.ParserCreate()
            parser.Parse(conteudo, True)
        except expat.ExpatError:
            return False
    return True


def _zip_tem_word(conteudo: bytes) -> bool:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            informacao = arquivo.getinfo("word/document.xml")
            if informacao.is_dir():
                return False
            documento = arquivo.read(informacao)
            if not documento.strip() or not _xml_bem_formado(documento):
                return False
            # Valida também CRC/deflate de outros membros: um diretório
            # central legível não basta para chamar o ZIP de válido.
            return arquivo.testzip() is None
    except (
        EOFError,
        KeyError,
        NotImplementedError,
        OSError,
        OverflowError,
        RuntimeError,
        UnicodeError,
        ValueError,
        ET.ParseError,
        zlib.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ):
        # ``read`` pode revelar corrupção de deflate/CRC somente depois que o
        # diretório central foi aceito. Nenhum desses erros deve escapar como
        # se o arquivo fosse um DOCX.
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


_LOCKS_LOCAIS_GUARD = threading.Lock()
_LOCKS_LOCAIS: dict[str, threading.Lock] = {}


class _LockIndisponivel(RuntimeError):
    """Sinaliza que uma tentativa não bloqueante encontrou um lock ocupado."""


def _destino_canonico(destino_dir: Path) -> Path:
    """Resolve aliases do destino antes de criar locks ou arquivos.

    ``resolve(strict=False)`` também funciona quando o último diretório ainda
    não existe. O fallback mantém o comportamento em plataformas/FSs que não
    conseguem resolver a cadeia inteira, mas não finge oferecer canonicalização
    nesses casos.
    """
    caminho = Path(destino_dir).expanduser()
    try:
        return caminho.resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(os.path.abspath(os.fspath(caminho)))


def _chave_diretorio(destino_dir: Path) -> str:
    return os.fspath(_destino_canonico(destino_dir))


def _componente_seguro(valor: object) -> str:
    """Converte entrada externa em um único componente sem glob/traversal."""
    if not isinstance(valor, str):
        valor = "" if valor is None else str(valor)
    return slug(valor)


def _base_documento(papel: object, sequencial: int | None, titulo: str) -> str:
    # O papel vem de dados do PNCP em alguns caminhos e não pode ser usado
    # diretamente em ``Path``/``glob``.
    componente_papel = _componente_seguro(papel)
    numero = 0 if not sequencial else int(sequencial)
    return f"{componente_papel}-{numero:02d}-{slug(titulo)}"


def _chave_documento(destino_dir: Path, base: str) -> str:
    return f"{_chave_diretorio(destino_dir)}\0{base}"


def _lock_path(destino_dir: Path, base: str) -> Path:
    """Sidecar de nome fixo e não interpretável como componente externo."""
    destino_dir = _destino_canonico(destino_dir)
    identidade = f"{os.fspath(destino_dir)}\0{base}".encode(
        "utf-8", "surrogatepass"
    )
    token = hashlib.sha256(identidade).hexdigest()
    return destino_dir / f".licita-{token}.lock"


def _flock_indisponivel(erro: OSError) -> bool:
    return erro.errno in {
        getattr(errno, "ENOSYS", -1),
        getattr(errno, "ENOTSUP", -1),
        getattr(errno, "EOPNOTSUPP", -1),
        getattr(errno, "ENOTTY", -1),
    }


def _lock_ocupado(erro: OSError) -> bool:
    return erro.errno in {
        getattr(errno, "EACCES", -1),
        getattr(errno, "EAGAIN", -1),
    }


@contextmanager
def _lock_documento(
    destino_dir: Path, base: str, *, bloqueante: bool = True
):
    """Lock por documento: local para threads e advisory cross-process no Unix.

    Em Unix com ``fcntl.flock`` o sidecar é compartilhado por processos que
    chegam ao mesmo diretório canônico e nome-base. Se ``fcntl`` não existir,
    ou o filesystem não suportar ``flock``, o fallback explícito é apenas o
    lock de threads desta aplicação; nesse ambiente não há garantia
    cross-process possível por esta implementação.
    """
    destino_dir = _destino_canonico(destino_dir)
    chave = _chave_documento(destino_dir, base)
    with _LOCKS_LOCAIS_GUARD:
        lock_local = _LOCKS_LOCAIS.setdefault(chave, threading.Lock())

    if not lock_local.acquire(blocking=bloqueante):
        raise _LockIndisponivel(chave)

    descritor: int | None = None
    flock_adquirido = False
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        # Não seguir um symlink plantado no lugar do sidecar. O nome já é um
        # hash, mas esta proteção também cobre adulteração local do diretório.
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descritor = os.open(os.fspath(_lock_path(destino_dir, base)), flags, 0o600)

        modulo_fcntl = fcntl
        tem_flock = modulo_fcntl is not None and all(
            hasattr(modulo_fcntl, nome)
            for nome in ("flock", "LOCK_EX", "LOCK_UN", "LOCK_NB")
        )
        if tem_flock:
            modo = modulo_fcntl.LOCK_EX
            if not bloqueante:
                modo |= modulo_fcntl.LOCK_NB
            try:
                modulo_fcntl.flock(descritor, modo)
                flock_adquirido = True
            except NotImplementedError:
                # Fallback local explícito quando a plataforma expõe o módulo
                # mas não implementa flock.
                pass
            except OSError as erro:
                if not bloqueante and _lock_ocupado(erro):
                    raise _LockIndisponivel(chave) from None
                if not _flock_indisponivel(erro):
                    raise
                # Fallback local: ENOTSUP/ENOSYS não é uma disputa normal e
                # não deve impedir o download neste filesystem.

        yield
    finally:
        if descritor is not None:
            if flock_adquirido and fcntl is not None:
                try:
                    fcntl.flock(descritor, fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                os.close(descritor)
            except OSError:
                pass
        lock_local.release()


def _remover_parcial(caminho: Path) -> None:
    try:
        caminho.unlink()
    except (FileNotFoundError, OSError):
        pass


_TOKEN_TEMPORARIO = re.compile(r"[A-Za-z0-9_]+")


def _base_do_temporario(nome: str) -> str | None:
    """Obtém o base de temporários deste módulo e do formato legado.

    O escritor atual produz ``.<base>.<random>.part``. O formato antigo
    ``<base>.<ext>.part`` também é reconhecido para que uma coleta interrompida
    possa ser limpa sob o mesmo lock.
    """
    sufixo = ".part"
    if not nome.endswith(sufixo):
        return None
    corpo = nome[: -len(sufixo)]
    if nome.startswith("."):
        sem_ponto = corpo[1:]
        prefixo, separador, token = sem_ponto.rpartition(".")
        if (
            separador
            and prefixo
            and "." in prefixo
            and _TOKEN_TEMPORARIO.fullmatch(token)
        ):
            nome_final = prefixo
        elif "." in sem_ponto:
            nome_final = sem_ponto
        else:
            return None
    else:
        nome_final = corpo
    if "." not in nome_final:
        return None
    base, _extensao = nome_final.rsplit(".", 1)
    return base or None


def _listar_parciais(destino_dir: Path) -> tuple[Path, ...]:
    try:
        return tuple(destino_dir.glob("*.part"))
    except OSError:
        return ()


def _limpar_temporarios_base(destino_dir: Path, base: str) -> None:
    """Limpa apenas o base do lock já adquirido."""
    for parcial in _listar_parciais(destino_dir):
        if _base_do_temporario(parcial.name) != base:
            continue
        try:
            if parcial.is_file() or parcial.is_symlink():
                parcial.unlink()
        except (FileNotFoundError, OSError):
            pass


def _limpar_temporarios_obsoletos(
    destino_dir: Path, *, ignorar_base: str | None = None
) -> None:
    """Limpa resíduos sem remover um temporário com lock potencialmente ativo.

    Temporários reconhecíveis são removidos somente após uma tentativa
    não-bloqueante do lock do próprio documento; os irreconhecíveis são
    resíduos de formatos anteriores que este escritor nunca mantém abertos e
    podem ser removidos diretamente.
    """
    bases_vistas: set[str] = set()
    for parcial in _listar_parciais(destino_dir):
        base = _base_do_temporario(parcial.name)
        if base is None:
            _remover_parcial(parcial)
            continue
        if base == ignorar_base or base in bases_vistas:
            continue
        bases_vistas.add(base)
        try:
            with _lock_documento(destino_dir, base, bloqueante=False):
                _limpar_temporarios_base(destino_dir, base)
        except (_LockIndisponivel, FileNotFoundError, OSError, RuntimeError):
            # Ocupado, inacessível ou com sidecar adulterado: conservar é a
            # opção segura, e a limpeza não pode mascarar a operação principal.
            pass


def _limpar_residuos_part(destino_dir: Path) -> None:
    """Limpa resíduos abandonados, preservando temporários ativos."""
    _limpar_temporarios_obsoletos(_destino_canonico(destino_dir))


def _limpar_sob_lock(destino_dir: Path, base: str) -> None:
    _limpar_temporarios_base(destino_dir, base)
    _limpar_temporarios_obsoletos(destino_dir, ignorar_base=base)


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
    destino_dir = _destino_canonico(destino_dir)
    base = _base_documento(papel, sequencial, titulo)
    return _baixar_documento(
        pncp,
        url,
        destino_dir,
        papel,
        sequencial,
        titulo,
        reaproveitar,
        base,
    )


def _caminhos_do_base(destino_dir: Path, base: str) -> tuple[Path, ...]:
    try:
        return tuple(
            sorted(
                caminho
                for caminho in destino_dir.glob(f"{base}.*")
                if caminho.is_file() and not caminho.name.lower().endswith(".part")
            )
        )
    except OSError:
        return ()


def _existente_valido(destino_dir: Path, base: str) -> Baixado | None:
    validos: list[Baixado] = []
    for existente in _caminhos_do_base(destino_dir, base):
        try:
            validos.append(_do_disco(existente))
        except (OSError, ValueError, UnicodeError):
            # Arquivo vazio, ilegível, corrompido ou fora do escopo não é uma
            # cópia confiável; o download abaixo poderá repará-lo.
            continue
    return validos[0] if len(validos) == 1 else None


def _estado_base(destino_dir: Path, base: str) -> tuple[tuple[object, ...], ...]:
    """Fingerprint leve para detectar replace concorrente durante o download."""
    estado: list[tuple[object, ...]] = []
    for caminho in _caminhos_do_base(destino_dir, base):
        try:
            informacao = caminho.stat()
        except OSError:
            continue
        estado.append(
            (
                caminho.name,
                informacao.st_ino,
                informacao.st_size,
                informacao.st_mtime_ns,
            )
        )
    return tuple(estado)


def _limpar_apos_falha(destino_dir: Path, base: str) -> None:
    """Tenta limpar sem substituir a exceção original da rede."""
    try:
        with _lock_documento(destino_dir, base):
            _limpar_sob_lock(destino_dir, base)
    except (FileNotFoundError, OSError, RuntimeError):
        pass


def _baixar_documento(
    pncp: Pncp,
    url: str,
    destino_dir: Path,
    papel: str,
    sequencial: int | None,
    titulo: str,
    reaproveitar: bool,
    base: str,
) -> Baixado | None:
    destino_dir = _destino_canonico(destino_dir)
    # A primeira passagem evita uma requisição quando já há uma cópia válida.
    # No modo forçado, guarda-se o estado para distinguir uma cópia que existia
    # antes da chamada de uma cópia instalada por outro processo enquanto a
    # rede era consultada.
    estado_inicial: tuple[tuple[object, ...], ...] | None = None
    with _lock_documento(destino_dir, base):
        _limpar_sob_lock(destino_dir, base)
        if reaproveitar:
            existente = _existente_valido(destino_dir, base)
            if existente is not None:
                return existente
        else:
            estado_inicial = _estado_base(destino_dir, base)

    try:
        conteudo, content_type, nome_original = pncp.baixar(url)
    except PncpNotFound:
        conteudo = None
        content_type = None
        nome_original = None
    except BaseException:
        _limpar_apos_falha(destino_dir, base)
        raise

    # Esta é a revalidação decisiva: ela ocorre depois da rede e no mesmo lock
    # que cobre o replace e a leitura final.
    with _lock_documento(destino_dir, base):
        _limpar_sob_lock(destino_dir, base)
        if reaproveitar:
            existente = _existente_valido(destino_dir, base)
            if existente is not None:
                return existente
        elif estado_inicial is not None and _estado_base(destino_dir, base) != estado_inicial:
            # ``reaproveitar=False`` continua forçando a escrita em chamadas
            # isoladas, mas não desfaz o resultado de uma chamada concorrente.
            existente = _existente_valido(destino_dir, base)
            if existente is not None:
                return existente

        if not conteudo:
            return None

        # A decisão precisa vir do conteúdo. O fallback de identificar_extensao
        # é público, mas não pode fazer um texto chamado ``arquivo.pdf`` entrar
        # no corpus.
        extensao = _identificar_extensao_real(conteudo)
        if extensao is None or extensao not in EXTENSOES_SUPORTADAS:
            return None

        caminho = destino_dir / f"{base}.{extensao}"
        digesto = hashlib.sha256(conteudo).hexdigest()
        ja_existia = _tem_sha256(caminho, digesto)
        if not ja_existia:
            _escrever_atomico(caminho, conteudo)

        # Não confie apenas no buffer baixado: o hash/bytes retornados devem
        # corresponder ao arquivo final lido ainda dentro do lock.
        final = _do_disco(caminho)
        return Baixado(
            caminho=final.caminho,
            sha256=final.sha256,
            bytes=final.bytes,
            extensao=final.extensao,
            content_type=content_type,
            nome_original=nome_original,
            ja_existia=ja_existia,
        )


def _tem_sha256(caminho: Path, esperado: str) -> bool:
    try:
        return caminho.is_file() and hashlib.sha256(caminho.read_bytes()).hexdigest() == esperado
    except OSError:
        return False


def _do_disco(caminho: Path) -> Baixado:
    conteudo = caminho.read_bytes()
    if not conteudo:
        raise ValueError(f"arquivo existente vazio: {caminho}")

    extensao = caminho.suffix.lower().lstrip(".")
    extensao_real = _identificar_extensao_real(conteudo)
    if extensao not in EXTENSOES_SUPORTADAS or extensao_real != extensao:
        identificada = extensao_real or "<desconhecida>"
        raise ValueError(
            f"assinatura/extensão incompatível em {caminho}: "
            f"esperada .{extensao or '<nenhuma>'}, identificada .{identificada}"
        )

    return Baixado(
        caminho=caminho,
        sha256=hashlib.sha256(conteudo).hexdigest(),
        bytes=len(conteudo),
        extensao=extensao,
        content_type=None,
        nome_original=None,
        ja_existia=True,
    )


def _fsync_diretorio(diretorio: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descritor = os.open(os.fspath(diretorio), flags)
    try:
        os.fsync(descritor)
    finally:
        os.close(descritor)


def _escrever_atomico(caminho: Path, conteudo: bytes) -> None:
    """Grava o documento sem expor um arquivo final parcialmente escrito."""
    parcial: Path | None = None
    descritor: int | None = None
    try:
        descritor, nome_parcial = tempfile.mkstemp(
            prefix=f".{caminho.name}.",
            suffix=".part",
            dir=os.fspath(caminho.parent),
        )
        parcial = Path(nome_parcial)
        with os.fdopen(descritor, "wb") as arquivo:
            descritor = None
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(parcial, caminho)
        try:
            _fsync_diretorio(caminho.parent)
        except Exception:
            # O replace já tornou o arquivo final observável. Sem uma cópia
            # transacional para restaurar, um erro de durabilidade do diretório
            # não pode apagar um documento válido nem virar falha da coleta.
            pass
    except BaseException:
        if descritor is not None:
            try:
                os.close(descritor)
            except OSError:
                pass
        if parcial is not None:
            _remover_parcial(parcial)
        raise


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
    destino_dir = _destino_canonico(destino_dir)
    # A lista pode ser vazia (ou todos os itens podem ser filtrados). A
    # manutenção fica fora do loop para também limpar esse caminho.
    _limpar_residuos_part(destino_dir)
    try:
        brutos = pncp.arquivos_contrato(
            contrato["cnpj_orgao"],
            contrato["ano_contrato"],
            contrato["sequencial_contrato"],
        ) or []
        saida: list[tuple[dict[str, Any], Baixado]] = []
        for bruto in brutos:
            if not bruto.get("statusAtivo", True):
                continue
            url = bruto.get("url") or bruto.get("uri")
            if not url:
                continue
            papel = papel_documento_contrato(
                bruto.get("tipoDocumentoNome"), bruto.get("titulo", "")
            )
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
    finally:
        # Também cobre lista vazia, filtros que removem todos os itens e
        # exceções da API; o helper não remove um temporário cujo lock esteja
        # ocupado por outro processo.
        _limpar_residuos_part(destino_dir)
