"""Tests for URL/path helpers."""

from __future__ import annotations

import unittest

from oslabs_scraper.errors import UnsafePathError
from oslabs_scraper.util import (
    format_bytes,
    normalize_url,
    origin_of,
    sha256_bytes,
    site_root,
    url_basename,
    url_to_relpath,
)

BASE = "https://os-labs.p.cs-lab.top/"


class NormalizeUrlTests(unittest.TestCase):
    def test_relative_link_is_resolved(self) -> None:
        self.assertEqual(
            normalize_url("part2.html", BASE + "lab1/part1.html"),
            BASE + "lab1/part2.html",
        )

    def test_directory_url_becomes_index(self) -> None:
        self.assertEqual(normalize_url("lab1/", BASE), BASE + "lab1/index.html")

    def test_bare_host_becomes_index(self) -> None:
        self.assertEqual(normalize_url("https://example.test"), "https://example.test/index.html")

    def test_fragment_is_dropped(self) -> None:
        self.assertEqual(
            normalize_url(BASE + "index.html#section-2"),
            BASE + "index.html",
        )

    def test_default_port_is_dropped(self) -> None:
        self.assertEqual(normalize_url("https://example.test:443/a.html"), "https://example.test/a.html")
        self.assertEqual(normalize_url("http://example.test:80/a.html"), "http://example.test/a.html")

    def test_custom_port_is_kept(self) -> None:
        self.assertEqual(normalize_url("https://example.test:8443/a.html"), "https://example.test:8443/a.html")

    def test_scheme_and_host_are_lower_cased(self) -> None:
        self.assertEqual(normalize_url("HTTPS://Example.TEST/A.html"), "https://example.test/A.html")

    def test_query_string_is_preserved(self) -> None:
        self.assertEqual(normalize_url("/a.html?x=1", BASE), BASE + "a.html?x=1")

    def test_non_http_scheme_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_url("mailto:someone@example.test")


class RelPathTests(unittest.TestCase):
    def test_root_maps_to_index(self) -> None:
        self.assertEqual(url_to_relpath(BASE, BASE).as_posix(), "index.html")
        self.assertEqual(url_to_relpath(BASE + "index.html", BASE).as_posix(), "index.html")

    def test_nested_page(self) -> None:
        self.assertEqual(
            url_to_relpath(BASE + "lab3/ai-model-kv.html", BASE).as_posix(),
            "lab3/ai-model-kv.html",
        )

    def test_percent_escapes_are_decoded(self) -> None:
        self.assertEqual(
            url_to_relpath(BASE + "a%20b/c%2Bd.png", BASE).as_posix(),
            "a b/c+d.png",
        )

    def test_windows_illegal_characters_are_replaced(self) -> None:
        self.assertEqual(
            url_to_relpath(BASE + "x/y:z%3F.html", BASE).as_posix(),
            "x/y_z_.html",
        )

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(UnsafePathError):
            url_to_relpath(BASE + "%2e%2e/secret.html", BASE)

    def test_query_string_does_not_leak_into_path(self) -> None:
        self.assertEqual(
            url_to_relpath(BASE + "a.png?rev=3", BASE).as_posix(),
            "a.png",
        )


class MiscTests(unittest.TestCase):
    def test_origin_and_site_root(self) -> None:
        self.assertEqual(origin_of(BASE + "lab1/part1.html"), "https://os-labs.p.cs-lab.top")
        self.assertEqual(site_root(BASE + "lab1/part1.html"), BASE)

    def test_url_basename(self) -> None:
        self.assertEqual(url_basename(BASE + "lab1/part1.html"), "part1.html")
        self.assertEqual(url_basename(BASE + "lab1/"), "lab1")

    def test_sha256(self) -> None:
        self.assertEqual(
            sha256_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(2048), "2.0 KB")
        self.assertEqual(format_bytes(5 * 1024 * 1024), "5.0 MB")


if __name__ == "__main__":
    unittest.main()
