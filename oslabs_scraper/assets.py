"""Extraction of asset references (images, stylesheets, downloads)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.parse import urlsplit

from .htmltree import Node, parse
from .util import normalize_url, origin_of

#: Elements and attributes that point at a resource which should be mirrored.
REFERENCE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "img": ("src", "data-src", "srcset"),
    "source": ("src", "srcset"),
    "script": ("src",),
    "link": ("href",),
    "iframe": ("src",),
    "video": ("src", "poster"),
    "audio": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "track": ("src",),
}

#: ``<link rel=...>`` values that reference something worth mirroring.
MIRRORED_LINK_RELS = frozenset(
    {
        "stylesheet",
        "icon",
        "shortcut icon",
        "apple-touch-icon",
        "apple-touch-icon-precomposed",
        "mask-icon",
        "preload",
        "prefetch",
        "manifest",
    }
)

#: Extensions of files linked with ``<a href>`` that we treat as assets.
DOWNLOADABLE_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avif",
        ".bmp",
        ".bz2",
        ".c",
        ".conf",
        ".css",
        ".csv",
        ".doc",
        ".docx",
        ".eot",
        ".gif",
        ".gz",
        ".h",
        ".ico",
        ".jpeg",
        ".jpg",
        ".json",
        ".map",
        ".md",
        ".mp4",
        ".otf",
        ".pdf",
        ".png",
        ".py",
        ".sh",
        ".svg",
        ".tar",
        ".tgz",
        ".ttf",
        ".txt",
        ".wasm",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
)

KIND_BY_EXTENSION = {
    ".css": "stylesheet",
    ".js": "script",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".webp": "image",
    ".avif": "image",
    ".ico": "image",
    ".woff": "font",
    ".woff2": "font",
    ".ttf": "font",
    ".otf": "font",
    ".eot": "font",
}


@dataclass(frozen=True)
class AssetRef:
    """A resource referenced by a page."""

    url: str
    kind: str

    @property
    def extension(self) -> str:
        return extension_of(self.url)


def extension_of(url: str) -> str:
    """Lower-case file extension of *url* (``""`` when it has none)."""
    path = urlsplit(url).path.lower()
    last = path.rsplit("/", 1)[-1]
    if "." not in last:
        return ""
    return path[path.rfind(".") :]


def classify(url: str) -> str:
    return KIND_BY_EXTENSION.get(extension_of(url), "other")


def extract_asset_refs(
    html: str,
    page_url: str,
    *,
    include_external: bool = False,
) -> list[AssetRef]:
    """Return the assets referenced by *html*, in document order, deduplicated.

    Only same-origin resources are returned unless *include_external* is set
    (external hosts are usually CDNs that are not part of the mirror).
    """
    root = parse(html)
    origin = origin_of(page_url)
    refs: list[AssetRef] = []
    seen: set[str] = set()

    for node in root.iter():
        attributes = REFERENCE_ATTRIBUTES.get(node.tag)
        if attributes is None:
            continue
        if node.tag == "link" and not _is_mirrored_link(node):
            continue
        for attribute in attributes:
            raw = node.get(attribute).strip()
            if not raw:
                continue
            for candidate in _split_srcset(raw) if attribute == "srcset" else [raw]:
                url = _resolve(candidate, page_url, origin, include_external)
                if url is None or url in seen:
                    continue
                seen.add(url)
                refs.append(AssetRef(url=url, kind=classify(url)))

    for node in root.iter():
        if node.tag != "a":
            continue
        href = node.get("href").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = _resolve(href, page_url, origin, include_external)
        if url is None or url in seen:
            continue
        if extension_of(url) not in DOWNLOADABLE_EXTENSIONS:
            continue
        seen.add(url)
        refs.append(AssetRef(url=url, kind="download"))

    return refs


def _is_mirrored_link(node: Node) -> bool:
    rel = node.get("rel").strip().lower()
    if not rel:
        return False
    return any(value in MIRRORED_LINK_RELS for value in rel.split())


def _split_srcset(value: str) -> Iterable[str]:
    for candidate in value.split(","):
        candidate = candidate.strip()
        if candidate:
            yield candidate.split()[0]


def _resolve(
    href: str,
    page_url: str,
    origin: str,
    include_external: bool,
) -> str | None:
    if href.startswith("data:"):
        return None
    try:
        url = normalize_url(href, page_url)
    except ValueError:
        return None
    if not include_external and origin_of(url) != origin:
        return None
    return url


def summarize(refs: Sequence[AssetRef]) -> dict[str, int]:
    """Count references per kind - used by ``--dry-run`` output."""
    counts: dict[str, int] = {}
    for ref in refs:
        counts[ref.kind] = counts.get(ref.kind, 0) + 1
    return dict(sorted(counts.items()))
