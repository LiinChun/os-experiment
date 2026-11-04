"""A tiny, tolerant HTML DOM built on :mod:`html.parser`.

The scraper only needs a few things from the markup: the navigation tree, the
``<a href>`` links of a page and the ``src``/``href`` references of its assets.
A full HTML5 parser (lxml, bs4) would be overkill and an extra dependency, so
this module implements the smallest DOM that can answer those questions while
tolerating the unclosed tags that show up in real pages.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator, Sequence

VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

_WHITESPACE = re.compile(r"\s+")

#: Opening these tags implicitly closes a still-open tag from the value set.
#: Pages served by mkdocs are well formed, but tolerating the classic HTML
#: shorthands (``<li>a<li>b``) keeps the parser useful for arbitrary markup.
IMPLIED_CLOSE: dict[str, frozenset[str]] = {
    "li": frozenset({"li"}),
    "p": frozenset({"p"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "tr": frozenset({"tr", "td", "th"}),
    "option": frozenset({"option"}),
    "thead": frozenset({"tbody", "thead", "tfoot"}),
    "tbody": frozenset({"tbody", "thead", "tfoot"}),
    "tfoot": frozenset({"tbody", "thead", "tfoot"}),
}


class Node:
    """One element in the document tree.

    Children are either :class:`Node` instances or ``str`` text nodes.
    """

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(
        self,
        tag: str,
        attrs: Sequence[tuple[str, str | None]] | dict[str, str] | None = None,
        parent: "Node | None" = None,
    ) -> None:
        self.tag = tag
        self.attrs: dict[str, str] = dict(attrs or {})  # type: ignore[arg-type]
        self.children: list[Node | str] = []
        self.parent = parent

    # -- attributes -------------------------------------------------------- #
    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> set[str]:
        return set(self.get("class").split())

    def has_class(self, name: str) -> bool:
        return name in self.classes

    # -- tree -------------------------------------------------------------- #
    def element_children(self) -> list["Node"]:
        return [child for child in self.children if isinstance(child, Node)]

    def append(self, child: "Node | str") -> None:
        if isinstance(child, Node):
            child.parent = self
        self.children.append(child)

    def iter(self) -> Iterator["Node"]:
        """Depth-first iteration over this node and all descendants."""
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.iter()

    def find(self, tag: str | None = None, cls: str | None = None) -> "Node | None":
        for node in self.iter():
            if _matches(node, tag, cls):
                return node
        return None

    def find_all(
        self,
        tag: str | None = None,
        cls: str | None = None,
        limit: int | None = None,
    ) -> list["Node"]:
        found: list[Node] = []
        for node in self.iter():
            if node is self:
                continue
            if _matches(node, tag, cls):
                found.append(node)
                if limit is not None and len(found) >= limit:
                    break
        return found

    def find_shallow(
        self,
        tag: str | None = None,
        cls: str | None = None,
        stop_tags: Sequence[str] = ("nav",),
    ) -> "Node | None":
        """Find the first match without descending into *stop_tags* subtrees."""
        stack: list[Node] = [self]
        while stack:
            node = stack.pop(0)
            if node is not self and _matches(node, tag, cls):
                return node
            if node is not self and node.tag in stop_tags:
                continue
            stack.extend(node.element_children())
        return None

    # -- text -------------------------------------------------------------- #
    def text(self) -> str:
        """Concatenated text of the subtree, entities already decoded."""
        parts: list[str] = []
        stack: list[Node | str] = [self]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                parts.append(item)
            else:
                stack.extend(reversed(item.children))
        return "".join(parts)

    def clean_text(self) -> str:
        """Text of the subtree with runs of whitespace collapsed."""
        return _WHITESPACE.sub(" ", self.text()).strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        attrs = "".join(f' {key}="{value}"' for key, value in self.attrs.items())
        return f"<{self.tag}{attrs}>"


def _matches(node: Node, tag: str | None, cls: str | None) -> bool:
    if tag is not None and node.tag != tag:
        return False
    if cls is not None and not node.has_class(cls):
        return False
    return True


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._stack: list[Node] = [self.root]

    # -- parser hooks ------------------------------------------------------ #
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._imply_close(tag)
        node = Node(tag, [(key, value or "") for key, value in attrs], self._stack[-1])
        self._stack[-1].append(node)
        if tag not in VOID_ELEMENTS:
            self._stack.append(node)

    def _imply_close(self, tag: str) -> None:
        closable = IMPLIED_CLOSE.get(tag)
        if not closable:
            return
        while len(self._stack) > 1 and self._stack[-1].tag in closable:
            self._stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, [(key, value or "") for key, value in attrs], self._stack[-1])
        self._stack[-1].append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].append(data)


def parse(html: str) -> Node:
    """Parse *html* and return the document root node."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def walk_with_depth(root: Node, tag: str | None = None, cls: str | None = None) -> Iterator[tuple[Node, int]]:
    """Yield ``(node, depth)`` pairs depth-first.

    The document root itself is not counted, so the first element below it has
    depth ``0``.
    """
    stack: list[tuple[Node, int]] = [
        (child, 0) for child in reversed(root.element_children())
    ]
    while stack:
        node, depth = stack.pop()
        if _matches(node, tag, cls):
            yield node, depth
        for child in reversed(node.element_children()):
            stack.append((child, depth + 1))
