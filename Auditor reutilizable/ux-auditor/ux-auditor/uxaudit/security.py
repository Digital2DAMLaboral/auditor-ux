"""Controles de seguridad del UX-Auditor.

Principios aplicados:
  * Validar toda entrada externa (URLs, rutas, ficheros de configuración y datos
    que devuelve la página auditada, que se consideran NO confiables).
  * Lista blanca de esquemas y bloqueo de direcciones peligrosas (SSRF).
  * Escritura de ficheros atómica, con nombres generados y sin seguir enlaces simbólicos.
  * Sin shell, sin eval y sin deserialización insegura en ningún punto del programa.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import tempfile
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


class SecurityError(ValueError):
    """Entrada rechazada por una política de seguridad."""


MAX_URL_LENGTH = 2048
ALLOWED_TARGET_SCHEMES = {"http", "https"}
# Esquemas que el navegador puede usar internamente sin salir a la red.
INTERNAL_SCHEMES = {"data", "blob", "about"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


@dataclass(frozen=True)
class Target:
    """Objetivo de auditoría ya validado."""
    kind: str                    # "url" | "file"
    url: str                     # URL que abrirá el navegador
    display: str                 # versión segura para mostrar en informes
    base_dir: Optional[Path] = None  # para ficheros locales: carpeta permitida


# ───────────────────────── texto no confiable ─────────────────────────

def clean_text(value: object, max_len: int = 300) -> str:
    """Convierte un valor no confiable en texto seguro para almacenar.

    Elimina caracteres de control y de reordenación bidireccional (ataques
    «Trojan Source» en informes), normaliza a NFC y trunca.
    """
    if value is None:
        return ""
    text = str(value)
    if len(text) > max_len * 4:          # evita trabajar con cadenas enormes
        text = text[: max_len * 4]
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS.sub("", text).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r" {2,}", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def clamp_number(value: object, low: float, high: float) -> Optional[float]:
    """Devuelve un número finito dentro de [low, high] o None si no es válido."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / infinito
        return None
    return max(low, min(high, float(value)))


def clamp_int(value: object, low: int = 0, high: int = 1_000_000) -> int:
    number = clamp_number(value, low, high)
    return int(number) if number is not None else low


# ───────────────────────── objetivos (URL / fichero) ─────────────────────────

def validate_target(raw: str) -> Target:
    """Valida el objetivo indicado por el usuario (URL http/https o fichero HTML local)."""
    if not isinstance(raw, str) or not raw.strip():
        raise SecurityError("El objetivo está vacío.")
    raw = raw.strip()
    if len(raw) > MAX_URL_LENGTH:
        raise SecurityError(f"El objetivo supera {MAX_URL_LENGTH} caracteres.")
    if _CONTROL_CHARS.search(raw):
        raise SecurityError("El objetivo contiene caracteres de control.")

    scheme_only = re.match(r"^([A-Za-z][A-Za-z0-9+.-]+):(?!//)", raw)
    if scheme_only and not re.match(r"^[A-Za-z]:[\\/]", raw):  # «C:\...» es una ruta de Windows
        raise SecurityError(f"Esquema no permitido: «{clean_text(scheme_only.group(1), 20)}». Solo se admiten http y https.")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw):
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        if scheme == "file":
            raise SecurityError("Indica los ficheros locales como ruta (./web/index.html), no como file://.")
        if scheme not in ALLOWED_TARGET_SCHEMES:
            raise SecurityError(f"Esquema no permitido: «{scheme}». Solo se admiten http y https.")
        if not parts.hostname:
            raise SecurityError("La URL no tiene nombre de host.")
        if parts.username is not None or parts.password is not None:
            raise SecurityError("No incluyas usuario ni contraseña en la URL: quedarían registrados en los informes.")
        try:
            port = parts.port
        except ValueError as exc:
            raise SecurityError("Puerto no válido en la URL.") from exc
        host = parts.hostname.encode("idna").decode("ascii") if not _is_ip(parts.hostname) else parts.hostname
        netloc = f"[{host}]" if ":" in host else host
        if port:
            netloc += f":{port}"
        url = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
        return Target("url", url, redact_url(url))

    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SecurityError(f"No existe el fichero o carpeta: {clean_text(raw, 200)}") from exc
    if path.is_dir():
        path = path / "index.html"
        if not path.is_file():
            raise SecurityError("La carpeta no contiene index.html.")
    if not path.is_file():
        raise SecurityError("El objetivo local debe ser un fichero HTML.")
    if path.suffix.lower() not in HTML_SUFFIXES:
        raise SecurityError("Solo se pueden auditar ficheros .html, .htm o .xhtml.")
    return Target("file", path.as_uri(), path.name, base_dir=path.parent)


