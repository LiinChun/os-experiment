"""Tests for asset reference extraction."""

from __future__ import annotations

import unittest

from oslabs_scraper.assets import (
    AssetRef,
    DOWNLOADABLE_EXTENSIONS,
    classify,
    extension_of,
    extract_asset_refs,
    summarize,
)

BASE = "https://os-labs.p.cs-lab.top/"
PAGE = BASE + "lab1/part1.html"


class AssetExtractionTests(unittest.TestCase):
    HTML = """
    <img src="part1.assets/a.png">
    <img data-src="part1.assets/lazy.gif" src="data:image/gif;base64,AAAA">
    <img srcset="part1.assets/s1.png 1x, part1.assets/s2.png 2x">
    <link rel="stylesheet" href="/stylesheets/main.css">
    <link rel="preconnect" href="https://fonts.example.test">
    <script src="/javascripts/bundle.js"></script>
    <a href="files/guide.pdf">pdf</a>
    <a href="part2.html">another page</a>
    <a href="https://mirror.example.test/x.zip">external zip</a>
    """

    def test_same_site_references(self) -> None:
        urls = {ref.url for ref in extract_asset_refs(self.HTML, PAGE)}
        self.assertEqual(
            urls,
            {
                BASE + "lab1/part1.assets/a.png",
                BASE + "lab1/part1.assets/lazy.gif",
                BASE + "lab1/part1.assets/s1.png",
                BASE + "lab1/part1.assets/s2.png",
                BASE + "stylesheets/main.css",
                BASE + "javascripts/bundle.js",
                BASE + "lab1/files/guide.pdf",
            },
        )

    def test_data_uris_and_external_hosts_are_skipped(self) -> None:
        urls = [ref.url for ref in extract_asset_refs(self.HTML, PAGE)]
        self.assertFalse(any(url.startswith("data:") for url in urls))
        self.assertFalse(any("mirror.example.test" in url for url in urls))
        self.assertFalse(any("fonts.example.test" in url for url in urls))

    def test_external_can_be_included(self) -> None:
        urls = {ref.url for ref in extract_asset_refs(self.HTML, PAGE, include_external=True)}
        self.assertIn("https://mirror.example.test/x.zip", urls)

    def test_kinds(self) -> None:
        kinds = {ref.url.rsplit("/", 1)[-1]: ref.kind for ref in extract_asset_refs(self.HTML, PAGE)}
        self.assertEqual(kinds["a.png"], "image")
        self.assertEqual(kinds["main.css"], "stylesheet")
        self.assertEqual(kinds["bundle.js"], "script")
        self.assertEqual(kinds["guide.pdf"], "download")

    def test_duplicates_are_removed(self) -> None:
        html = '<img src="a.png"><img src="a.png"><img src="./a.png">'
        refs = extract_asset_refs(html, PAGE)
        self.assertEqual(len(refs), 1)

    def test_page_links_are_not_assets(self) -> None:
        html = '<a href="part2.html">page</a>'
        self.assertEqual(extract_asset_refs(html, PAGE), [])


class HelperTests(unittest.TestCase):
    def test_extension_of(self) -> None:
        self.assertEqual(extension_of(BASE + "a/b/c.PNG"), ".png")
        self.assertEqual(extension_of(BASE + "a/b/c"), "")
        self.assertEqual(extension_of(BASE + "a/b.v2/c"), "")

    def test_classify(self) -> None:
        self.assertEqual(classify(BASE + "x.woff2"), "font")
        self.assertEqual(classify(BASE + "x.bin"), "other")

    def test_summarize(self) -> None:
        refs = [AssetRef(BASE + "a.png", "image"), AssetRef(BASE + "b.png", "image")]
        self.assertEqual(summarize(refs), {"image": 2})

    def test_downloadable_extensions_cover_common_formats(self) -> None:
        for extension in (".pdf", ".zip", ".png", ".md"):
            self.assertIn(extension, DOWNLOADABLE_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
