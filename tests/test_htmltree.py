"""Tests for the tiny HTML DOM."""

from __future__ import annotations

import unittest

from oslabs_scraper.htmltree import VOID_ELEMENTS, parse, walk_with_depth


class HtmlTreeTests(unittest.TestCase):
    def test_nested_structure_and_classes(self) -> None:
        root = parse('<div class="a b"><p>hi <b>there</b></p></div>')
        div = root.find("div", cls="a")
        self.assertIsNotNone(div)
        assert div is not None
        self.assertEqual(div.classes, {"a", "b"})
        paragraph = div.find("p")
        assert paragraph is not None
        self.assertEqual(paragraph.clean_text(), "hi there")

    def test_void_elements_do_not_nest(self) -> None:
        self.assertIn("img", VOID_ELEMENTS)
        root = parse('<p><img src="a.png"><span>after</span></p>')
        paragraph = root.find("p")
        assert paragraph is not None
        self.assertEqual([child.tag for child in paragraph.element_children()], ["img", "span"])

    def test_unclosed_tags_are_tolerated(self) -> None:
        root = parse("<ul><li>one<li>two</ul><p>tail")
        items = root.find_all("li")
        self.assertEqual([item.clean_text() for item in items], ["one", "two"])
        self.assertEqual(root.find("p").clean_text(), "tail")  # type: ignore[union-attr]

    def test_entities_are_decoded(self) -> None:
        root = parse("<p>a &amp; b &lt;c&gt;</p>")
        self.assertEqual(root.find("p").clean_text(), "a & b <c>")  # type: ignore[union-attr]

    def test_find_shallow_skips_nested_nav(self) -> None:
        html = (
            '<li class="md-nav__item">'
            '<a class="md-nav__link" href="outer.html">outer</a>'
            '<nav><a class="md-nav__link" href="inner.html">inner</a></nav>'
            "</li>"
        )
        root = parse(html)
        li = root.find("li")
        assert li is not None
        anchor = li.find_shallow("a", cls="md-nav__link")
        assert anchor is not None
        self.assertEqual(anchor.get("href"), "outer.html")

    def test_walk_with_depth(self) -> None:
        root = parse("<div><section><p>text</p></section></div>")
        depths = {node.tag: depth for node, depth in walk_with_depth(root, tag="p")}
        self.assertEqual(depths, {"p": 2})

    def test_missing_attribute_returns_default(self) -> None:
        root = parse("<img>")
        img = root.find("img")
        assert img is not None
        self.assertEqual(img.get("src", "none"), "none")


if __name__ == "__main__":
    unittest.main()
