"""Post-scrape integrity check for a mirror directory.

``oslabs-scrape verify`` answers two questions:

1. does every file listed in ``manifest.json`` exist and still hash correctly?
2. do the links/images inside the saved pages resolve to files that are really
   in the mirror (i.e. does the snapshot work offline)?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .assets import extract_asset_refs
from .config import Config
from .discover import extract_page_links
from .manifest import Manifest
from .util import sha256_file, url_to_relpath


@dataclass
class VerifyResult:
    checked_files: int = 0
    hash_mismatch: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    #: target relative path -> pages that reference it
    broken_local_refs: dict[str, list[str]] = field(default_factory=dict)
    checked_pages: int = 0

    @property
    def healthy(self) -> bool:
        return not self.hash_mismatch and not self.missing_files

    @property
    def clean(self) -> bool:
        return self.healthy and not self.broken_local_refs


def verify_mirror(config: Config, *, check_links: bool = True) -> VerifyResult:
    result = VerifyResult()
    manifest = Manifest.load(config.manifest_path)
    out_dir = config.out_dir

    for rel_key in manifest:
        path = out_dir.joinpath(*rel_key.split("/"))
        result.checked_files += 1
        if not path.is_file():
            result.missing_files.append(rel_key)
            continue
        expected = manifest.items[rel_key].sha256
        if expected and sha256_file(path) != expected:
            result.hash_mismatch.append(rel_key)

    if not check_links:
        return result

    known = set(manifest.items)
    for rel_key in manifest:
        if not rel_key.endswith((".html", ".htm")):
            continue
        path = out_dir.joinpath(*rel_key.split("/"))
        if not path.is_file():
            continue
        result.checked_pages += 1
        page_url = config.base_url + rel_key
        html = path.read_text(encoding="utf-8", errors="replace")

        targets: list[str] = []
        for ref in extract_asset_refs(html, page_url):
            targets.append(ref.url)
        for link in extract_page_links(html, page_url):
            targets.append(link)

        for target in targets:
            try:
                local = url_to_relpath(target, config.base_url).as_posix()
            except Exception:  # noqa: BLE001 - defensive: odd URL in the page
                continue
            if local not in known:
                result.broken_local_refs.setdefault(local, []).append(rel_key)

    return result


def format_result(result: VerifyResult) -> list[str]:
    lines = [
        f"校验文件: {result.checked_files} 个（页面 {result.checked_pages} 个）",
    ]
    if result.missing_files:
        lines.append(f"缺失文件: {len(result.missing_files)}")
        lines.extend(f"  - {item}" for item in result.missing_files[:20])
    if result.hash_mismatch:
        lines.append(f"哈希不一致: {len(result.hash_mismatch)}")
        lines.extend(f"  - {item}" for item in result.hash_mismatch[:20])
    if result.broken_local_refs:
        lines.append(f"本地引用目标缺失: {len(result.broken_local_refs)} 个")
        for target, pages in list(result.broken_local_refs.items())[:20]:
            extra = f"，共 {len(pages)} 页引用" if len(pages) > 1 else ""
            lines.append(f"  - {target}（引用自 {pages[0]}{extra}）")
    if result.clean:
        lines.append("结果: 通过 ✅")
    elif result.healthy:
        lines.append("结果: 文件完整，但有引用未镜像 ⚠️")
    else:
        lines.append("结果: 失败 ❌")
    return lines


def ensure_within_out_dir(path: Path, out_dir: Path) -> bool:
    """Guard used by callers that delete files during ``--prune``."""
    try:
        resolved = path.resolve()
        root = out_dir.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents
