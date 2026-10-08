"""Polite, bounded discovery crawler. It fetches HTML pages only, never resources."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import tempfile
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

import yaml  # type: ignore[import-not-found]

from .filters import (
    should_crawl,
    is_within_domain,
    normalize_url,
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
}
USER_AGENT = "SinhalaMMLUDiscovery/0.1 (+educational corpus discovery; HTML only)"
CATALOG_COLUMNS = (
    "doc_id", "title", "subject", "domain", "grade", "education_level",
    "document_type", "source", "source_url", "publication_year", "exam_year",
    "language", "license", "status", "local_filename", "sha256",
    "extraction_method", "ocr_required", "page_count", "quality_score",
    "pipeline_version", "last_processed", "error",
)
DOC_ID_PATTERN = re.compile(r"^LK-EDU-(\d+)$")


class CatalogError(Exception):
    """Raised when the catalog cannot safely be read or written."""


class _DomainRedirectHandler(HTTPRedirectHandler):
    """Reject redirects to hosts outside the configured source domain."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = normalize_url(urljoin(req.full_url, newurl))
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
    sources = sources_data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("configs/sources.yaml must contain a 'sources' list")
    if not isinstance(subjects_config.get("domains"), dict):
        raise ValueError("configs/subjects.yaml must contain a 'domains' mapping")
    return sources, subjects_config


def read_catalog(path: Path = CATALOG_PATH) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not set(CATALOG_COLUMNS).issubset(reader.fieldnames):
                raise CatalogError("documents.csv is missing one or more expected columns")
            return [dict(row) for row in reader]
    except (OSError, csv.Error) as exc:
        raise CatalogError(f"Could not safely read documents.csv: {exc}") from exc


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


def append_catalog(path: Path, new_records: list[dict[str, str]]) -> None:
    """Atomically append records after validating and preserving the schema/data."""
    existing = read_catalog(path)
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        header = next(csv.reader(stream), None)
    if header is None or not set(CATALOG_COLUMNS).issubset(header):
        raise CatalogError("documents.csv header changed before append")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing)
            writer.writerows(new_records)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def create_logger() -> tuple[logging.Logger, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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


class PoliteFetcher:
    def __init__(self, delay: float, timeout: float, logger: logging.Logger) -> None:
        self.delay = delay
        self.timeout = timeout
        self.logger = logger
        self.last_request = 0.0
        self.robots: dict[str, RobotFileParser] = {}
        self.error_count = 0

    def _wait(self) -> None:
        remaining = self.delay - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, url: str, base_url: str, method: str = "GET"):
        self._wait()
        request = Request(url, headers={"User-Agent": USER_AGENT}, method=method)
        try:
            opener = build_opener(_DomainRedirectHandler(base_url))
            response = opener.open(request, timeout=self.timeout)
            self.last_request = time.monotonic()
            return response
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            self.last_request = time.monotonic()
            self.error_count += 1
            self.logger.warning("Request failed (%s) %s: %s", method, url, exc)
            return None

    def robots_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robots_url = f"{origin}/robots.txt"
            response = self._request(robots_url, url)
            parser = RobotFileParser(robots_url)
            if response is None:
                parser.parse(["User-agent: *", "Disallow:"])
                self.logger.warning("Robots policy unavailable; proceeding cautiously for %s", origin)
            else:
                try:
                    final_url = normalize_url(response.geturl())
                    if not is_within_domain(final_url, url):
                        raise ValueError("robots.txt redirected outside the source domain")
                    content = response.read(512_000).decode("utf-8", errors="replace")
                    parser.parse(content.splitlines())
                except (OSError, ValueError) as exc:
                    parser.parse(["User-agent: *", "Disallow:"])
                    self.logger.warning("Could not read robots.txt for %s: %s", origin, exc)
                finally:
                    response.close()
            self.robots[origin] = parser
        return self.robots[origin].can_fetch(USER_AGENT, url)

    def fetch_html(self, url: str, base_url: str) -> str | None:
        response = self._request(url, base_url)
        if response is None:
            return None
        try:
            final_url = normalize_url(response.geturl())
            if not final_url or not is_within_domain(final_url, base_url):
                self.logger.warning("Rejected redirect outside configured domain: %s -> %s", url, response.geturl())
                return None
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                self.logger.info("Skipped non-HTML response (%s): %s", content_type, url)
                return None
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read(2_000_000).decode(charset, errors="replace")
        except (OSError, LookupError, UnicodeError) as exc:
            self.error_count += 1
            self.logger.warning("Could not read HTML page %s: %s", url, exc)
            return None
        finally:
            response.close()


