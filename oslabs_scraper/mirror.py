"""The mirror engine: discover, download, snapshot, index, prune."""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .assets import extract_asset_refs
from .config import Config
from .discover import NavItem, extract_page_links, extract_title, nav_page_urls, parse_nav
from .errors import ScrapeError
from .fetcher import DEFAULT_USER_AGENT, Fetcher
from .manifest import Entry, Manifest
from .util import (
    atomic_write,
    atomic_write_text,
    format_bytes,
    normalize_url,
    sha256_bytes,
    site_root,
    url_to_relpath,
)

Logger = Callable[[str], None]

PAGE = "page"
ASSET = "asset"


@dataclass
class Report:
    """Outcome of one mirror run - everything the CLI needs to summarise it."""

    site_title: str = ""
    nav: list[NavItem] = field(default_factory=list)
    url_to_rel: dict[str, str] = field(default_factory=dict)
    rel_to_url: dict[str, str] = field(default_factory=dict)
    asset_rel_to_url: dict[str, str] = field(default_factory=dict)
    page_new: int = 0
    page_changed: int = 0
    page_unchanged: int = 0
    asset_new: int = 0
    asset_changed: int = 0
    asset_unchanged: int = 0
    downloaded_bytes: int = 0
    removed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manifest_changed: bool = False
    hit_page_limit: bool = False

    @property
    def page_count(self) -> int:
        return len(self.rel_to_url)

    @property
    def asset_count(self) -> int:
        return len(self.asset_rel_to_url)

    @property
    def changed(self) -> bool:
        return bool(
            self.page_new
            or self.page_changed
            or self.asset_new
            or self.asset_changed
            or self.removed
        )

    def summary_lines(self) -> list[str]:
        lines = [
            f"页面: 新增 {self.page_new} / 更新 {self.page_changed} / 未变 {self.page_unchanged}",
            f"资源: 新增 {self.asset_new} / 更新 {self.asset_changed} / 未变 {self.asset_unchanged}",
            f"下载: {format_bytes(self.downloaded_bytes)}",
        ]
        if self.removed:
            lines.append(f"清理: 删除 {len(self.removed)} 个已不存在的文件")
        if self.errors:
            lines.append(f"失败: {len(self.errors)} 个 URL")
        return lines


