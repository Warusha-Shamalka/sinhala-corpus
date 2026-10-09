"""HTML link and candidate metadata extraction (no linked-resource downloads)."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .filters import (
    CandidateDecision,
    classify_candidate,
    resolve_url,
)

@dataclass
class Link:
    href: str
    text: str = ""
    title: str = ""
    before: str = ""
    after: str = ""

    @property
    def context(self) -> str:
        return " ".join(part for part in (self.text, self.title, self.before, self.after) if part)


@dataclass
class ParsedPage:
    title: str
    links: list[Link] = field(default_factory=list)
    text: str = ""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.page_parts: list[str] = []
        self.links: list[Link] = []
        self._ignored_tag: str | None = None
        self._title_depth = 0
        self._active_link: Link | None = None
        self._after_link: Link | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._ignored_tag is not None:
            return
        if tag.lower() in {"script", "style", "template"}:
            self._ignored_tag = tag.lower()
            return
        attributes = dict(attrs)
        if tag.lower() == "title":
            self._title_depth += 1
        if tag.lower() == "a" and attributes.get("href"):
            self._after_link = None
            self._active_link = Link(
                href=str(attributes["href"]),
                title=str(attributes.get("title") or "").strip(),
                before=" ".join(self.page_parts[-6:])[-300:],
            )
            self.links.append(self._active_link)

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tag is not None:
            if tag.lower() == self._ignored_tag:
                self._ignored_tag = None
            return
        if tag.lower() == "title" and self._title_depth:
            self._title_depth -= 1
        if tag.lower() == "a" and self._active_link is not None:
            self._after_link = self._active_link
            self._active_link = None

    def handle_data(self, data: str) -> None:
        if self._ignored_tag is not None:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.page_parts.append(text)
        if self._title_depth:
            self.title_parts.append(text)
        if self._active_link is not None:
            self._active_link.text = f"{self._active_link.text} {text}".strip()
        elif self._after_link is not None and len(self._after_link.after) < 180:
            remaining = 180 - len(self._after_link.after)
            self._after_link.after = f"{self._after_link.after} {text[:remaining]}".strip()


def parse_html(html: str) -> ParsedPage:
    parser = _PageParser()
    parser.feed(html)
    return ParsedPage(" ".join(parser.title_parts).strip(), parser.links, " ".join(parser.page_parts))


def candidate_from_link(
    link: Link,
    page_title: str,
    page_url: str,
    source: dict,
    subjects_config: dict,
) -> dict | None:
    """Build a CSV-shaped candidate only when scored candidate evidence passes."""
    candidate, _ = evaluate_link(link, page_title, page_url, source, subjects_config)
    return candidate


def evaluate_link(
    link: Link,
    page_title: str,
    page_url: str,
    source: dict,
    subjects_config: dict,
) -> tuple[dict | None, CandidateDecision]:
    """Return the optional catalog record and its explainable classifier decision."""
    url = resolve_url(page_url, link.href)
    title = link.text.strip() or link.title.strip()
    if not url:
        return None, CandidateDecision(False, -999, title, rejection_reason="invalid URL")
    filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    filename_title = filename.rsplit(".", 1)[0] if "." in filename else filename
    if not title or title.casefold().strip() in {"view", "download", "open", "read more", "click here", "file"}:
        title = filename_title.replace("_", " ").replace("-", " ").strip()
    metadata = {
        "title": title,
        "anchor_text": link.text.strip(),
        "filename": filename,
        "surrounding_text": " ".join((link.before, link.after)).strip(),
    }
    decision = classify_candidate(url, metadata, subjects_config)
    if not decision.accepted:
        return None, decision
    subject, domain = decision.subject, decision.domain
    grade, education_level = decision.grade, decision.education_level
    candidate = {
        "title": title,
        "subject": subject,
        "domain": domain,
        "grade": grade,
        "education_level": education_level,
        "document_type": decision.document_type,
        "source": str(source.get("name", "")),
        "source_url": url,
        "language": "",  # Source-wide language is only an unverified hint.
        "_language_hint": str(source.get("language", "")),
        "status": "DISCOVERED",
        "_candidate_score": str(decision.score),
        "_candidate_reasons": "; ".join(decision.reasons),
    }
    return candidate, decision
