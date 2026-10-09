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

GENERIC_LINK_TEXT = {"view", "download", "open", "read more", "click here", "file", "බාගත කරන්න"}
LOCAL_TEXT_LIMIT = 500
MAX_CONTEXT_DEPTH = 128
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Link:
    href: str
    text: str = ""
    title: str = ""
    before: str = ""
    after: str = ""
    resource_context: str = ""
    context_kind: str = ""

    @property
    def context(self) -> str:
        return " ".join(part for part in (self.text, self.title, self.before, self.after, self.resource_context) if part)


@dataclass
class ParsedPage:
    title: str
    links: list[Link] = field(default_factory=list)
    text: str = ""


@dataclass
class _Frame:
    tag: str
    scoped: bool
    blocked: bool
    parts: list[str] = field(default_factory=list)
    size: int = 0
    overflow: bool = False
    links: list[tuple[Link, bool]] = field(default_factory=list)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.page_parts: list[str] = []
        self.links: list[Link] = []
        self._ignored_tag: str | None = None
        self._title_depth = 0
        self._active_link: Link | None = None
        self._stack: list[_Frame] = []
        self._ignored_depth = 0
        self._context_disabled = False

    def _finish_scope(self, frame: _Frame) -> None:
        if not frame.scoped or frame.blocked or frame.overflow:
            return
        # Multiple destinations cannot safely share one document description.
        if len({link.href.strip() for link, _ in frame.links}) != 1:
            return
        context = " ".join(frame.parts).strip()
        if not context or context.casefold() in GENERIC_LINK_TEXT:
            return
        for link, blocked in frame.links:
            if not blocked and not link.resource_context:
                link.resource_context = context
                link.context_kind = frame.tag

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._ignored_tag is not None:
            if tag == self._ignored_tag:
                self._ignored_depth += 1
            return
        if tag in {"script", "style", "template"}:
            self._ignored_tag = tag
            self._ignored_depth = 1
            return
        attributes = dict(attrs)
        blocked = (any(frame.blocked for frame in self._stack)
                   or tag in {"head", "nav", "header", "footer", "aside"}
                   or str(attributes.get("role") or "").casefold() in {"navigation", "banner", "contentinfo", "complementary"}
                   or "hidden" in attributes or str(attributes.get("aria-hidden") or "").casefold() == "true")
        classes = set(str(attributes.get("class") or "").casefold().split())
        scoped = (tag in {"tr", "li", "article", "dd"}
                  or tag == "div" and bool(classes & {"card", "resource", "resource-card", "document", "material", "item"}))
        if tag not in VOID_TAGS and not self._context_disabled:
            if len(self._stack) >= MAX_CONTEXT_DEPTH:
                # Keep discovering explicit links, but stop structural inference
                # on pathological nesting instead of growing quadratic work.
                self._stack.clear()
                self._context_disabled = True
            else:
                self._stack.append(_Frame(tag, scoped, blocked))
        if tag == "title":
            self._title_depth += 1
        if tag == "a" and attributes.get("href"):
            self._active_link = Link(
                href=str(attributes["href"]),
                title=str(attributes.get("title") or "").strip(),
            )
            self.links.append(self._active_link)
            # A navigation link inside a card still makes that card ambiguous.
            for frame in self._stack:
                if frame.scoped and not frame.overflow:
                    frame.links.append((self._active_link, blocked))

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tag is not None:
            if tag.lower() == self._ignored_tag:
                self._ignored_depth -= 1
                if not self._ignored_depth:
                    self._ignored_tag = None
            return
        if tag.lower() == "title" and self._title_depth:
            self._title_depth -= 1
        if tag.lower() == "a" and self._active_link is not None:
            self._active_link = None
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag.lower():
                frame = self._stack[index]
                if any(child.tag == "a" for child in self._stack[index + 1:]):
                    self._active_link = None
                    frame.overflow = True
                # Abandoned/malformed nested scopes are not promoted as evidence.
                self._finish_scope(frame)
                del self._stack[index:]
                break

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

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
        if any(frame.blocked for frame in self._stack):
            return
        for frame in self._stack:
            if frame.scoped and not frame.blocked and not frame.overflow:
                frame.size += len(text) + bool(frame.parts)
                if frame.size > LOCAL_TEXT_LIMIT:
                    frame.overflow = True
                    frame.parts.clear()
                    frame.links.clear()
                else:
                    frame.parts.append(text)


def parse_html(html: str) -> ParsedPage:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
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
    generic = not title or title.casefold() in GENERIC_LINK_TEXT
    used_local_context = False
    if generic and link.title.strip() and link.title.strip().casefold() not in GENERIC_LINK_TEXT:
        title = link.title.strip()
        generic = False
    if not url:
        return None, CandidateDecision(False, -999, title, rejection_reason="invalid URL")
    filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    filename_title = filename.rsplit(".", 1)[0] if "." in filename else filename
    if generic:
        title = link.resource_context or filename_title.replace("_", " ").replace("-", " ").strip()
        used_local_context = bool(link.resource_context)
    metadata = {
        "title": title,
        "anchor_text": link.text.strip(),
        "filename": filename,
        "surrounding_text": " ".join((link.before, link.after)).strip(),
    }
    if used_local_context:
        original = classify_candidate(url, {**metadata, "title": filename_title}, subjects_config)
        if not original.accepted and original.rejection_reason in {"navigation", "site infrastructure", "category/listing page"}:
            original.reasons.append("resource_local_evidence_not_used_for_navigation")
            return None, original
    decision = classify_candidate(url, metadata, subjects_config)
    if used_local_context:
        decision.reasons.append(f"resource_local_evidence:{link.context_kind}")
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