class Mirror:
    """Mirrors one site into ``config.out_dir``."""

    def __init__(
        self,
        config: Config,
        *,
        fetcher: Fetcher | None = None,
        log: Logger | None = None,
    ) -> None:
        self.config = config
        self.log: Logger = log or (lambda _message: None)
        self.fetcher = fetcher or Fetcher(
            user_agent=config.user_agent or DEFAULT_USER_AGENT,
            timeout=config.timeout,
            retries=config.retries,
            delay=config.delay,
            verify=config.verify_tls,
            max_bytes=config.max_bytes,
            respect_robots=config.respect_robots,
        )
        self._owns_fetcher = fetcher is None
        self._path_owner: dict[str, str] = {}
        self._assets: dict[str, str] = {}
        self._nav_parsed = False

    # -- public API -------------------------------------------------------- #
    def run(self, *, force: bool = False, prune: bool = False, dry_run: bool = False) -> Report:
        config = self.config
        old = Manifest.load(config.manifest_path)
        new = Manifest(base_url=config.base_url)
        report = Report()
        self._path_owner = {rel: entry.url for rel, entry in old.items.items()}

        try:
            self._crawl(old, new, report, force=force, dry_run=dry_run)
            self._mirror_assets(old, new, report, force=force, dry_run=dry_run)
        finally:
            if self._owns_fetcher:
                self.fetcher.close()

        if prune:
            self._prune(old, new, report, dry_run=dry_run)

        if not dry_run:
            report.manifest_changed = new.save(config.manifest_path)
            self._write_index(report, dry_run=dry_run)
        return report

    # -- crawling ---------------------------------------------------------- #
    def _crawl(
        self,
        old: Manifest,
        new: Manifest,
        report: Report,
        *,
        force: bool,
        dry_run: bool,
    ) -> None:
        queue: deque[str] = deque([self.config.start_url])
        seen: set[str] = set()

        while queue:
            if report.page_count >= self.config.max_pages:
                report.hit_page_limit = True
                self.log(f"! 达到 --max-pages={self.config.max_pages} 上限，停止爬取")
                break
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            rel, content = self._mirror_one(url, old, new, report, kind=PAGE, force=force, dry_run=dry_run)
            if rel is None or content is None:
                continue
            report.url_to_rel[url] = rel
            report.rel_to_url[rel] = url

            html = content.decode("utf-8", errors="replace")
            if not self._nav_parsed:
                self._nav_parsed = True
                report.site_title = extract_title(html, default="站点镜像")
                report.nav = parse_nav(html, self.config.base_url)
                for seed in nav_page_urls(report.nav):
                    if seed not in seen and not self.config.is_skipped(seed):
                        queue.append(seed)
                # A page that is neither in the nav nor linked from another page
                # is still listed in mkdocs' search index - use it as a safety net.
                for seed in self._search_index_urls():
                    if seed not in seen and not self.config.is_skipped(seed):
                        queue.append(seed)

            for link in extract_page_links(html, url):
                if link not in seen and not self.config.is_skipped(link):
                    queue.append(link)
            for ref in extract_asset_refs(
                html, url, include_external=self.config.include_external
            ):
                if not self.config.is_skipped(ref.url):
                    self._assets.setdefault(ref.url, ref.kind)

    def _search_index_urls(self) -> list[str]:
        """Page URLs listed in mkdocs' ``search/search_index.json``.

        The search index is generated from the site's ``nav``/docs tree, so it
        catches pages that are neither in the sidebar nor linked from another
        page (this site has two such orphans).  Failures are non-fatal.
        """
        url = site_root(self.config.base_url) + "search/search_index.json"
        try:
            result = self.fetcher.get(url)
        except ScrapeError:
            return []
        try:
            payload = json.loads(result.text())
        except ValueError:
            return []
        docs = payload.get("docs") if isinstance(payload, dict) else None
        if not isinstance(docs, list):
            return []

        urls: list[str] = []
        seen: set[str] = set()
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            location = str(doc.get("location") or "").split("#", 1)[0]
            if not location:
                continue
            try:
                absolute = normalize_url(location, self.config.base_url)
            except ValueError:
                continue
            if absolute not in seen:
                seen.add(absolute)
                urls.append(absolute)
        if urls:
            self.log(f"· search_index.json 提供 {len(urls)} 个页面地址")
        return urls

    def _mirror_assets(
        self,
        old: Manifest,
        new: Manifest,
        report: Report,
        *,
        force: bool,
        dry_run: bool,
    ) -> None:
        total = len(self._assets)
        for index, url in enumerate(sorted(self._assets), start=1):
            rel, _content = self._mirror_one(
                url, old, new, report, kind=ASSET, force=force, dry_run=dry_run
            )
            if rel is not None:
                report.asset_rel_to_url[rel] = url
            if total > 20 and index % 20 == 0:
                self.log(f"  资源 {index}/{total}")

    # -- one resource ------------------------------------------------------ #
    def _mirror_one(
        self,
        url: str,
        old: Manifest,
        new: Manifest,
        report: Report,
        *,
        kind: str,
        force: bool,
        dry_run: bool,
    ) -> tuple[str | None, bytes | None]:
        rel_key = self._relpath_for(url)
        dest = self._local_path(rel_key)
        previous = old.get(rel_key)

        etag = previous.etag if previous and dest.is_file() and not force else ""
        last_modified = previous.last_modified if previous and dest.is_file() and not force else ""

        try:
            result = self.fetcher.get(url, etag=etag, last_modified=last_modified)
        except ScrapeError as exc:
            report.errors.append(str(exc))
            self.log(f"  ! {exc}")
            return None, None

        if result.not_modified and previous is not None:
            new.put(rel_key, previous)
            self._count(report, kind, "unchanged")
            content = dest.read_bytes() if dest.is_file() else None
            return rel_key, content

        digest = sha256_bytes(result.content)
        entry = Entry(
            url=url,
            sha256=digest,
            size=len(result.content),
            content_type=result.content_type,
            etag=result.etag,
            last_modified=result.last_modified,
        )
        new.put(rel_key, entry)
        report.downloaded_bytes += len(result.content)

        if previous is not None and previous.sha256 == digest and dest.is_file():
            self._count(report, kind, "unchanged")
            return rel_key, result.content

        if not dry_run:
            atomic_write(dest, result.content)
        self._count(report, kind, "new" if previous is None else "changed")
        size = format_bytes(len(result.content))
        marker = "+" if previous is None else "~"
        self.log(f"  {marker} {rel_key}  ({size})")
        return rel_key, result.content

    @staticmethod
    def _count(report: Report, kind: str, state: str) -> None:
        attribute = f"{kind}_{state}"
        setattr(report, attribute, getattr(report, attribute) + 1)

    def _relpath_for(self, url: str) -> str:
        rel = url_to_relpath(url, self.config.base_url)
        key = rel.as_posix()
        owner = self._path_owner.get(key)
        if owner is not None and owner != url:
            digest = sha256_bytes(url.encode("utf-8"))[:8]
            if rel.suffix:
                rel = rel.with_name(f"{rel.stem}-{digest}{rel.suffix}")
            else:
                rel = rel.with_name(f"{rel.name}-{digest}")
            key = rel.as_posix()
        self._path_owner[key] = url
        return key

    def _local_path(self, rel_key: str) -> Path:
        return self.config.out_dir.joinpath(*rel_key.split("/"))

    # -- pruning ----------------------------------------------------------- #
    def _prune(self, old: Manifest, new: Manifest, report: Report, *, dry_run: bool) -> None:
        stale = sorted(old.relative_paths() - new.relative_paths())
        for rel_key in stale:
            path = self._local_path(rel_key)
            if not dry_run and path.is_file():
                path.unlink()
                self._remove_empty_parents(path.parent)
            report.removed.append(rel_key)
        if stale:
            self.log(f"  - 清理 {len(stale)} 个过期文件")

    def _remove_empty_parents(self, directory: Path) -> None:
        out_root = self.config.out_dir.resolve()
        current = directory.resolve()
        while current != out_root and out_root in current.parents:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    # -- index ------------------------------------------------------------- #
    def _write_index(self, report: Report, *, dry_run: bool) -> None:
        index_path = self.config.index_path
        if index_path is None:
            return
        text = render_index(report, self.config)
        if index_path.is_file() and index_path.read_text(encoding="utf-8") == text:
            return
        if not dry_run:
            atomic_write_text(index_path, text)


