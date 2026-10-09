"""URL normalization and scored educational-resource classification."""

from __future__ import annotations

import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit


DEFAULT_CANDIDATE_THRESHOLD = 4
DOCUMENT_TYPES = {
    "marking_scheme": ("marking scheme", "marking schemes", "answer scheme", "answer schemes"),
    "past_paper": ("past paper", "past papers", "question paper", "question papers", "model paper", "model papers", "exam paper", "examination paper"),
    "teacher_guide": ("teacher guide", "teacher guides", "teachers guide", "teacher's guide", "teacher's guides", "teacher guidebook", "teacher guide book"),
    "syllabus": ("syllabus", "curriculum", "විෂය නිර්දේශය"),
    "textbook": ("textbook", "text book", "student book", "පෙළපොත"),
    "workbook": ("workbook", "work book", "worksheet", "වැඩපොත"),
    "lesson": ("lesson note", "lesson notes", "lesson", "tutorial", "study note", "study notes", "notes", "පාඩම්", "සටහන්"),
    "article": ("educational article", "article"),
}
POSITIVE_TERMS = (
    "textbook", "text book", "teacher guide", "teacher guides", "teacher's guide", "teacher guidebook",
    "syllabus", "curriculum", "lesson", "notes", "study note", "workbook", "worksheet",
    "past paper", "paper", "question paper", "examination", "exam", "marking scheme",
    "marking", "answer scheme", "model paper", "model answer", "resource", "tutorial", "guide",
    "පෙළපොත", "ගුරු මාර්ගෝපදේශ", "විෂය නිර්දේශය", "පාඩම්", "ප්‍රශ්න පත්‍ර", "පසුගිය ප්‍රශ්න පත්‍ර",
    "සටහන්", "වැඩපොත", "උත්තර පත්‍ර",
)
INFRASTRUCTURE_TERMS = (
    "privacy", "privacy policy", "terms", "terms of use", "sitemap", "login", "log in",
    "register", "registration", "dashboard", "account", "profile",
)
NAVIGATION_TERMS = ("home", "about", "contact")
LISTING_TERMS = ("hub", "category", "categories", "tag", "tags", "search", "listing")
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf")


@dataclass
class CandidateDecision:
    accepted: bool
    score: int
    title: str
    subject: str = ""
    domain: str = ""
    grade: str = ""
    education_level: str = ""
    document_type: str = "other"
    reasons: list[str] = field(default_factory=list)
    rejection_reason: str = ""


def _normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFC", unquote(value)).casefold().replace("\u200d", "").replace("\u200c", "")
    return re.sub(r"[\s_\-]+", " ", value).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalized_text(text)
    normalized_phrase = _normalized_text(phrase)
    return bool(re.search(rf"(?<![\w\u0d80-\u0dff]){re.escape(normalized_phrase)}(?![\w\u0d80-\u0dff])", normalized_text))


def _title_path_segments(url: str, metadata: dict) -> tuple[str, str]:
    parts = urlsplit(url)
    path = re.sub(r"\.[a-z0-9]{1,5}$", " ", parts.path.rsplit("/", 1)[-1], flags=re.IGNORECASE)
    title = str(metadata.get("title") or metadata.get("anchor_text") or "")
    return title, _normalized_text(path.replace("+", " "))


def normalize_url(url: str) -> str:
    """Normalize URL host/path and drop fragments while retaining query strings."""
    if not isinstance(url, str) or any(ord(char) < 32 for char in url):
        return ""
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        hostname = (parts.hostname or "").lower()
        port = parts.port
        if scheme not in {"http", "https"} or not hostname or parts.username is not None or parts.password is not None:
            return ""
        if any(char.isspace() for char in hostname):
            return ""
    except ValueError:
        return ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    trailing_slash = path.endswith("/")
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = f"/{path}"
    if trailing_slash and path != "/":
        path += "/"
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~[]")
    return urlunsplit((scheme, netloc, path, query, ""))


