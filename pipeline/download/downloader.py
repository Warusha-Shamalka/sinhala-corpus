"""Download bounded PDF batches from the catalog; dry-run performs no requests."""

from __future__ import annotations

import argparse
import csv
import hashlib
from http.client import HTTPException
import json
import logging
import math
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlsplit

import yaml

from pipeline.discovery.crawler import (
    ROOT, SOURCES_PATH, CatalogError, PoliteFetcher,
    _catalog_lock, _read_catalog, _validate_rows, read_catalog,
)
from pipeline.discovery.filters import normalize_url


VERSION = "download-0.1"
PIPELINE_PATH = ROOT / "configs/pipeline.yaml"
PDF_MIMES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


class DownloadError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_settings(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "pipeline-1" or not isinstance(data.get("download"), dict):
        raise ValueError("Expected pipeline-1 configuration with download settings")
    settings = dict(data["download"])
    for name in ("catalog_path", "raw_root", "log_root"):
        value = settings.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing path: {name}")
        settings[name] = (ROOT / value).resolve()
    for name in ("max_documents", "max_bytes", "max_requests", "max_retries"):
        value = settings.get(name)
        if type(value) is not int or value < (0 if name == "max_retries" else 1):
            raise ValueError(f"Invalid integer setting: {name}")
    for name in ("max_seconds", "timeout_seconds", "request_delay_seconds", "max_retry_wait"):
        value = settings.get(name)
        minimum = 0 if name in {"request_delay_seconds", "max_retry_wait"} else 0.000001
        if type(value) not in {int, float} or not math.isfinite(value) or value < minimum:
            raise ValueError(f"Invalid duration setting: {name}")
    return settings


def load_sources(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("Sources must be a list")
    sources, ids, names = data["sources"], set(), set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Invalid source entry")
        for field, seen in (("id", ids), ("name", names)):
            value = source.get(field)
            if not isinstance(value, str) or not value.strip() or value in seen:
                raise ValueError(f"Missing or duplicate source {field}")
            seen.add(value)
        if any(type(source.get(flag)) is not bool for flag in ("enabled", "verified")):
            raise ValueError("Source approval flags must be booleans")
        if source["enabled"] and source["verified"] and not normalize_url(source.get("base_url", "")):
            raise ValueError("Approved source requires a valid base_url")
    return sources


def plan_downloads(rows: list[dict], sources: list[dict], *, source_id: str | None = None,
                   doc_ids: list[str] | None = None, maximum: int = 5, refresh: bool = False) -> tuple[list[tuple[dict, dict]], list[dict]]:
    if source_id and source_id not in {s["id"] for s in sources}:
        raise ValueError(f"Unknown source: {source_id}")
    if doc_ids and set(doc_ids) - {r["doc_id"] for r in rows}:
        raise ValueError("Requested document IDs are absent from the catalog")
    by_name = {s["name"]: s for s in sources}
    jobs, excluded = [], []
    # Fresh work before already-completed records avoids starving later batches.
    for row in sorted(rows, key=lambda r: r["status"] == "DOWNLOADED"):
        if doc_ids and row["doc_id"] not in doc_ids:
            continue
        source = by_name.get(row["source"])
        if source_id and (not source or source["id"] != source_id):
            continue
        url = normalize_url(row["source_url"])
        reason = ""
        if not url:
            reason = "missing_source_url"
        elif not source or not source["enabled"] or not source["verified"]:
            reason = "source_not_approved"
        elif urlsplit(url).hostname != urlsplit(normalize_url(source["base_url"])).hostname:
            reason = "resource_host_not_approved"
        elif row["status"] not in {"DISCOVERED", "DOWNLOAD_FAILED", "DOWNLOADED"}:
            reason = "stage_already_advanced"
        elif len(jobs) >= maximum:
            reason = "batch_limit"
        if reason:
            excluded.append({"doc_id": row["doc_id"], "reason": reason})
        else:
            jobs.append((row, source))
    return jobs, excluded


def checkpoint(catalog: Path, expected: dict, updates: dict) -> bool:
    """Compare-and-set one row under the existing catalog lock."""
    with _catalog_lock(catalog, 10):
        header, rows = _read_catalog(catalog)
        current = next((r for r in rows if r["doc_id"] == expected["doc_id"]), None)
        if current != expected:
            return False
        current.update(updates)
        _validate_rows(rows, allow_pilots=True)
        fd, name = tempfile.mkstemp(prefix=f".{catalog.name}.", suffix=".tmp", dir=catalog.parent)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=header)
                writer.writeheader()
                writer.writerows(rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, catalog)
            sync_directory(catalog.parent)
        finally:
            Path(name).unlink(missing_ok=True)
    return True


def artifact_name(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def recover(row: dict, raw_root: Path) -> dict | None:
    folder = raw_root / "pdf" / row["doc_id"]
    receipts = sorted(folder.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True) if folder.exists() else []
    if row["status"] == "DOWNLOADED":
        receipts = [folder / f"{row['sha256']}.json"]
    for path in receipts:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("schema_version") != "raw-download-1" or receipt.get("doc_id") != row["doc_id"]:
            raise DownloadError("Invalid raw download receipt")
        if receipt.get("requested_url") != normalize_url(row["source_url"]):
            continue
        digest = receipt.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or path.stem != digest:
            raise DownloadError("Invalid receipt hash")
        artifact = folder / f"{digest}.pdf"
        if type(receipt.get("bytes")) is not int or receipt["bytes"] < 1:
            raise DownloadError("Invalid receipt byte count")
        if receipt.get("artifact_path") != str(artifact.relative_to(raw_root)) or receipt.get("local_filename") != artifact_name(artifact):
            raise DownloadError("Receipt and raw artifact path disagree")
        if artifact.stat().st_size != receipt["bytes"] or file_hash(artifact) != digest:
            raise DownloadError("Stored raw artifact failed hash/size verification")
        if row["status"] == "DOWNLOADED" and row["local_filename"] != artifact_name(artifact):
            raise DownloadError("Catalog and raw artifact path disagree")
        return receipt
    if row["status"] == "DOWNLOADED":
        raise DownloadError("Downloaded record has no matching raw receipt")
    return None


def persist_pdf(row: dict, source: dict, settings: dict, fetcher: PoliteFetcher) -> dict:
    url = normalize_url(row["source_url"])
    response = fetcher.open_resource(url, normalize_url(source["base_url"]))
    if response is None:
        raise DownloadError(fetcher.last_failure or "request_failed")
    temporary = None
    started = utc_now()
    try:
        final_url = normalize_url(response.geturl())
        if not final_url or urlsplit(final_url).hostname != urlsplit(url).hostname:
            raise DownloadError("Unapproved final resource host")
        if response.getcode() != 200:
            raise DownloadError("Expected HTTP 200 (partial responses are not resumed)")
        mime = response.headers.get_content_type().lower()
        if mime not in PDF_MIMES:
            raise DownloadError(f"Not a supported PDF MIME type: {mime}")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise DownloadError("Compressed transport is not supported")
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) > settings["max_bytes"]):
            raise DownloadError("Invalid or excessive Content-Length")
        folder = settings["raw_root"] / "pdf" / row["doc_id"]
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".download-", suffix=".tmp", dir=folder)
        temporary = Path(name)
        digest, size, prefix, tail = hashlib.sha256(), 0, b"", b""
        with os.fdopen(fd, "wb") as stream:
            read = getattr(response, "read1", response.read)
            while True:
                if fetcher._remaining() <= 0:
                    raise DownloadError("time_limit")
                chunk = read(min(65536, settings["max_bytes"] + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > settings["max_bytes"]:
                    raise DownloadError("Resource exceeds byte limit")
                prefix = (prefix + chunk)[:16]
                if len(prefix) >= 5 and not prefix.startswith(b"%PDF-"):
                    raise DownloadError("PDF signature missing; possible HTML/login/error response")
                tail = (tail + chunk)[-2048:]
                digest.update(chunk)
                stream.write(chunk)
            if declared is not None and size != int(declared):
                raise DownloadError("Content-Length mismatch; interrupted response")
            if not prefix.startswith(b"%PDF-") or b"%%EOF" not in tail:
                raise DownloadError("Incomplete PDF signature/end marker")
            stream.flush()
            os.fsync(stream.fileno())
        sha = digest.hexdigest()
        artifact = folder / f"{sha}.pdf"
        if artifact.exists():
            if file_hash(artifact) != sha:
                raise DownloadError("Existing raw artifact is corrupted; refusing overwrite")
        else:
            os.replace(temporary, artifact)
            sync_directory(folder)
        receipt = {"schema_version": "raw-download-1", "doc_id": row["doc_id"], "source_id": source["id"],
                   "requested_url": url, "final_url": final_url, "http_status": 200, "mime": mime,
                   "bytes": size, "sha256": sha, "artifact_path": str(artifact.relative_to(settings["raw_root"])),
                   "local_filename": artifact_name(artifact), "started_at_utc": started, "completed_at_utc": utc_now(),
                   "etag": response.headers.get("ETag", ""), "last_modified": response.headers.get("Last-Modified", ""),
                   "pipeline_version": VERSION, "robots_outcomes": dict(fetcher.robots_outcomes)}
        receipt_path = folder / f"{sha}.json"
        if not receipt_path.exists():
            fd, receipt_tmp = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=folder)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(receipt, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(receipt_tmp, receipt_path)
                sync_directory(folder)
            finally:
                Path(receipt_tmp).unlink(missing_ok=True)
        return receipt
    finally:
        response.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(settings: dict, sources: list[dict], *, source_id=None, doc_ids=None, dry_run=False, refresh=False) -> dict:
    catalog = settings["catalog_path"]
    jobs, excluded = plan_downloads(read_catalog(catalog), sources, source_id=source_id,
                                   doc_ids=doc_ids, maximum=settings["max_documents"], refresh=refresh)
    report = {"schema_version": "download-run-1", "dry_run": dry_run, "refresh": refresh,
              "planned": [r["doc_id"] for r, _ in jobs], "excluded": excluded, "results": []}
    if dry_run or not jobs:
        return report
    # Cooperative single downloader; discovery still uses the independent CSV lock.
    with _catalog_lock(catalog.with_name("download-worker"), 0):
        log_root = settings["log_root"]
        log_root.mkdir(parents=True, exist_ok=True)
        events = log_root / f"download_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}.jsonl"
        report["events_path"] = str(events)
        fetchers = {}
        with events.open("x", encoding="utf-8") as audit:
            for row, source in jobs:
                result = {"doc_id": row["doc_id"], "at_utc": utc_now()}
                try:
                    receipt = None if refresh else recover(row, settings["raw_root"])
                    if receipt is None:
                        if source["id"] not in fetchers:
                            fetchers[source["id"]] = PoliteFetcher(
                                settings["request_delay_seconds"], settings["timeout_seconds"], logging.getLogger(__name__),
                                max_requests=settings["max_requests"], max_seconds=settings["max_seconds"],
                                max_retries=settings["max_retries"], max_retry_wait=settings["max_retry_wait"],
                                user_agent="SinhalaCorpusDownload/0.1 (+educational corpus resource downloader)",
                                allowed_hosts={urlsplit(normalize_url(source["base_url"])).hostname})
                        receipt = persist_pdf(row, source, settings, fetchers[source["id"]])
                        result["outcome"] = "downloaded"
                    else:
                        result["outcome"] = "verified_existing" if row["status"] == "DOWNLOADED" else "recovered"
                    result["sha256"] = receipt["sha256"]
                    updates = {"status": "DOWNLOADED", "sha256": receipt["sha256"],
                               "local_filename": receipt["local_filename"], "pipeline_version": VERSION,
                               "last_processed": utc_now(), "error": ""}
                    if not checkpoint(catalog, row, updates):
                        result["outcome"] = "catalog_conflict"
                except (DownloadError, HTTPException, OSError, ValueError, KeyError, CatalogError) as exc:
                    result.update(outcome="failed", error=str(exc))
                    # A failed refresh must preserve the previous successful version.
                    if row["status"] != "DOWNLOADED":
                        checkpoint(catalog, row, {"status": "DOWNLOAD_FAILED", "error": str(exc),
                                                  "last_processed": utc_now(), "pipeline_version": VERSION})
                audit.write(json.dumps(result, ensure_ascii=False) + "\n")
                audit.flush()
                os.fsync(audit.fileno())
                report["results"].append(result)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PIPELINE_PATH)
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--source")
    parser.add_argument("--doc-id", action="append", dest="doc_ids")
    parser.add_argument("--max-documents", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Fetch a new version; retain old raw artifacts")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.max_documents is not None:
            if args.max_documents < 1:
                raise ValueError("max-documents must be positive")
            settings["max_documents"] = args.max_documents
        report = run(settings, load_sources(args.sources), source_id=args.source, doc_ids=args.doc_ids,
                     dry_run=args.dry_run, refresh=args.refresh)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(any(r["outcome"] in {"failed", "catalog_conflict"} for r in report["results"]))
    except (OSError, ValueError, CatalogError) as exc:
        parser.exit(2, f"Download configuration/catalog error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