def discover_source(
    source: dict,
    subjects_config: dict,
    limits: dict,
    logger: logging.Logger,
) -> tuple[list[dict[str, str]], dict]:
    stats: dict = {
        "pages_visited": 0, "pages_skipped": 0, "candidates_discovered": 0, "errors": 0,
        "navigation_pages_excluded": 0, "listing_pages_excluded": 0,
        "rejected_samples": [],
    }
    base_url = normalize_url(str(source.get("base_url", "")))
    if not base_url:
        logger.warning("Source %s has no valid base_url; skipped", source.get("id", ""))
        stats["pages_skipped"] += 1
        return [], stats
    fetcher = PoliteFetcher(limits["request_delay_seconds"], limits["timeout_seconds"], logger)
    queue = deque([(base_url, 0)])
    visited: set[str] = set()
    candidate_by_url: dict[str, dict[str, str]] = {}
    rejected_by_url: dict[str, tuple[str, int, str]] = {}

    def process_link(link: Link, page_title: str, page_url: str) -> None:
        candidate, decision = evaluate_link(link, page_title, page_url, source, subjects_config)
        candidate_url = normalize_url(urljoin(page_url, link.href))
        if candidate and is_within_domain(candidate["source_url"], base_url):
            candidate_by_url.setdefault(candidate["source_url"], candidate)
        elif candidate_url and is_within_domain(candidate_url, base_url):
            rejected_by_url.setdefault(
                candidate_url,
                (decision.title or candidate_url, decision.score, decision.rejection_reason),
            )

    while queue and stats["pages_visited"] < limits["max_pages_per_source"]:
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
        html = fetcher.fetch_html(page_url, base_url)
        if html is None:
            stats["pages_skipped"] += 1
            continue
        page = parse_html(html)
        process_link(Link(href=page_url, text=page.title), page.title, page_url)
        for link in page.links:
            process_link(link, page.title, page_url)
            target = normalize_url(urljoin(page_url, link.href))
            if not target or not is_within_domain(target, base_url) or target in visited:
                continue
            if depth >= limits["max_depth"] or not should_crawl(target):
                continue
            queue.append((target, depth + 1))
    if queue:
        stats["pages_skipped"] += len(queue)
        logger.info("Page limit reached; %d queued pages not visited", len(queue))
    stats["errors"] = fetcher.error_count
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
    started = time.monotonic()
    logger, log_path = create_logger()
    logger.info("Crawl started at %s", datetime.now(timezone.utc).isoformat())
    try:
        sources, subjects_config = load_configuration()
        existing = read_catalog()
    except (OSError, ValueError, yaml.YAMLError, CatalogError) as exc:
        logger.error("Configuration/catalog validation failed: %s", exc)
        return 2

    selected = [source for source in sources if args.source is None or source.get("id") == args.source]
    if args.source and not selected:
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
    }
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
            continue
        if source.get("verified") is not True:
            logger.warning("SKIPPED_UNVERIFIED_SOURCE %s", source_id)
            continue
        if not source.get("base_url"):
            logger.warning("Verified source %s has no base_url; skipped", source_id)
            continue
        logger.info("Source started: %s (%s)", source_id, source.get("base_url"))
        candidates, stats = discover_source(source, subjects_config, limits, logger)
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

    rows = assign_ids(list(new_candidates.values()), existing)
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
        try:
            append_catalog(CATALOG_PATH, rows)
        except (OSError, CatalogError, csv.Error) as exc:
            logger.error("Catalog append failed; no successful update reported: %s", exc)
            return 2
        print(f"Appended {len(rows)} candidate(s) to documents.csv.")
    else:
        print("No new candidates to append.")
    elapsed = time.monotonic() - started
    logger.info("Crawl completed: candidates_to_add=%d elapsed_seconds=%.2f", len(rows), elapsed)
    logger.info("Log file: %s", log_path)
    for handler in logger.handlers:
        handler.flush()
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover educational resources from verified configured sources.")
    parser.add_argument("--source", help="Crawl only this configured source ID")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_LIMITS["max_pages_per_source"])
    parser.add_argument("--max-depth", type=int, default=DEFAULT_LIMITS["max_depth"])
    parser.add_argument("--delay", type=float, default=DEFAULT_LIMITS["request_delay_seconds"])
    parser.add_argument("--timeout", type=float, default=DEFAULT_LIMITS["timeout_seconds"])
    parser.add_argument("--dry-run", action="store_true", help="Discover and preview candidates without modifying the catalog")
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_depth < 0 or args.delay < 0 or args.timeout <= 0:
        parser.error("--max-pages must be positive; --max-depth and --delay nonnegative; --timeout positive")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