def render_index(report: Report, config: Config) -> str:
    """Render ``INDEX.md``: the site outline with links to the local snapshot."""
    title = report.site_title or "站点镜像"
    out_dir = _index_link_prefix(config)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines: list[str] = [
        f"# {title} 镜像索引",
        "",
        f"- 源站：<{config.base_url}>",
        f"- 快照目录：[`{out_dir}/`]({out_dir}/)",
        f"- 页面：{report.page_count} · 资源：{report.asset_count}",
        f"- 生成日期：{today}",
        "",
        "> 本索引由 `oslabs-scraper` 自动生成，抓取的是站点原始 HTML 快照。",
        "",
        "## 站点导航",
        "",
    ]
    lines.extend(_render_nav_items(report.nav, report, out_dir, depth=0))

    linked = {url for url in report.url_to_rel}
    nav_urls = {item.href for item in _flatten(report.nav) if item.href}
    extra = [url for url in linked if url not in nav_urls]
    if extra:
        lines.extend(["", "## 导航之外的页面", ""])
        for url in extra:
            rel = report.url_to_rel[url]
            lines.append(f"- [{rel}]({out_dir}/{rel})")

    if report.errors:
        lines.extend(["", "## 抓取失败的 URL", ""])
        for error in report.errors:
            lines.append(f"- `{error}`")

    return "\n".join(lines) + "\n"


def _index_link_prefix(config: Config) -> str:
    """Relative link from ``INDEX.md`` to the snapshot directory."""
    out_dir = config.out_dir
    index_path = config.index_path
    if index_path is None:
        return out_dir.as_posix()
    try:
        relative = os.path.relpath(out_dir, index_path.parent)
    except ValueError:  # different drives on Windows
        return out_dir.as_posix()
    return Path(relative).as_posix()


def _flatten(items: list[NavItem]) -> list[NavItem]:
    flat: list[NavItem] = []
    for item in items:
        flat.extend(node for node, _depth in item.walk())
    return flat


def _render_nav_items(
    items: list[NavItem],
    report: Report,
    out_dir: str,
    *,
    depth: int,
) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    for item in items:
        if item.href:
            rel = report.url_to_rel.get(item.href)
            if rel:
                lines.append(f"{indent}- [{item.title}]({out_dir}/{rel})")
            else:
                lines.append(f"{indent}- {item.title}（未抓取）")
        else:
            lines.append(f"{indent}- **{item.title}**")
        lines.extend(
            _render_nav_items(list(item.children), report, out_dir, depth=depth + 1)
        )
    return lines
