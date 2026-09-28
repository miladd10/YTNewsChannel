"""Fetch a short, readable excerpt of each approved news article.

Google News RSS only provides headlines, so without this step the writer and
claim ledger see nothing but a title. The excerpt is the page's description
plus its opening body paragraphs, capped so prompts stay bounded. Facts in an
excerpt still have to pass the claim ledger before they can be narrated.
"""
from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

EXCERPT_MAX_CHARS = 1800
_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "figure", "figcaption", "svg", "button"}
_BOILERPLATE_RE = re.compile(
    r"(subscribe|sign up|newsletter|cookie|all rights reserved|advertis|click here|read more|"
    r"follow us|share this|terms of (?:use|service)|privacy policy|log ?in|sign in)",
    re.IGNORECASE,
)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.paragraphs: list[str] = []
        self._skip_depth = 0
        self._in_p = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "meta":
            data = {key.lower(): (value or "") for key, value in attrs}
            name = (data.get("property") or data.get("name") or "").lower()
            if name in {"og:description", "description", "twitter:description", "article:published_time"} and data.get("content"):
                self.meta.setdefault(name, data["content"].strip())
        elif tag == "p" and not self._skip_depth:
            self._in_p = True
            self._buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "p" and self._in_p:
            text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
            if text:
                self.paragraphs.append(text)
            self._in_p = False

    def handle_data(self, data):
        if self._in_p and not self._skip_depth:
            self._buffer.append(data)


def extract_article_text(page_html: str, max_chars: int = EXCERPT_MAX_CHARS) -> dict:
    parser = _ArticleParser()
    try:
        parser.feed(page_html or "")
        parser.close()
    except Exception:
        pass
    description = html_lib.unescape(
        parser.meta.get("og:description") or parser.meta.get("description") or parser.meta.get("twitter:description") or ""
    ).strip()
    body: list[str] = []
    seen: set[str] = set()
    total = 0
    for paragraph in parser.paragraphs:
        # Real article sentences: long enough, not site chrome, not repeated.
        if len(paragraph) < 60 or _BOILERPLATE_RE.search(paragraph) and len(paragraph) < 200:
            continue
        key = paragraph.casefold()
        if key in seen or (description and key == description.casefold()):
            continue
        seen.add(key)
        body.append(paragraph)
        total += len(paragraph)
        if total >= max_chars:
            break
    excerpt = "\n".join(body)
    if len(excerpt) > max_chars:
        cut = excerpt[:max_chars]
        excerpt = cut[: cut.rfind(" ")] + " …" if " " in cut else cut
    return {
        "description": description[:500],
        "excerpt": excerpt,
        "published_time": parser.meta.get("article:published_time", ""),
    }