def resolve_url(base_url: str, href: str) -> str:
    """Resolve malformed or unsupported anchors safely before any crawl action."""
    if not isinstance(href, str) or any(ord(char) < 32 for char in href):
        return ""
    try:
        return normalize_url(urljoin(base_url, href))
    except ValueError:
        return ""


def is_within_domain(url: str, base_url: str) -> bool:
    """Return true for HTTP(S) source hosts/subdomains, never lookalikes."""
    candidate = normalize_url(url)
    base = normalize_url(base_url)
    if not candidate or not base:
        return False
    candidate_host = urlsplit(candidate).hostname.rstrip(".")
    source_host = urlsplit(base).hostname.rstrip(".")
    return candidate_host == source_host or candidate_host.endswith(f".{source_host}")


def subject_matches(text: str, subjects_config: dict) -> tuple[str, str]:
    """Prefer contained specific names, while retaining independent ambiguity."""
    normalized = _normalized_text(text)
    matches = []
    for domain, data in subjects_config.get("domains", {}).items():
        for subject in data.get("subjects", []):
            name = subject["name"]
            for alias in (name, *subject.get("aliases", [])):
                phrase = _normalized_text(alias)
                pattern = rf"(?<![\w\u0d80-\u0dff]){re.escape(phrase)}(?![\w\u0d80-\u0dff])"
                for match in re.finditer(pattern, normalized):
                    matches.append((match.start(), match.end(), name, str(domain)))
    specific = [
        item for item in matches
        if not any(other[0] <= item[0] and item[1] <= other[1]
                   and (other[0], other[1]) != (item[0], item[1]) for other in matches)
    ]
    unique = list(dict.fromkeys((name, domain) for _, _, name, domain in specific))
    return unique[0] if len(unique) == 1 else ("", "")


