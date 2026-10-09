"""Polite, bounded discovery crawler. It fetches HTML pages only, never resources."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import math
import logging
import os
import re
import tempfile
import time
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from uuid import uuid4
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

import yaml  # type: ignore[import-not-found]

from .filters import (
    should_crawl,
    is_within_domain,
    normalize_url,
    resolve_url,
)
from .parser import Link, evaluate_link, parse_html


ROOT = Path(__file__).resolve().parents[2]
SOURCES_PATH = ROOT / "configs" / "sources.yaml"
SUBJECTS_PATH = ROOT / "configs" / "subjects.yaml"
CATALOG_PATH = ROOT / "corpus" / "catalog" / "documents.csv"
LOG_DIR = ROOT / "corpus" / "logs" / "discovery"
DEFAULT_LIMITS = {
    "max_depth": 3,
    "max_pages_per_source": 100,
    "request_delay_seconds": 1.0,
    "timeout_seconds": 15,
    "max_queue": 1000,
    "max_requests": 250,
    "max_seconds": 300.0,
    "max_retries": 2,
    "max_retry_wait": 30.0,
}
USER_AGENT = "SinhalaMMLUDiscovery/0.1 (+educational corpus discovery; HTML only)"
CATALOG_COLUMNS = (
    "doc_id", "title", "subject", "domain", "grade", "education_level",
    "document_type", "source", "source_url", "publication_year", "exam_year",
    "language", "license", "status", "local_filename", "sha256",
    "extraction_method", "ocr_required", "page_count", "quality_score",
    "pipeline_version", "last_processed", "error",
)
DOC_ID_PATTERN = re.compile(r"^LK-EDU-(\d{6,})$")
PILOTS_PATH = ROOT / "corpus" / "catalog" / "pilots.json"
CATALOG_STATUSES = {
    "DISCOVERED", "DOWNLOADED", "EXTRACTED", "CLEANED", "DEDUPLICATED", "VALIDATED", "READY",
    "DOWNLOAD_FAILED", "EXTRACTION_FAILED", "OCR_FAILED", "QUALITY_FAILED", "DUPLICATE",
}
DOCUMENT_TYPES = {"textbook", "teacher_guide", "syllabus", "past_paper", "marking_scheme",
                  "lesson", "article", "workbook", "other"}
ARTIFACT_STATUSES = {"DOWNLOADED", "EXTRACTED", "CLEANED", "DEDUPLICATED", "VALIDATED", "READY"}



class CatalogError(Exception):
    """Raised when the catalog cannot safely be read or written."""


class _DomainRedirectHandler(HTTPRedirectHandler):
    """Reject redirects to hosts outside the configured source domain."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = resolve_url(req.full_url, newurl)
        if not target or not is_within_domain(target, self.base_url):
            raise HTTPError(req.full_url, code, "redirect outside configured source domain", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def load_configuration() -> tuple[list[dict], dict]:
    for path in (SOURCES_PATH, SUBJECTS_PATH, CATALOG_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"Required project file does not exist: {path}")
    with SOURCES_PATH.open(encoding="utf-8") as stream:
        sources_data = yaml.safe_load(stream) or {}
    with SUBJECTS_PATH.open(encoding="utf-8") as stream:
        subjects_config = yaml.safe_load(stream) or {}
    if not isinstance(sources_data, dict) or not isinstance(subjects_config, dict):
        raise ValueError("Source and subject configurations must be mappings")
    sources = sources_data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("configs/sources.yaml must contain a 'sources' list")
    if not isinstance(subjects_config.get("domains"), dict):
        raise ValueError("configs/subjects.yaml must contain a 'domains' mapping")
    ids = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not source["id"]:
            raise ValueError("Every source requires a nonempty string id")
        if source["id"] in ids:
            raise ValueError(f"Duplicate source id: {source['id']}")
        ids.add(source["id"])
        for flag in ("enabled", "verified"):
            if type(source.get(flag)) is not bool:
                raise ValueError(f"Source {source['id']} requires boolean {flag}")
        base_url = source.get("base_url", "")
        if not isinstance(base_url, str) or (base_url and not normalize_url(base_url)) or (
            source["enabled"] and source["verified"] and not base_url
        ):
            raise ValueError(f"Source {source['id']} requires a valid HTTP(S) base_url")
    for domain, details in subjects_config["domains"].items():
        if not isinstance(details, dict) or not isinstance(details.get("subjects"), list):
            raise ValueError(f"Domain {domain} requires a subjects list")
        for subject in details["subjects"]:
            if not isinstance(subject, dict) or not isinstance(subject.get("name"), str) or not subject["name"]:
                raise ValueError(f"Domain {domain} contains an invalid subject")
            _validate_aliases(subject.get("aliases", []), f"subject {subject['name']}")
            _validate_range(subject, f"subject {subject['name']}")
    levels = subjects_config.get("education_levels")
    if not isinstance(levels, dict):
        raise ValueError("education_levels must be a mapping")
    for level, details in levels.items():
        if not isinstance(details, dict):
            raise ValueError(f"Invalid education level: {level}")
        _validate_range(details, f"level {level}")
        _validate_aliases(details.get("aliases", []), f"level {level}")
    markers = subjects_config.get("grade_markers", {})
    if not isinstance(markers, dict):
        raise ValueError("grade_markers must be a mapping")
    for position, values in markers.items():
        if position not in {"before_number", "after_number"}:
            raise ValueError(f"Unknown grade marker position: {position}")
        _validate_aliases(values, f"grade markers {position}")
    return sources, subjects_config


def _validate_aliases(values: object, context: str) -> None:
    if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{context} aliases/markers must be a list of nonempty strings")


def _validate_range(details: dict, context: str) -> None:
    low, high = details.get("grade_min"), details.get("grade_max")
    if type(low) is not int or type(high) is not int or not 1 <= low <= high <= 13:
        raise ValueError(f"Invalid grade range for {context}")


def _pilot_titles() -> dict[str, str]:
    try:
        data = json.loads(PILOTS_PATH.read_text(encoding="utf-8"))
        if data.get("schema_version") != "pilot-annotations-1" or not isinstance(data.get("pilots"), list):
            raise ValueError("invalid schema")
        titles = {}
        for item in data["pilots"]:
            doc_id, title = item["doc_id"], item["title"]
            if not isinstance(doc_id, str) or not DOC_ID_PATTERN.fullmatch(doc_id) or not isinstance(title, str) or not title.strip() or doc_id in titles:
                raise ValueError("invalid or duplicate pilot annotation")
            titles[doc_id] = title
        return titles
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CatalogError(f"Could not read pilot annotations: {exc}") from exc


def _validate_rows(records: list[dict[str, str]], *, allow_pilots: bool) -> None:
    pilots = _pilot_titles() if allow_pilots else {}
    ids, urls = set(), set()
    for index, row in enumerate(records, start=2):
        def reject(reason: str) -> None:
            raise CatalogError(f"Catalog row {index}: {reason}")

        if any(not isinstance(value, str) for value in row.values()):
            reject("missing or extra CSV fields")
        doc_id = row.get("doc_id", "")
        if not DOC_ID_PATTERN.fullmatch(doc_id) or int(doc_id.rsplit("-", 1)[1]) < 1:
            reject("invalid doc_id")
        if doc_id in ids:
            reject(f"duplicate doc_id {doc_id}")
        ids.add(doc_id)
        if not row.get("title", "").strip():
            reject("title is required")
        status = row.get("status", "")
        if status not in CATALOG_STATUSES:
            reject(f"unknown status {status!r}")
        if row.get("document_type", "") not in DOCUMENT_TYPES:
            reject("unknown document_type")
        raw_url = row.get("source_url", "")
        url = normalize_url(raw_url)
        is_pilot = status == "DISCOVERED" and pilots.get(doc_id) == row["title"]
        if raw_url and not url:
            reject("source_url must be a valid HTTP(S) URL")
        if not is_pilot and (not url or not row.get("source", "").strip()):
            reject("source and source_url are required outside annotated pilots")
        if url:
            if url in urls:
                reject("duplicate normalized source_url")
            urls.add(url)
        sha = row.get("sha256", "")
        if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
            reject("sha256 must be 64 lowercase hexadecimal characters")
        if status in ARTIFACT_STATUSES and (not sha or not row.get("local_filename", "")):
            reject("processed states require raw artifact path and sha256")
        for field in ("publication_year", "exam_year", "page_count"):
            value = row.get(field, "")
            if value and (not value.isascii() or not value.isdigit() or int(value) < 1):
                reject(f"{field} must be a positive integer or empty")
        grade = row.get("grade", "")
        if grade:
            match = re.fullmatch(r"([1-9]|1[0-3])(?:-([1-9]|1[0-3]))?", grade)
            if not match or int(match[1]) > int(match[2] or match[1]):
                reject("grade must be a valid grade or ascending range")
        value = row.get("quality_score", "")
        if value:
            try:
                if not math.isfinite(float(value)):
                    reject("quality_score must be finite")
            except ValueError:
                reject("quality_score must be numeric or empty")
        if row.get("ocr_required", "") not in {"", "true", "false"}:
            reject("ocr_required must be empty, true or false")


def _read_catalog(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames
            if header is None or len(set(header)) != len(header) or not set(CATALOG_COLUMNS).issubset(header):
                raise CatalogError("documents.csv has duplicate or missing expected columns")
            records = list(reader)
        _validate_rows(records, allow_pilots=True)
        return header, records
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CatalogError(f"Could not safely read documents.csv: {exc}") from exc


def read_catalog(path: Path = CATALOG_PATH) -> list[dict[str, str]]:
    return _read_catalog(path)[1]


def catalog_url_set(records: list[dict[str, str]]) -> set[str]:
    return {normalized for row in records if (normalized := normalize_url(row.get("source_url", "")))}


def next_document_number(records: list[dict[str, str]]) -> int:
    numbers = [
        int(match.group(1))
        for row in records
        if (match := DOC_ID_PATTERN.fullmatch(row.get("doc_id", "")))
    ]
    return max(numbers, default=0) + 1


def make_doc_id(number: int) -> str:
    return f"LK-EDU-{number:06d}"


def assign_ids(candidates: list[dict[str, str]], existing: list[dict[str, str]]) -> list[dict[str, str]]:
    number = next_document_number(existing)
    output = []
    for candidate in candidates:
        row = {column: "" for column in CATALOG_COLUMNS}
        row.update(candidate)
        row["doc_id"] = make_doc_id(number)
        row["status"] = "DISCOVERED"
        output.append(row)
        number += 1
    return output


@contextmanager
def _catalog_lock(path: Path, timeout: float):
    """Lock a stable sidecar inode; replacing the CSV must not replace its lock."""
    if not math.isfinite(timeout) or timeout < 0:
        raise CatalogError("Catalog lock timeout must be finite and nonnegative")
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CatalogError(f"Timed out waiting for catalog lock: {lock_path}")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_catalog(path: Path, new_records: list[dict[str, str]], *, lock_timeout: float = 10.0) -> list[dict[str, str]]:
    """Commit discovery candidates under a lock and return only committed rows.

    Incoming IDs are previews only. Allocate real IDs from the locked snapshot.
    Existing metadata and extension columns are preserved; duplicates are skipped.
    """
    path = path.resolve()
    with _catalog_lock(path, lock_timeout):
        header, existing = _read_catalog(path)
        urls = catalog_url_set(existing)
        candidates = []
        allowed_fields = set(header) | {"_candidate_score", "_candidate_reasons", "_language_hint"}
        for candidate in new_records:
            if not isinstance(candidate, dict) or set(candidate) - allowed_fields:
                raise CatalogError("Discovery candidate has unknown fields")
            if any(not isinstance(value, str) for value in candidate.values()):
                raise CatalogError("Discovery candidate values must be strings")
            if candidate.get("status", "DISCOVERED") != "DISCOVERED":
                raise CatalogError("Only DISCOVERED candidates can be appended")
            url = normalize_url(candidate.get("source_url", ""))
            if not url or not candidate.get("source", "").strip() or not candidate.get("title", "").strip():
                raise CatalogError("Discovery candidates require title, source and valid HTTP(S) source_url")
            if url in urls:
                continue
            urls.add(url)
            row = {key: value for key, value in candidate.items() if key in header}
            row["source_url"] = url
            candidates.append(row)
        rows = assign_ids(candidates, existing)
        _validate_rows(rows, allow_pilots=False)
        if not rows:
            return []
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=header)
                writer.writeheader()
                writer.writerows(existing)
                writer.writerows(rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return rows


def create_logger() -> tuple[logging.Logger, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    log_path = LOG_DIR / f"discovery_{timestamp}_{os.getpid()}.log"
    logger = logging.getLogger(f"sinhala_discovery.{os.getpid()}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, log_path


@dataclass(frozen=True)
class FetchedPage:
    html: str
    final_url: str


class PoliteFetcher:
    """Bounded HTTP requests and conservative, cached robots policy."""

    def __init__(self, delay: float, timeout: float, logger: logging.Logger, *,
                 max_requests: int = 250, max_seconds: float = 300,
                 max_retries: int = 2, max_retry_wait: float = 30,
                 user_agent: str = USER_AGENT, allowed_hosts: set[str] | None = None) -> None:
        self.delay, self.timeout, self.logger = delay, timeout, logger
        self.last_request = 0.0
        self.robots: dict[str, RobotFileParser] = {}
        self.robots_outcomes: dict[str, str] = {}
        self.error_count = 0
        self.request_count = 0
        self.retry_count = 0
        self.truncated_count = 0
        self.max_requests, self.max_retries = max_requests, max_retries
        self.max_retry_wait = max_retry_wait
        self.deadline = time.monotonic() + max_seconds
        self.budget_reason = ""
        self.last_failure = ""
        self.last_http_status = None
        self.user_agent = user_agent
        self.allowed_hosts = allowed_hosts

    def _remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.budget_reason = "time_limit"
        return remaining

    def _wait(self, minimum: float = 0) -> bool:
        wait = max(minimum, self.delay - (time.monotonic() - self.last_request), 0)
        if self._remaining() <= wait:
            self.budget_reason = "time_limit"
            return False
        if wait:
            time.sleep(wait)
        return True

    def _charge_request(self) -> bool:
        if self._remaining() <= 0:
            return False
        if self.request_count >= self.max_requests:
            self.budget_reason = "request_limit"
            return False
        self.request_count += 1
        return True

    def _retry_after(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            if value.strip().isdigit():
                return float(value.strip())
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None

    def _request(self, url: str, base_url: str, method: str = "GET", *, check_redirect_robots: bool = False):
        self.last_failure, self.last_http_status = "", None
        owner = self

        class BoundedRedirectHandler(_DomainRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
                if owner.allowed_hosts is not None and urlsplit(redirected.full_url).hostname not in owner.allowed_hosts:
                    raise HTTPError(req.full_url, code, "redirect outside allowed resource hosts", headers, fp)
                if check_redirect_robots and not owner.robots_allowed(redirected.full_url):
                    raise HTTPError(req.full_url, code, "redirect forbidden by robots policy", headers, fp)
                if not owner._wait() or not owner._charge_request():
                    raise HTTPError(req.full_url, code, "redirect budget exhausted", headers, fp)
                owner.last_request = time.monotonic()
                return redirected

        for attempt in range(self.max_retries + 1):
            if not self._wait() or not self._charge_request():
                self.last_failure = self.budget_reason
                return None
            request = Request(url, headers={"User-Agent": self.user_agent}, method=method)
            self.last_request = time.monotonic()
            try:
                response = build_opener(BoundedRedirectHandler(base_url)).open(
                    request, timeout=min(self.timeout, self._remaining()))
                self.last_failure, self.last_http_status = "", None
                return response
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                self.error_count += 1
                status = exc.code if isinstance(exc, HTTPError) else None
                self.last_http_status = status
                self.last_failure = f"http_{status}" if status else "network_error"
                retry_after = self._retry_after(exc.headers.get("Retry-After")) if isinstance(exc, HTTPError) and exc.headers else None
                if isinstance(exc, HTTPError):
                    exc.close()
                self.logger.warning("Request failed (%s) %s: %s", method, url, exc)
                transient = status in {429, 500, 502, 503, 504} or status is None
                if self.budget_reason or not transient or attempt == self.max_retries:
                    return None
                wait = max(2 ** attempt, retry_after or 0)
                if wait > self.max_retry_wait:
                    self.last_failure = "retry_deferred"
                    self.logger.warning("Retry deferred: server wait exceeds retry-wait budget for %s", url)
                    return None
                if not self._wait(wait):
                    self.last_failure = self.budget_reason
                    return None
                self.retry_count += 1
        return None

    def _read_bounded(self, response, maximum: int) -> bytes | None:
        chunks = []
        size = 0
        read = getattr(response, "read1", response.read)
        while size <= maximum:
            if self._remaining() <= 0:
                self.last_failure = "time_limit"
                return None
            chunk = read(min(65536, maximum + 1 - size))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
        self.truncated_count += 1
        self.last_failure = "truncated_response"
        self.logger.warning("Rejected response exceeding %d bytes", maximum)
        return None

    def robots_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robots_url = f"{origin}/robots.txt"
            response = self._request(robots_url, url)
            parser = RobotFileParser(robots_url)
            outcome = "unavailable"
            lines = ["User-agent: *", "Disallow: /"]
            if response is None:
                if self.last_http_status in {404, 410}:
                    outcome, lines = "absent", ["User-agent: *", "Disallow:"]
                elif self.last_http_status in {401, 403}:
                    outcome = "forbidden"
            else:
                try:
                    final_url = normalize_url(response.geturl())
                    if not is_within_domain(final_url, url):
                        raise ValueError("robots redirect outside source domain")
                    if response.headers.get_content_type() != "text/plain":
                        raise ValueError("robots policy is not plain text")
                    content = self._read_bounded(response, 512_000)
                    if content is not None:
                        lines, outcome = content.decode("utf-8-sig").splitlines(), "available"
                except (OSError, ValueError, UnicodeError) as exc:
                    self.error_count += 1
                    self.logger.warning("Cannot read robots policy for %s: %s", origin, exc)
                finally:
                    response.close()
            parser.parse(lines)
            self.robots[origin] = parser
            self.robots_outcomes[origin] = outcome
            crawl_delay = parser.crawl_delay(self.user_agent)
            request_rate = parser.request_rate(self.user_agent)
            self.delay = max(self.delay, crawl_delay or 0,
                             request_rate.seconds / request_rate.requests if request_rate and request_rate.requests else 0)
            self.logger.info("Robots policy %s: %s", origin, outcome)
        return self.robots[origin].can_fetch(self.user_agent, url)

    def open_resource(self, url: str, base_url: str):
        """Open an approved resource with robots checks before every redirect GET.

        Caller owns response closure and streaming/type validation. Discovery
        continues to use fetch_html and never calls this resource API.
        """
        if not is_within_domain(url, base_url) or (
            self.allowed_hosts is not None and urlsplit(url).hostname not in self.allowed_hosts
        ):
            self.last_failure = "unapproved_resource_host"
            return None
        if not self.robots_allowed(url):
            self.last_failure = "robots_blocked"
            return None
        return self._request(url, base_url, check_redirect_robots=True)

    def fetch_html(self, url: str, base_url: str) -> FetchedPage | None:
        response = self._request(url, base_url)
        if response is None:
            return None
        try:
            final_url = normalize_url(response.geturl())
            if not final_url or not is_within_domain(final_url, base_url):
                self.last_failure = "external_redirect"
                self.error_count += 1
                return None
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                self.last_failure = "non_html"
                self.logger.info("Skipped non-HTML response (%s): %s", content_type, url)
                return None
            content = self._read_bounded(response, 2_000_000)
            if content is None:
                return None
            charset = response.headers.get_content_charset() or "utf-8"
            return FetchedPage(content.decode(charset), final_url)
        except (OSError, LookupError, UnicodeError, ValueError) as exc:
            self.error_count += 1
            self.last_failure = "page_read_error"
            self.logger.warning("Could not read HTML page %s: %s", url, exc)
            return None
        finally:
            response.close()


def discover_source(
    source: dict,
    subjects_config: dict,
    limits: dict,
    logger: logging.Logger,
    decision_sink=None,
) -> tuple[list[dict[str, str]], dict]:
    stats: dict = {
        "pages_visited": 0, "pages_skipped": 0, "candidates_discovered": 0, "errors": 0,
        "navigation_pages_excluded": 0, "listing_pages_excluded": 0,
        "rejected_samples": [], "pages_succeeded": 0, "pages_failed": 0,
        "queue_dropped": 0, "queue_peak": 1, "stop_reason": "", "outcome": "skipped",
    }
    limits = {**DEFAULT_LIMITS, **limits}
    _validate_limits(limits)
    source_started = time.monotonic()
    base_url = normalize_url(str(source.get("base_url", "")))
    if not base_url:
        logger.warning("Source %s has no valid base_url; skipped", source.get("id", ""))
        stats["pages_skipped"] += 1
        return [], stats
    fetcher = PoliteFetcher(limits["request_delay_seconds"], limits["timeout_seconds"], logger,
                            max_requests=limits["max_requests"], max_seconds=limits["max_seconds"],
                            max_retries=limits["max_retries"], max_retry_wait=limits["max_retry_wait"])
    queue = deque([(base_url, 0)])
    scheduled = {base_url}
    visited: set[str] = set()
    candidate_by_url: dict[str, dict[str, str]] = {}
    rejected_by_url: dict[str, tuple[str, int, str]] = {}

    def process_link(link: Link, page_title: str, page_url: str) -> None:
        candidate, decision = evaluate_link(link, page_title, page_url, source, subjects_config)
        candidate_url = resolve_url(page_url, link.href)
        in_domain = bool(candidate_url) and is_within_domain(candidate_url, base_url)
        if decision_sink is not None:
            decision_sink({
                "schema_version": "discovery-decision-1", "rule_version": "discovery-0.3",
                "source_id": source["id"], "referring_url": page_url, "candidate_url": candidate_url,
                "href": link.href,
                "title": decision.title, "accepted": bool(candidate and in_domain),
                "score": decision.score, "reasons": decision.reasons,
                "rejection_reason": (decision.rejection_reason if in_domain else "invalid or external URL"),
                "subject": decision.subject, "grade": decision.grade, "document_type": decision.document_type,
                "evidence": {"anchor": link.text, "title": link.title, "before": link.before, "after": link.after,
                             "resource_context": link.resource_context, "context_kind": link.context_kind},
                "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            })
        if candidate and in_domain:
            candidate_by_url.setdefault(candidate["source_url"], candidate)
        elif candidate_url and is_within_domain(candidate_url, base_url):
            rejected_by_url.setdefault(
                candidate_url,
                (decision.title or candidate_url, decision.score, decision.rejection_reason),
            )

    while queue and stats["pages_visited"] < limits["max_pages_per_source"]:
        if time.monotonic() - source_started >= limits["max_seconds"]:
            stats["stop_reason"] = "time_limit"
            break
        if getattr(fetcher, "budget_reason", ""):
            stats["stop_reason"] = fetcher.budget_reason
            break
        page_url, depth = queue.popleft()
        page_url = normalize_url(page_url)
        if not page_url or page_url in visited:
            continue
        if not is_within_domain(page_url, base_url):
            stats["pages_skipped"] += 1
            continue
        visited.add(page_url)
        if not fetcher.robots_allowed(page_url):
            logger.info("Robots-disallowed page skipped: %s", page_url)
            stats["pages_skipped"] += 1
            continue
        stats["pages_visited"] += 1
        fetched = fetcher.fetch_html(page_url, base_url)
        if fetched is None:
            stats["pages_skipped"] += 1
            if getattr(fetcher, "last_failure", "") != "non_html":
                stats["pages_failed"] += 1
            continue
        stats["pages_succeeded"] += 1
        final_url = fetched.final_url
        if final_url != page_url and final_url in visited:
            continue
        visited.add(final_url)
        page_url = final_url
        page = parse_html(fetched.html)
        process_link(Link(href=page_url, text=page.title), page.title, page_url)
        for link in page.links:
            if time.monotonic() - source_started >= limits["max_seconds"]:
                stats["stop_reason"] = "time_limit"
                break
            process_link(link, page.title, page_url)
            target = resolve_url(page_url, link.href)
            if not target or not is_within_domain(target, base_url) or target in visited or target in scheduled:
                continue
            if depth >= limits["max_depth"] or not should_crawl(target):
                continue
            if len(queue) >= limits["max_queue"]:
                stats["queue_dropped"] += 1
                continue
            queue.append((target, depth + 1))
            scheduled.add(target)
            stats["queue_peak"] = max(stats["queue_peak"], len(queue))
    if queue:
        stats["pages_skipped"] += len(queue)
        stats["stop_reason"] = stats["stop_reason"] or getattr(fetcher, "budget_reason", "") or "page_limit"
        logger.info("Crawl stopped (%s); %d queued pages not visited", stats["stop_reason"], len(queue))
    stats["errors"] = fetcher.error_count
    stats["requests"] = getattr(fetcher, "request_count", 0)
    stats["retries"] = getattr(fetcher, "retry_count", 0)
    stats["truncated_responses"] = getattr(fetcher, "truncated_count", 0)
    stats["robots_outcomes"] = getattr(fetcher, "robots_outcomes", {})
    stats["stop_reason"] = stats["stop_reason"] or getattr(fetcher, "budget_reason", "")
    if stats["queue_dropped"] and not stats["stop_reason"]:
        stats["stop_reason"] = "queue_limit"
    policy_unavailable = any(outcome == "unavailable" for outcome in stats["robots_outcomes"].values())
    if stats["pages_succeeded"]:
        stats["outcome"] = "partial" if stats["pages_failed"] or policy_unavailable or stats["stop_reason"] else "success"
    elif stats["pages_failed"] or policy_unavailable or stats["stop_reason"]:
        stats["outcome"] = "failed"
    else:
        stats["outcome"] = "skipped"
    stats["candidates_discovered"] = len(candidate_by_url)
    stats["navigation_pages_excluded"] = sum(
        1 for _, _, reason in rejected_by_url.values()
        if reason in {"navigation", "site infrastructure"}
    )
    stats["listing_pages_excluded"] = sum(
        1 for _, _, reason in rejected_by_url.values() if reason == "category/listing page"
    )
    stats["rejected_samples"] = [
        {"title": title, "score": score, "reason": reason, "url": url}
        for url, (title, score, reason) in list(rejected_by_url.items())[:20]
    ]
    return list(candidate_by_url.values()), stats


def run(args: argparse.Namespace) -> int:
    logger, log_path = create_logger()
    run_id = log_path.stem
    decisions_path = log_path.with_suffix(".decisions.jsonl")
    summary_path = log_path.with_suffix(".summary.json")
    summary = {"schema_version": "discovery-run-1", "run_id": run_id,
               "dry_run": args.dry_run, "sources": [], "outcome": "failed",
               "started_at_utc": datetime.now(timezone.utc).isoformat()}
    result = 2
    try:
        with decisions_path.open("w", encoding="utf-8") as stream:
            def record(decision):
                stream.write(json.dumps({"run_id": run_id, **decision}, ensure_ascii=False) + "\n")
                stream.flush()
            result = _run(args, logger, log_path, record, summary)
    except (OSError, ValueError, CatalogError) as exc:
        result = 2
        summary["error"] = str(exc)
        logger.error("Discovery run failed: %s", exc)
    if result == 2 and summary["outcome"] in {"success", "partial"}:
        summary["outcome"] = "failed"
    summary.update(exit_code=result, finished_at_utc=datetime.now(timezone.utc).isoformat())
    try:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Run outcome: {summary['outcome']}; exit code: {result}")
        print(f"Decisions: {decisions_path}\nSummary: {summary_path}")
    except OSError as exc:
        logger.error("Could not persist run summary: %s", exc)
        result = 2
    for handler in logger.handlers:
        handler.flush()
    return result


def _run(args, logger, log_path, decision_sink, summary) -> int:
    started = time.monotonic()
    logger.info("Crawl started at %s", datetime.now(timezone.utc).isoformat())
    try:
        sources, subjects_config = load_configuration()
        existing = read_catalog(CATALOG_PATH)
    except (OSError, ValueError, yaml.YAMLError, CatalogError) as exc:
        summary["error"] = str(exc)
        logger.error("Configuration/catalog validation failed: %s", exc)
        return 2

    selected = [source for source in sources if args.source is None or source.get("id") == args.source]
    if args.source and not selected:
        summary["error"] = f"Unknown source id: {args.source}"
        logger.error("Unknown source id: %s", args.source)
        return 2
    enabled_verified = [
        source for source in sources if source.get("enabled") is True and source.get("verified") is True
    ]
    print("Enabled and verified sources:")
    for source in enabled_verified:
        print(f"  {source.get('id')}: {source.get('base_url')}")
    if not enabled_verified:
        print("  (none)")
    limits = {
        "max_depth": args.max_depth,
        "max_pages_per_source": args.max_pages,
        "request_delay_seconds": args.delay,
        "timeout_seconds": args.timeout,
        **{name: getattr(args, name, DEFAULT_LIMITS[name]) for name in
           ("max_queue", "max_requests", "max_seconds", "max_retries", "max_retry_wait")},
    }
    _validate_limits(limits)
    summary["limits"] = limits
    print(f"Crawl limits: {limits}; dry_run={args.dry_run}")
    logger.info("Crawl limits: %s; dry_run=%s", limits, args.dry_run)

    catalog_urls = catalog_url_set(existing)
    new_candidates: dict[str, dict[str, str]] = {}
    run_totals = {
        "pages_visited": 0,
        "pages_skipped": 0,
        "navigation_pages_excluded": 0,
        "listing_pages_excluded": 0,
        "duplicates_skipped": 0,
        "errors": 0,
    }
    run_rejected_samples: list[dict] = []
    for source in selected:
        source_id = source.get("id", "")
        if source.get("enabled") is not True:
            logger.info("Disabled source skipped: %s", source_id)
            summary["sources"].append({"source_id": source_id, "outcome": "skipped", "reason": "disabled"})
            continue
        if source.get("verified") is not True:
            logger.warning("SKIPPED_UNVERIFIED_SOURCE %s", source_id)
            summary["sources"].append({"source_id": source_id, "outcome": "skipped", "reason": "unverified"})
            continue
        if not source.get("base_url"):
            logger.warning("Verified source %s has no base_url; skipped", source_id)
            summary["sources"].append({"source_id": source_id, "outcome": "skipped", "reason": "missing_url"})
            continue
        logger.info("Source started: %s (%s)", source_id, source.get("base_url"))
        candidates, stats = discover_source(source, subjects_config, limits, logger, decision_sink)
        stats.setdefault("outcome", "failed" if stats.get("errors") and not stats.get("pages_visited") else "success")
        if stats["outcome"] == "success" and not candidates:
            stats["outcome"] = "success_empty"
        summary["sources"].append({"source_id": source_id, **stats})
        duplicates_skipped = 0
        for metric in run_totals:
            if metric in stats:
                run_totals[metric] += stats[metric]
        run_rejected_samples.extend(stats.get("rejected_samples", []))
        for key, count in stats.items():
            if key != "rejected_samples":
                logger.info("Source %s %s=%s", source_id, key, count)
        for candidate in candidates:
            url = normalize_url(candidate.get("source_url", ""))
            if not url or url in catalog_urls or url in new_candidates:
                logger.info("Duplicate candidate skipped: %s", url)
                duplicates_skipped += 1
                continue
            new_candidates[url] = candidate
        logger.info("Source %s duplicates_skipped=%d", source_id, duplicates_skipped)
        run_totals["duplicates_skipped"] += duplicates_skipped
        logger.info("Source completed: %s", source_id)

    outcomes = [item["outcome"] for item in summary["sources"]]
    useful = any(outcome in {"success", "success_empty", "partial"} for outcome in outcomes)
    incomplete = any(outcome in {"failed", "partial"} for outcome in outcomes)
    summary["outcome"] = ("partial" if incomplete else "success") if useful else (
        "failed" if "failed" in outcomes else "skipped")
    result = 1 if useful and incomplete else (0 if useful else 2)
    summary["totals"] = run_totals
    rows = assign_ids(list(new_candidates.values()), existing)
    summary["candidates_to_add"] = len(rows)
    if args.dry_run:
        print(f"Pages visited: {run_totals['pages_visited']}")
        print(f"Pages skipped: {run_totals['pages_skipped']}")
        print(f"Candidates: {len(rows)}")
        print(f"Navigation pages excluded from catalog: {run_totals['navigation_pages_excluded']}")
        print(f"Category/listing pages excluded from catalog: {run_totals['listing_pages_excluded']}")
        print(f"Duplicates skipped: {run_totals['duplicates_skipped']}")
        print(f"Errors: {run_totals['errors']}")
        direct_files = sum(
            1 for row in rows
            if urlsplit(row.get("source_url", "")).path.casefold().endswith(
                (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf")
            )
        )
        type_counts = Counter(row.get("document_type", "other") for row in rows)
        print(f"Direct document URLs: {direct_files}; HTML/other URLs: {len(rows) - direct_files}")
        print(f"Candidate document types: {dict(type_counts)}")
        print(f"Dry run: {len(rows)} new candidate(s) would be appended; catalog unchanged.")
        print("Sample candidate decisions:")
        for row in rows[:20]:
            print(
                f"  [ACCEPT] {row['title']} | score={row.get('_candidate_score', '')} "
                f"subject={row.get('subject', '') or '(unknown)'} "
                f"grade={row.get('grade', '') or '(unknown)'} "
                f"type={row.get('document_type', 'other')} | {row['source_url']}"
            )
            print(f"    signals: {row.get('_candidate_reasons', '')}")
        print("Sample excluded navigation/listing decisions:")
        for decision in run_rejected_samples:
            print(f"  [REJECT] {decision['title']} score={decision['score']} reason={decision['reason']} | {decision['url']}")
    elif rows:
        for row in rows:
            row.pop("_candidate_score", None)
            row.pop("_candidate_reasons", None)
            row.pop("_language_hint", None)
        try:
            rows = append_catalog(CATALOG_PATH, rows)
        except (OSError, CatalogError, csv.Error) as exc:
            summary["error"] = str(exc)
            logger.error("Catalog append failed; no successful update reported: %s", exc)
            return 2
        summary["rows_committed"] = len(rows)
        print(f"Appended {len(rows)} candidate(s) to documents.csv.")
    else:
        print("No new candidates to append.")
    elapsed = time.monotonic() - started
    logger.info("Crawl completed: candidates_to_add=%d elapsed_seconds=%.2f", len(rows), elapsed)
    logger.info("Log file: %s", log_path)
    for handler in logger.handlers:
        handler.flush()
    return result


def _validate_limits(limits):
    for name in ("max_pages_per_source", "max_queue", "max_requests"):
        if type(limits[name]) is not int or limits[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    for name in ("max_depth", "max_retries"):
        if type(limits[name]) is not int or limits[name] < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    for name in ("request_delay_seconds", "timeout_seconds", "max_seconds", "max_retry_wait"):
        value = limits[name]
        if not math.isfinite(value) or value < 0 or (name in {"timeout_seconds", "max_seconds"} and value == 0):
            raise ValueError(f"{name} must be finite and within its allowed range")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover educational resources from verified configured sources.")
    parser.add_argument("--source", help="Crawl only this configured source ID")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_LIMITS["max_pages_per_source"])
    parser.add_argument("--max-depth", type=int, default=DEFAULT_LIMITS["max_depth"])
    parser.add_argument("--delay", type=float, default=DEFAULT_LIMITS["request_delay_seconds"])
    parser.add_argument("--timeout", type=float, default=DEFAULT_LIMITS["timeout_seconds"])
    parser.add_argument("--max-queue", type=int, default=DEFAULT_LIMITS["max_queue"])
    parser.add_argument("--max-requests", type=int, default=DEFAULT_LIMITS["max_requests"])
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_LIMITS["max_seconds"])
    parser.add_argument("--max-retries", type=int, default=DEFAULT_LIMITS["max_retries"])
    parser.add_argument("--max-retry-wait", type=float, default=DEFAULT_LIMITS["max_retry_wait"])
    parser.add_argument("--dry-run", action="store_true", help="Discover and preview candidates without modifying the catalog")
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        _validate_limits({"max_pages_per_source": args.max_pages, "max_depth": args.max_depth,
                          "request_delay_seconds": args.delay, "timeout_seconds": args.timeout,
                          **{name: getattr(args, name) for name in
                             ("max_queue", "max_requests", "max_seconds", "max_retries", "max_retry_wait")}})
    except ValueError as exc:
        parser.error(str(exc))
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
