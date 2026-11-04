"""The state file that makes repeated scrapes cheap and diffs meaningful.

``manifest.json`` lives inside the mirror directory and records, for every
mirrored file, its source URL, size, content type, sha256 and the HTTP
validators (``ETag`` / ``Last-Modified``) needed for conditional requests.

The file is only rewritten when its content actually changes, so a scrape that
finds nothing new leaves the working tree untouched.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

MANIFEST_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Entry:
    """One mirrored file."""

    url: str
    sha256: str
    size: int
    content_type: str = ""
    etag: str = ""
    last_modified: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Entry":
        return cls(
            url=str(data.get("url", "")),
            sha256=str(data.get("sha256", "")),
            size=int(data.get("size", 0) or 0),
            content_type=str(data.get("content_type", "")),
            etag=str(data.get("etag", "")),
            last_modified=str(data.get("last_modified", "")),
        )

    def with_payload(self, *, sha256: str, size: int, content_type: str = "") -> "Entry":
        return replace(
            self,
            sha256=sha256,
            size=size,
            content_type=content_type or self.content_type,
        )


class Manifest:
    """An ordered mapping ``relative path -> Entry``."""

    def __init__(self, base_url: str = "", items: Mapping[str, Entry] | None = None) -> None:
        self.base_url = base_url
        self.items: dict[str, Entry] = dict(items or {})

    # -- persistence ------------------------------------------------------- #
    @classmethod
    def load(cls, path: os.PathLike[str] | str) -> "Manifest":
        """Load a manifest, returning an empty one when it is missing/corrupt."""
        target = Path(path)
        if not target.is_file():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        items_raw = raw.get("items") or {}
        items: dict[str, Entry] = {}
        if isinstance(items_raw, dict):
            for rel, data in items_raw.items():
                if isinstance(data, dict):
                    items[str(rel)] = Entry.from_dict(data)
        return cls(base_url=str(raw.get("base_url", "")), items=items)

    def body(self) -> dict[str, object]:
        """The part of the manifest that must be diffable and deterministic."""
        return {
            "version": MANIFEST_VERSION,
            "base_url": self.base_url,
            "items": {rel: self.items[rel].to_dict() for rel in sorted(self.items)},
        }

    def save(self, path: os.PathLike[str] | str) -> bool:
        """Write the manifest; return ``True`` when the file changed."""
        target = Path(path)
        body = self.body()
        if target.is_file():
            try:
                current = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = None
            if isinstance(current, dict):
                current.pop("generated_at", None)
                current.pop("count", None)
                if current == body:
                    return False
        payload = dict(body)
        payload["count"] = len(self.items)
        payload["generated_at"] = utc_now()
        ordered = {
            "version": payload["version"],
            "base_url": payload["base_url"],
            "generated_at": payload["generated_at"],
            "count": payload["count"],
            "items": payload["items"],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(ordered, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        # Write bytes explicitly so Windows does not turn LF into CRLF and the
        # file stays identical across platforms.
        target.write_bytes(text.encode("utf-8"))
        return True

    # -- access ------------------------------------------------------------ #
    def get(self, relpath: str) -> Entry | None:
        return self.items.get(relpath)

    def put(self, relpath: str, entry: Entry) -> None:
        self.items[relpath] = entry

    def remove(self, relpath: str) -> Entry | None:
        return self.items.pop(relpath, None)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self.items))

    def relative_paths(self) -> set[str]:
        return set(self.items)

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.items.values())