def redact_url(url: str) -> str:
    """Quita credenciales, parámetros y fragmento (pueden contener tokens)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[URL no válida]"
    if parts.scheme == "file":
        return Path(parts.path).name or "fichero local"
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{parts.port}" if parts.port else "")
    shown = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    if parts.query:
        shown += "?…"
    return clean_text(shown, 300)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


# ───────────────────────── política de red (SSRF) ─────────────────────────

# Siempre prohibidas: metadatos de nube, enlace local, multidifusión, reservadas.
_ALWAYS_BLOCKED = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
    "100.100.100.200/32",           # metadatos Alibaba Cloud
    "::/128", "fe80::/10", "ff00::/8", "fd00:ec2::254/128",
)]


def ip_forbidden(ip_text: str, block_private: bool) -> Optional[str]:
    """Motivo por el que una IP está prohibida, o None si se permite."""
    try:
        ip = ipaddress.ip_address(ip_text.strip("[]").split("%")[0])
    except ValueError:
        return "dirección IP no válida"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    for net in _ALWAYS_BLOCKED:
        if ip.version == net.version and ip in net:
            return "dirección reservada o de metadatos de la nube"
    if block_private and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                          or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"))):
        return "red privada o local (bloqueada por --bloquear-redes-privadas)"
    return None


@lru_cache(maxsize=512)
def _resolve(host: str) -> tuple[str, ...]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return tuple(sorted({info[4][0] for info in infos}))


def host_forbidden(host: str, block_private: bool) -> Optional[str]:
    """Comprueba todas las IPs a las que resuelve un host."""
    if not host:
        return "host vacío"
    host = host.strip("[]").lower()
    if _is_ip(host):
        return ip_forbidden(host, block_private)
    if block_private and (host == "localhost" or host.endswith(".localhost")):
        return "red privada o local (bloqueada por --bloquear-redes-privadas)"
    try:
        addresses = _resolve(host)
    except (socket.gaierror, UnicodeError, OSError):
        return None  # que falle el navegador con su error normal de DNS
    for address in addresses:
        reason = ip_forbidden(address, block_private)
        if reason:
            return reason
    return None


class RequestPolicy:
    """Decide qué peticiones puede hacer el navegador durante la auditoría."""

    def __init__(self, target: Target, block_private: bool):
        self.target = target
        self.block_private = block_private
        self.blocked: list[str] = []

    def check(self, url: str) -> Optional[str]:
        try:
            parts = urlsplit(url)
        except ValueError:
            return "URL mal formada"
        scheme = parts.scheme.lower()
        if scheme in INTERNAL_SCHEMES:
            return None
        if scheme == "file":
            if self.target.kind != "file" or self.target.base_dir is None:
                return "acceso a ficheros locales desde una web remota"
            try:
                from urllib.request import url2pathname
                requested = Path(url2pathname(parts.path)).resolve()
            except (OSError, ValueError):
                return "ruta local no válida"
            base = self.target.base_dir
            if requested != base and base not in requested.parents:
                return "fichero fuera de la carpeta auditada"
            return None
        if scheme in ("http", "https", "ws", "wss"):
            return host_forbidden(parts.hostname or "", self.block_private)
        return f"esquema no permitido ({clean_text(scheme, 20)})"

    def record_block(self, url: str, reason: str) -> None:
        if len(self.blocked) < 50:
            self.blocked.append(f"{redact_url(url)} — {reason}")


# ───────────────────────── ficheros ─────────────────────────

def ensure_output_dir(path: str | os.PathLike) -> Path:
    """Crea (si hace falta) la carpeta de salida, sin aceptar enlaces simbólicos."""
    out = Path(path).expanduser()
    if out.is_symlink():
        raise SecurityError("La carpeta de salida no puede ser un enlace simbólico.")
    out.mkdir(parents=True, exist_ok=True, mode=0o755)
    out = out.resolve(strict=True)
    if not out.is_dir():
        raise SecurityError("La ruta de salida no es una carpeta.")
    return out


def safe_filename(name: str) -> str:
    if not _SAFE_NAME.match(name) or ".." in name:
        raise SecurityError(f"Nombre de fichero no permitido: {clean_text(name, 60)}")
    return name


def atomic_write(directory: Path, name: str, data: bytes, mode: int = 0o644) -> Path:
    """Escribe un fichero de forma atómica dentro de `directory`.

    El nombre se valida (sin rutas ni «..») y nunca se sigue un enlace simbólico
    existente: se escribe en un temporal y se reemplaza con os.replace.
    """
    safe_filename(name)
    final = directory / name
    if final.is_symlink():
        raise SecurityError(f"Se ha encontrado un enlace simbólico en el destino: {name}")
    fd, tmp = tempfile.mkstemp(prefix=".uxaudit-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, final)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return final


def append_line(directory: Path, name: str, line: str, max_bytes: int = 5_000_000) -> None:
    """Añade una línea a un fichero de histórico (sin seguir enlaces simbólicos)."""
    safe_filename(name)
    path = directory / name
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            raise SecurityError("El histórico supera el tamaño máximo; archívalo o bórralo.")
        fd = os.open(path, flags, 0o644)
    except OSError as exc:
        raise SecurityError(f"No se puede escribir el histórico: {exc.strerror}") from exc
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


def read_text_limited(path: str | os.PathLike, max_bytes: int, what: str = "fichero") -> str:
    """Lee un fichero de texto UTF-8 rechazando los que superan `max_bytes`."""
    p = Path(path).expanduser()
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise SecurityError(f"No se puede leer el {what}: {clean_text(str(path), 200)}") from exc
    if not p.is_file():
        raise SecurityError(f"El {what} no es un fichero normal.")
    if size > max_bytes:
        raise SecurityError(f"El {what} supera el tamaño máximo ({max_bytes // 1024} KB).")
    with open(p, "rb") as handle:
        data = handle.read(max_bytes + 1)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SecurityError(f"El {what} no está en UTF-8.") from exc


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].strip("-") or "auditoria")
