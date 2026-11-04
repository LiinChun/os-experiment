"""URL normalisation, path mapping and small filesystem helpers.

The public API of this module is intentionally pure: every function is
deterministic and works on strings/bytes, which keeps it trivially testable.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .errors import UnsafePathError

DEFAULT_PORTS = {"http": 80, "https": 443}

# Characters that are illegal in Windows file names plus ASCII control chars.
_ILLEGAL_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')


# --------------------------------------------------------------------------- #
# URLs
# --------------------------------------------------------------------------- #
def is_http_url(url: str) -> bool:
    """Return ``True`` for ``http://`` / ``https://`` URLs."""
    return url.strip().lower().startswith(("http://", "https://"))


def normalize_url(url: str, base: str | None = None) -> str:
    """Return a canonical absolute form of *url*.

    Canonicalisation removes the fragment, lower-cases scheme and host, drops
    default ports and turns directory URLs (``/lab1/``) into their
    ``index.html`` equivalent so that the navigation and the crawler agree on
    the identity of a page.
    """
    absolute = urljoin(base, url) if base else url
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme in {url!r}")

    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"no host in {url!r}")
    if ":" in host and not host.startswith("["):  # IPv6 literal
        host = f"[{host}]"
    port = parts.port
    netloc = host if port in (None, DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"

    path = parts.path or "/"
    if path.endswith("/"):
        path += "index.html"

    return urlunsplit((scheme, netloc, path, parts.query, ""))


def origin_of(url: str) -> str:
    """Return ``scheme://host[:port]`` of *url*."""
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def site_root(url: str) -> str:
    """Return *url* reduced to the site root (``https://host/``)."""
    return origin_of(url) + "/"


def url_to_relpath(url: str, base_url: str) -> PurePosixPath:
    """Map *url* onto a relative path inside the mirror.

    ``https://host/lab1/part1.html`` becomes ``lab1/part1.html`` when
    *base_url* is ``https://host/``.  Paths are percent-decoded and stripped of
    characters that are illegal on Windows.  Paths that would escape the
    output directory raise :class:`UnsafePathError`.
    """
    base = urlsplit(base_url)
    base_path = base.path or "/"
    if not base_path.endswith("/"):
        base_path = base_path.rsplit("/", 1)[0] + "/"

    path = urlsplit(url).path or "/"
    if base_path != "/" and path.startswith(base_path):
        path = path[len(base_path) :]
    else:
        path = path.lstrip("/")

    if not path or path.endswith("/"):
        path += "index.html"

    segments: list[str] = []
    for raw in unquote(path).split("/"):
        if raw in ("", "."):
            continue
        if raw == "..":
            raise UnsafePathError(url, path)
        segments.append(_sanitize_segment(raw))

    if not segments:
        raise UnsafePathError(url, path)
    return PurePosixPath(*segments)


def _sanitize_segment(segment: str) -> str:
    """Replace characters that would break a checkout on Windows."""
    cleaned = _ILLEGAL_CHARS.sub("_", segment).rstrip(" .")
    return cleaned or "_"


def url_basename(url: str) -> str:
    """Return the last path segment of *url* (``""`` for directory URLs)."""
    path = urlsplit(url).path
    return path.rstrip("/").rsplit("/", 1)[-1]


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: os.PathLike[str] | str, data: bytes) -> None:
    """Write *data* to *path* atomically (same directory temp file + rename)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: os.PathLike[str] | str, text: str) -> None:
    atomic_write(path, text.encode("utf-8"))


def format_bytes(size: int) -> str:
    """Human readable byte count used in the CLI summary."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
