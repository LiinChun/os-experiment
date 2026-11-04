"""Tests for the manifest state file."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from oslabs_scraper.manifest import Entry, Manifest

import support


def entry(url: str = "https://example.test/a.html", sha: str = "abc") -> Entry:
    return Entry(url=url, sha256=sha, size=10, content_type="text/html", etag='"1"')


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = support.make_temp_dir()
        self.addCleanup(support.remove_temp_dir, self._dir)
        self.path: Path = self._dir / "raw" / "manifest.json"

    def test_roundtrip(self) -> None:
        manifest = Manifest(base_url="https://example.test/")
        manifest.put("index.html", entry())
        self.assertTrue(manifest.save(self.path))

        loaded = Manifest.load(self.path)
        self.assertEqual(loaded.base_url, "https://example.test/")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.get("index.html"), entry())  # type: ignore[arg-type]
        self.assertEqual(loaded.total_bytes, 10)

    def test_save_is_idempotent(self) -> None:
        manifest = Manifest(base_url="https://example.test/")
        manifest.put("index.html", entry())
        self.assertTrue(manifest.save(self.path))
        self.assertFalse(manifest.save(self.path))

    def test_save_detects_changes(self) -> None:
        manifest = Manifest(base_url="https://example.test/")
        manifest.put("index.html", entry())
        manifest.save(self.path)
        manifest.put("index.html", entry(sha="def"))
        self.assertTrue(manifest.save(self.path))

    def test_items_are_sorted_for_stable_diffs(self) -> None:
        manifest = Manifest(base_url="https://example.test/")
        manifest.put("z.html", entry("https://example.test/z.html", "z"))
        manifest.put("a.html", entry("https://example.test/a.html", "a"))
        body = manifest.body()
        self.assertEqual(list(body["items"]), ["a.html", "z.html"])  # type: ignore[index]

    def test_missing_file_loads_empty(self) -> None:
        self.assertEqual(len(Manifest.load(self.path)), 0)

    def test_corrupt_file_loads_empty(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(len(Manifest.load(self.path)), 0)

    def test_removal(self) -> None:
        manifest = Manifest(base_url="https://example.test/")
        manifest.put("a.html", entry())
        self.assertIsNotNone(manifest.remove("a.html"))
        self.assertIsNone(manifest.remove("a.html"))
        self.assertEqual(len(manifest), 0)

    def test_written_file_has_metadata(self) -> None:
        manifest = Manifest(base_url="https://example.test/")
        manifest.put("a.html", entry())
        manifest.save(self.path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertEqual(raw["count"], 1)
        self.assertIn("generated_at", raw)
        self.assertEqual(raw["items"]["a.html"]["sha256"], "abc")

    def test_entry_with_payload(self) -> None:
        updated = entry().with_payload(sha256="new", size=99, content_type="image/png")
        self.assertEqual(updated.sha256, "new")
        self.assertEqual(updated.size, 99)
        self.assertEqual(updated.content_type, "image/png")
        self.assertEqual(updated.url, "https://example.test/a.html")


if __name__ == "__main__":
    unittest.main()