def extract_grade(text: str, subjects_config: dict) -> tuple[str, str]:
    """Extract explicit ranges/grades and compatible levels; conflicts stay unknown."""
    normalized = unicodedata.normalize("NFC", unquote(text)).casefold().replace("\u200d", "").replace("\u200c", "")
    normalized = re.sub(r"[._]+", " ", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    markers = subjects_config.get("grade_markers", {})
    before = markers.get("before_number", ["grade", "grades", "class"])
    after = markers.get("after_number", [])
    # Match the full number first, so grade 15 cannot accidentally become grade 1.
    number = r"(?P<low>\d{1,2})(?:\s*(?:[-–—]|to)\s*(?P<high>\d{1,2}))?(?!\d)"
    ranges = set()
    for labels, prefix in ((before, True), (after, False)):
        if not labels:
            continue
        label = "(?:" + "|".join(re.escape(_normalized_text(x)) for x in labels) + ")"
        pattern = (rf"(?<![\w\u0d80-\u0dff]){label}\s*[-:]?\s*{number}" if prefix
                   else rf"(?<!\d){number}\s*{label}(?![\w\u0d80-\u0dff])")
        for match in re.finditer(pattern, normalized):
            low = int(match["low"])
            high = int(match["high"] or low)
            if not 6 <= low <= high <= 13:
                return "", ""
            ranges.add((low, high))
    levels = subjects_config.get("education_levels", {})
    matched_levels = []
    defaults = {"O-Level": ["o/l", "ordinary level"], "A-Level": ["a/l", "advanced level"]}
    for level, details in levels.items():
        aliases = details.get("aliases", defaults.get(level, []))
        if any(_contains_phrase(normalized, alias) for alias in aliases):
            matched_levels.append((level, details))
    if len(ranges) > 1 or len(matched_levels) > 1:
        return "", ""
    if ranges:
        low, high = next(iter(ranges))
        if matched_levels:
            _, details = matched_levels[0]
            if not details["grade_min"] <= low <= high <= details["grade_max"]:
                return "", ""
        level = next((name for name, details in levels.items()
                      if details["grade_min"] <= low <= high <= details["grade_max"]), "")
        return (str(low) if low == high else f"{low}-{high}"), level
    if matched_levels:
        level, details = matched_levels[0]
        return f'{details["grade_min"]}-{details["grade_max"]}', level
    return "", ""


def detect_document_type(url: str, text: str) -> str:
    """Infer one of the existing controlled document types, else ``other``."""
    combined = _normalized_text(f"{url} {text}")
    for document_type, terms in DOCUMENT_TYPES.items():
        if any(_contains_phrase(combined, term) for term in terms):
            return document_type
    if _contains_phrase(combined, "paper") and re.search(
        r"\b(?:19|20)\d{2}\b|\b(?:grade|class)\s*(?:[6-9]|1[0-3])\b|\b(?:o\s*/\s*l|a\s*/\s*l|ordinary level|advanced level)\b",
        combined,
    ):
        return "past_paper"
    return "other"


def is_educational_candidate(url: str, text: str, subject_names: list[str]) -> bool:
    """Compatibility helper: check for educational signals without scoring."""
    combined = f"{url} {text}".casefold()
    return (
        urlsplit(url).path.casefold().endswith(DOCUMENT_EXTENSIONS)
        or any(term.casefold() in combined for term in POSITIVE_TERMS)
        or any(name.casefold() in combined for name in subject_names if name)
    )


def should_crawl(url: str, metadata: dict | None = None) -> bool:
    """Navigation/listing pages remain crawlable; only non-HTTP and file links do not."""
    normalized = normalize_url(url)
    return bool(normalized) and not is_obvious_file_url(normalized)


def classify_candidate(
    url: str,
    metadata: dict,
    subjects_config: dict,
    threshold: int = DEFAULT_CANDIDATE_THRESHOLD,
) -> CandidateDecision:
    """Score metadata transparently; keep crawls broad and catalog acceptance selective."""
    url = normalize_url(url)
    if not url:
        return CandidateDecision(False, -999, str(metadata.get("title", "")), rejection_reason="invalid URL")
    title, path = _title_path_segments(url, metadata)
    anchor = str(metadata.get("anchor_text", ""))
    filename = str(metadata.get("filename", ""))
    surrounding = str(metadata.get("surrounding_text", ""))
    item_evidence = " ".join((urlsplit(url).path, filename, anchor, title))
    normalized_title = _normalized_text(title)
    normalized_path = _normalized_text(path)
    normalized_evidence = _normalized_text(item_evidence)
    score = 0
    reasons: list[str] = []
    rejection_reason = ""

    is_document_link = urlsplit(url).path.casefold().endswith(DOCUMENT_EXTENSIONS)
    download_hint = any(term in normalized_evidence for term in ("download", "attachment", "file"))
    if is_document_link or (download_hint and any(_contains_phrase(normalized_evidence, term) for term in POSITIVE_TERMS)):
        score += 5
        reasons.append("direct_document_link +5")

    subject, domain = subject_matches(item_evidence, subjects_config)
    if subject:
        score += 3
        reasons.append(f"configured_subject:{subject} +3")

    grade, education_level = extract_grade(item_evidence, subjects_config)
    if grade:
        score += 3
        reasons.append(f"explicit_grade_or_level:{grade} +3")

    matching_terms = [
        term for term in POSITIVE_TERMS
        if any(_contains_phrase(value, term) for value in (urlsplit(url).path, filename, anchor, title))
    ]
    if matching_terms:
        score += 2
        reasons.append(f"educational_keyword:{matching_terms[0]} +2")

    specific_document_terms = (
        "textbook", "text book", "teacher guide", "teacher guides", "teacher's guide", "teacher guidebook",
        "syllabus", "curriculum", "workbook", "worksheet", "past paper", "question paper",
        "marking scheme", "answer scheme", "model paper", "model answer", "lesson note",
        "lesson notes", "study note", "study notes", "examination", "exam", "tutorial",
        "පෙළපොත", "ගුරු මාර්ගෝපදේශ", "විෂය නිර්දේශය", "ප්‍රශ්න පත්‍ර", "පසුගිය ප්‍රශ්න පත්‍ර",
    )
    has_specific_resource = any(
        _contains_phrase(value, term)
        for value in (urlsplit(url).path, filename, anchor, title)
        for term in specific_document_terms
    )
    if has_specific_resource:
        score += 4
        reasons.append("resource_title +4")

    nearby_resource_terms = (
        "textbook", "text book", "teacher guide", "syllabus", "curriculum", "lesson note",
        "workbook", "worksheet", "past paper", "question paper", "marking scheme",
        "answer scheme", "model paper", "model answer", "පෙළපොත", "විෂය නිර්දේශය",
        "ප්‍රශ්න පත්‍ර", "සටහන්",
    )
    if not _contains_phrase(normalized_title, "timetable") and any(
        _contains_phrase(surrounding, term) for term in nearby_resource_terms
    ):
        score += 1
        reasons.append("educational_surrounding_text +1")

    navigation_text = f"{normalized_title} {normalized_path}"
    infrastructure = any(_contains_phrase(navigation_text, term) for term in INFRASTRUCTURE_TERMS)
    navigation = any(
        normalized_title == term or normalized_path == term
        or normalized_path.endswith(f" {term}")
        for term in NAVIGATION_TERMS
    )
    path_segments = {
        _normalized_text(segment)
        for segment in urlsplit(url).path.split("/")
        if segment
    }
    category_route = bool(path_segments & {"category", "categories", "tag", "tags", "search"})
    has_explicit_year = bool(re.search(r"\b(?:19|20)\d{2}\b", item_evidence))
    concrete_resource_identity = has_specific_resource and bool(grade or subject or has_explicit_year)
    listing_route = normalized_path in {"paper", "note", "notes", "marking", "teacher guides", "notesearch"}
    root_landing_page = urlsplit(url).path.rstrip("/") == "" and not has_specific_resource
    listing = (
        any(_contains_phrase(navigation_text, term) for term in LISTING_TERMS)
        or normalized_path in {"paper", "note", "notes", "marking"}
        or normalized_title in {"paper", "note", "notes", "marking"}
        or normalized_path == "teacher guides"
        or normalized_title == "teacher guides"
        or category_route
        or root_landing_page
    )
    if normalized_title == "paper hub":
        score -= 3
        reasons.append("category_or_listing_page -3")
        rejection_reason = "category/listing page"
        listing = True
    if infrastructure:
        score -= 5
        reasons.append("site_infrastructure -5")
        rejection_reason = "site infrastructure"
    elif navigation:
        score -= 4
        reasons.append("navigation_page -4")
        rejection_reason = "navigation"
    elif listing and not rejection_reason:
        score -= 3
        reasons.append("category_or_listing_page -3")
        rejection_reason = "category/listing page"

    # Exact infrastructure/navigation labels cannot become resources by inheriting
    # broad page context; direct files and explicit resource titles can override it.
    strong_resource = is_document_link or (
        concrete_resource_identity and not category_route and not listing_route
    )
    timetable = _contains_phrase(normalized_title, "timetable")
    accepted = (
        score >= threshold
        and not timetable
        and (not (infrastructure or navigation or listing) or strong_resource)
    )
    if not accepted and not rejection_reason:
        rejection_reason = "timetable/non-document page" if timetable else "below candidate threshold"
    return CandidateDecision(
        accepted=accepted,
        score=score,
        title=title,
        subject=subject,
        domain=domain,
        grade=grade,
        education_level=education_level,
        document_type=detect_document_type(url, item_evidence),
        reasons=reasons,
        rejection_reason=rejection_reason,
    )


def is_candidate(
    url: str,
    metadata: dict,
    subjects_config: dict,
    threshold: int = DEFAULT_CANDIDATE_THRESHOLD,
) -> bool:
    """Boolean convenience API corresponding to :func:`classify_candidate`."""
    return classify_candidate(url, metadata, subjects_config, threshold).accepted


def is_obvious_file_url(url: str) -> bool:
    """Avoid fetching likely documents, images, archives, or media as HTML pages."""
    path = urlsplit(url).path.casefold()
    return path.endswith((
        *DOCUMENT_EXTENSIONS,
        ".zip", ".rar", ".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mp3",
    ))
