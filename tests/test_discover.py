"""Tests for navigation and link discovery."""

from __future__ import annotations

from pathlib import Path

import unittest

from oslabs_scraper.discover import (
    NavItem,
    extract_page_links,
    extract_title,
    nav_page_urls,
    parse_nav,
)

BASE = "https://os-labs.p.cs-lab.top/"
FIXTURE = Path(__file__).parent / "fixtures" / "nav.html"


class NavParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        cls.items = parse_nav(html, BASE)

    def test_top_level_items(self) -> None:
        self.assertEqual(len(self.items), 8)
        self.assertEqual(self.items[0].title, "实验概述")
        self.assertEqual(self.items[0].href, BASE + "index.html")

    def test_section_headers_have_no_href(self) -> None:
        by_title = {item.title: item for item in self.items}
        faq = by_title["常见问题"]
        self.assertIsNone(faq.href)
        self.assertEqual(len(faq.children), 5)
        self.assertEqual(faq.children[0].href, BASE + "faq/faq-env.html")

    def test_nested_section_is_preserved(self) -> None:
        lab3 = next(item for item in self.items if item.title.startswith("Lab3"))
        ai_section = next(
            child for child in lab3.children if child.title.startswith("AI 推理服务")
        )
        self.assertIsNone(ai_section.href)
        self.assertEqual(len(ai_section.children), 8)
        self.assertEqual(ai_section.children[0].href, BASE + "lab3/part5.html")

    def test_every_page_url_is_absolute_and_unique(self) -> None:
        urls = nav_page_urls(self.items)
        self.assertEqual(len(urls), 50)
        self.assertEqual(len(set(urls)), 50)
        self.assertTrue(all(url.startswith(BASE) for url in urls))

    def test_navigation_order_is_document_order(self) -> None:
        urls = nav_page_urls(self.items)
        self.assertEqual(urls[0], BASE + "index.html")
        self.assertEqual(urls[1], BASE + "platform/index.html")
        self.assertEqual(urls[2], BASE + "vm_env.html")

    def test_walk_reports_depth(self) -> None:
        depths = {item.title: depth for item, depth in self.items[0].walk()}
        self.assertEqual(depths["实验概述"], 0)
        self.assertEqual(depths["实验平台"], 1)
        self.assertEqual(depths["1.虚拟机实验环境使用指南"], 2)

    def test_missing_nav_returns_empty(self) -> None:
        self.assertEqual(parse_nav("<html><body>plain</body></html>", BASE), [])


class LinkExtractionTests(unittest.TestCase):
    PAGE = BASE + "lab1/part1.html"

    def test_keeps_only_same_site_pages(self) -> None:
        html = (
            '<a href="part2.html">sibling</a>'
            '<a href="../faq/lab1.html">parent</a>'
            '<a href="https://pdos.csail.mit.edu/6.828/">external</a>'
            '<a href="mailto:ta@example.test">mail</a>'
            '<a href="#section">anchor</a>'
            '<a href="part1.assets/pic.png">image</a>'
            '<a href="part3.html#step">with fragment</a>'
        )
        self.assertEqual(
            extract_page_links(html, self.PAGE),
            [BASE + "lab1/part2.html", BASE + "faq/lab1.html", BASE + "lab1/part3.html"],
        )

    def test_skip_prefixes(self) -> None:
        html = '<a href="/search/index.html">search</a><a href="/lab2/part1.html">lab2</a>'
        self.assertEqual(
            extract_page_links(html, BASE + "index.html"),
            [BASE + "lab2/part1.html"],
        )

    def test_extension_less_paths_count_as_pages(self) -> None:
        html = '<a href="/about">about</a>'
        self.assertEqual(extract_page_links(html, BASE + "index.html"), [BASE + "about"])


class TitleTests(unittest.TestCase):
    def test_title_tag(self) -> None:
        html = "<html><head><title>实验概述 - 操作系统2026秋</title></head></html>"
        self.assertEqual(extract_title(html), "实验概述")

    def test_falls_back_to_h1(self) -> None:
        self.assertEqual(extract_title("<h1>只有标题</h1>"), "只有标题")

    def test_default(self) -> None:
        self.assertEqual(extract_title("<p>无</p>", default="fallback"), "fallback")

    def test_nav_item_is_hashable(self) -> None:
        item = NavItem(title="a", href="https://example.test/a.html")
        self.assertEqual(len({item, item}), 1)


if __name__ == "__main__":
    unittest.main()
