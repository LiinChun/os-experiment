"""Tests for the mirror integrity check."""

from __future__ import annotations

import json
import unittest

from oslabs_scraper.config import Config
from oslabs_scraper.util import sha256_bytes
from oslabs_scraper.verify import format_result, verify_mirror

import support

BASE = "https://example.test/"


class VerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = support.make_temp_dir()
        self.addCleanup(support.remove_temp_dir, self.root)
        self.out = self.root / "raw"
        self.config = Config(base_url=BASE, out_dir=self.out, index_path=None, delay=0)

    def write(self, rel: str, data: bytes) -> None:
        path = self.out.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_manifest(self, items: dict[str, tuple[str, bytes]]) -> None:
        payload = {
            "version": 1,
            "base_url": BASE,
            "items": {
                rel: {"url": BASE + rel, "sha256": sha256_bytes(data), "size": len(data)}
                for rel, (_ctype, data) in items.items()
            },
        }
        (self.out / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_healthy_mirror(self) -> None:
        html = b'<img src="pic.png"><a href="other.html">x</a>'
        self.write("index.html", html)
        self.write("other.html", b"<p>hi</p>")
        self.write("pic.png", b"png")
        self.write_manifest(
            {
                "index.html": ("text/html", html),
                "other.html": ("text/html", b"<p>hi</p>"),
                "pic.png": ("image/png", b"png"),
            }
        )

        result = verify_mirror(self.config)
        self.assertTrue(result.clean)
        self.assertEqual(result.checked_files, 3)
        self.assertEqual(result.broken_local_refs, {})
        self.assertIn("通过", "\n".join(format_result(result)))

    def test_missing_file_is_reported(self) -> None:
        html = b"<p>a</p>"
        self.write("index.html", html)
        self.write_manifest(
            {"index.html": ("text/html", html), "gone.html": ("text/html", b"<p>b</p>")}
        )

        result = verify_mirror(self.config)
        self.assertFalse(result.healthy)
        self.assertEqual(result.missing_files, ["gone.html"])

    def test_hash_mismatch_is_reported(self) -> None:
        self.write("index.html", b"<p>changed</p>")
        self.write_manifest({"index.html": ("text/html", b"<p>original</p>")})

        result = verify_mirror(self.config)
        self.assertFalse(result.healthy)
        self.assertEqual(result.hash_mismatch, ["index.html"])

    def test_broken_reference_is_deduplicated_per_target(self) -> None:
        html = b'<script src="js/missing.js"></script>'
        self.write("index.html", html)
        self.write("other.html", html)
        self.write_manifest(
            {"index.html": ("text/html", html), "other.html": ("text/html", html)}
        )

        result = verify_mirror(self.config)
        self.assertTrue(result.healthy)
        self.assertFalse(result.clean)
        self.assertEqual(list(result.broken_local_refs), ["js/missing.js"])
        self.assertEqual(len(result.broken_local_refs["js/missing.js"]), 2)

    def test_link_check_can_be_disabled(self) -> None:
        html = b'<script src="js/missing.js"></script>'
        self.write("index.html", html)
        self.write_manifest({"index.html": ("text/html", html)})

        result = verify_mirror(self.config, check_links=False)
        self.assertTrue(result.clean)

    def test_empty_mirror(self) -> None:
        result = verify_mirror(self.config)
        self.assertTrue(result.clean)
        self.assertEqual(result.checked_files, 0)


if __name__ == "__main__":
    unittest.main()
