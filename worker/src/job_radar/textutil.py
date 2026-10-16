"""Plain text from ATS HTML, and the normalisation quote checks compare on."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str | None) -> str:
    if not markup:
        return ""
    collector = _TextCollector()
    collector.feed(html.unescape(markup) if "&lt;" in markup else markup)
    text = "".join(collector.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_QUOTE_CHARS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-"})


def normalize(text: str) -> str:
    """Case, whitespace and typographic quotes/dashes do not count as a mismatch."""
    return re.sub(r"\s+", " ", text.translate(_QUOTE_CHARS)).strip().lower()


def quote_in(quote: str, source_normalized: str) -> bool:
    q = normalize(quote).strip(" .\"'")
    return bool(q) and q in source_normalized
