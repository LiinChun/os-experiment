"""End-to-end tests for the mirror engine using an in-memory fetcher."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from oslabs_scraper.config import Config
from oslabs_scraper.errors import FetchError
from oslabs_scraper.fetcher import FetchResult
from oslabs_scraper.mirror import Mirror

import support

BASE = "https://example.test/"

INDEX_HTML = """<html><head><title>测试站点</title></head><body>
<nav class="md-nav md-nav--primary" data-md-level="0">
  <label class="md-nav__title" for="__drawer">测试站点</label>
  <ul class="md-nav__list">
    <li class="md-nav__item">
      <a href="index.html" class="md-nav__link"><span class="md-ellipsis">概述</span></a>
      <nav class="md-nav" data-md-level="1">
        <ul class="md-nav__list">
          <li class="md-nav__item">
            <a href="lab1/part1.html" class="md-nav__link"><span class="md-ellipsis">实验一</span></a>
          </li>
        </ul>
      </nav>
    </li>
  </ul>
</nav>
<img src="assets/pic.png" alt="图片">
</body></html>"""

LAB1_HTML = (
    "<html><head><title>实验一 - 测试站点</title></head>"
    '<body><p>正文</p><a href="../index.html">返回</a>'
    '<a href="part2.html">下一页</a></body></html>'
)
PART2_HTML = "<html><head><title>实验一步骤</title></head><body>步骤</body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FakeFetcher:
    """Minimal stand-in for :class:`oslabs_scraper.fetcher.Fetcher`."""

    def __init__(self, resources: dict[str, tuple[str, bytes]]) -> None:
        self.resources = resources
        self.calls: list[str] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        etag: str = "",
        last_modified: str = "",
        allow_status: tuple[int, ...] = (),
        check_robots: bool = True,
    ) -> FetchResult:
        self.calls.append(url)
        if url not in self.resources:
            raise FetchError(url, status=404)
        content_type, body = self.resources[url]
        headers = {"Content-Type": content_type}
        if etag:
            headers["ETag"] = etag
        if etag and etag == f'"{len(body)}"':
            return FetchResult(url=url, status=304, headers=headers, not_modified=True)
        headers["ETag"] = f'"{len(body)}"'
        return FetchResult(url=url, status=200, content=body, headers=headers)

    def close(self) -> None:
        self.closed = True


def make_resources(**overrides: tuple[str, bytes]) -> dict[str, tuple[str, bytes]]:
    resources: dict[str, tuple[str, bytes]] = {
        BASE: ("text/html", INDEX_HTML.encode("utf-8")),
        BASE + "index.html": ("text/html", INDEX_HTML.encode("utf-8")),
        BASE + "lab1/part1.html": ("text/html", LAB1_HTML.encode("utf-8")),
        BASE + "lab1/part2.html": ("text/html", PART2_HTML.encode("utf-8")),
        BASE + "assets/pic.png": ("image/png", PNG),
    }
    resources.update(overrides)
    return resources


class MirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = support.make_temp_dir()
        self.addCleanup(support.remove_temp_dir, self.root)
        self.config = Config(
            base_url=BASE,
            out_dir=self.root / "raw",
            index_path=self.root / "INDEX.md",
            delay=0,
            retries=0,
        )

    def run_mirror(self, resources=None, **kwargs) -> tuple[Mirror, object]:
        fetcher = FakeFetcher(resources if resources is not None else make_resources())
        mirror = Mirror(self.config, fetcher=fetcher)
        report = mirror.run(**kwargs)
        return mirror, report

    def test_first_run_writes_pages_assets_manifest_and_index(self) -> None:
        _, report = self.run_mirror()
        raw = self.config.out_dir

        self.assertTrue((raw / "index.html").is_file())
        self.assertTrue((raw / "lab1" / "part1.html").is_file())
        self.assertTrue((raw / "assets" / "pic.png").is_file())
        self.assertTrue(self.config.manifest_path.is_file())
        self.assertTrue(self.config.index_path.is_file())

        self.assertEqual(report.page_count, 3)  # index + lab1/part1 + lab1/part2
        self.assertEqual(report.asset_count, 1)
        self.assertEqual(report.page_new, 3)
        self.assertEqual(report.asset_new, 1)
        expected_bytes = sum(
            len(body.encode("utf-8")) for body in (INDEX_HTML, LAB1_HTML, PART2_HTML)
        ) + len(PNG)
        self.assertEqual(report.downloaded_bytes, expected_bytes)

        index_text = self.config.index_path.read_text(encoding="utf-8")
        self.assertIn("测试站点", index_text)
        self.assertIn("[实验一](raw/lab1/part1.html)", index_text)

        manifest = json.loads(self.config.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["count"], 4)
        self.assertIn("lab1/part1.html", manifest["items"])
        self.assertEqual(manifest["items"]["assets/pic.png"]["content_type"], "image/png")

    def test_crawler_follows_links_outside_navigation(self) -> None:
        _, report = self.run_mirror()
        self.assertIn(BASE + "lab1/part2.html", report.url_to_rel)

    def test_second_run_is_a_no_op(self) -> None:
        self.run_mirror()
        _, report = self.run_mirror()

        self.assertEqual(report.page_new, 0)
        self.assertEqual(report.page_changed, 0)
        self.assertEqual(report.page_unchanged, 3)
        self.assertEqual(report.asset_changed, 0)
        self.assertEqual(report.downloaded_bytes, 0)
        self.assertFalse(report.manifest_changed)
        self.assertFalse(report.changed)

    def test_changed_page_is_rewritten(self) -> None:
        self.run_mirror()
        changed = PART2_HTML + "<!-- 修改 -->"
        _, report = self.run_mirror(
            make_resources(**{BASE + "lab1/part2.html": ("text/html", changed.encode("utf-8"))})
        )
        self.assertEqual(report.page_changed, 1)
        self.assertEqual(report.page_unchanged, 2)
        written = (self.config.out_dir / "lab1" / "part2.html").read_text(encoding="utf-8")
        self.assertIn("修改", written)

    def test_broken_asset_is_reported_but_pages_survive(self) -> None:
        resources = make_resources()
        del resources[BASE + "assets/pic.png"]
        _, report = self.run_mirror(resources)
        self.assertEqual(report.page_count, 3)
        self.assertEqual(report.asset_count, 0)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("assets/pic.png", report.errors[0])

    def test_prune_removes_deleted_pages(self) -> None:
        self.run_mirror()
        resources = make_resources()
        del resources[BASE + "lab1/part2.html"]
        # part2 is only reachable through part1, so drop the link as well.
        part1 = ("text/html", LAB1_HTML.replace('<a href="part2.html">下一页</a>', "").encode("utf-8"))
        resources[BASE + "lab1/part1.html"] = part1

        _, report = self.run_mirror(resources, prune=True)
        self.assertIn("lab1/part2.html", report.removed)
        self.assertFalse((self.config.out_dir / "lab1" / "part2.html").exists())
        self.assertTrue((self.config.out_dir / "lab1" / "part1.html").is_file())

    def test_dry_run_writes_nothing(self) -> None:
        _, report = self.run_mirror(dry_run=True)
        self.assertEqual(report.page_new, 3)
        self.assertFalse(self.config.out_dir.exists())

    def test_force_redownloads(self) -> None:
        self.run_mirror()
        fetcher = FakeFetcher(make_resources())
        mirror = Mirror(self.config, fetcher=fetcher)
        report = mirror.run(force=True)
        self.assertEqual(fetcher.calls.count(BASE + "index.html"), 1)
        self.assertGreater(report.downloaded_bytes, 0)
        self.assertEqual(report.page_unchanged, 3)

    def test_max_pages_stops_the_crawl(self) -> None:
        self.config.max_pages = 1
        _, report = self.run_mirror()
        self.assertEqual(report.page_count, 1)
        self.assertTrue(report.hit_page_limit)

    def test_site_root_and_index_are_the_same_page(self) -> None:
        _, report = self.run_mirror()
        self.assertEqual(report.url_to_rel[BASE + "index.html"], "index.html")
        self.assertNotIn(BASE, report.rel_to_url)

    def test_manifest_only_rewritten_when_content_changes(self) -> None:
        self.run_mirror()
        first = self.config.manifest_path.read_text(encoding="utf-8")
        self.run_mirror()
        self.assertEqual(first, self.config.manifest_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
