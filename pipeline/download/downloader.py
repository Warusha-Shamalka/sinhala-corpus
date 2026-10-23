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
import sys
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
from pipeline.progress import ProgressReporter


VERSION = "download-0.1"
PIPELINE_PATH = ROOT / "configs/pipeline.yaml"
PDF_MIMES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
HTML_MIMES = {"text/html", "application/xhtml+xml"}


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
    settings.setdefault('accepted_formats', ['pdf'])
    if not isinstance(settings['accepted_formats'], list) or not settings['accepted_formats'] or any(v not in {'pdf', 'html'} for v in settings['accepted_formats']):
        raise ValueError('accepted_formats must contain pdf and/or html')
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
        source_base = normalize_url(source["base_url"]) if source else ""
        allowed = set(source.get("resource_hosts", [])) | {urlsplit(source_base).hostname} if source else set()
        if not url:
            reason = "missing_source_url"
        elif not source or not source["enabled"] or not source["verified"]:
            reason = "source_not_approved"
        elif urlsplit(url).hostname not in allowed:
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
    folders = [raw_root / kind / row['doc_id'] for kind in ('pdf', 'html', 'png', 'jpg')]
    receipts = sorted((p for folder in folders for p in folder.glob('*.json')),
                      key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    if row["status"] == "DOWNLOADED":
        kind = Path(row['local_filename']).suffix.lower().lstrip('.')
        if kind not in {'pdf', 'html', 'png', 'jpg'}:
            raise DownloadError('Unsupported raw artifact format')
        receipts = [raw_root / kind / row['doc_id'] / f"{row['sha256']}.json"]
    for path in receipts:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("schema_version") != "raw-download-1" or receipt.get("doc_id") != row["doc_id"]:
            raise DownloadError("Invalid raw download receipt")
        if receipt.get("requested_url") != normalize_url(row["source_url"]):
            continue
        digest = receipt.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or path.stem != digest:
            raise DownloadError("Invalid receipt hash")
        kind = receipt.get('format', 'pdf')
        if kind not in {'pdf', 'html', 'png', 'jpg'} or path.parent != raw_root / kind / row['doc_id']:
            raise DownloadError('Invalid receipt format/path')
        artifact = path.parent / f"{digest}.{kind}"
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


def persist_pdf(row: dict, source: dict, settings: dict, fetcher: PoliteFetcher, progress=None) -> dict:
    url = normalize_url(row["source_url"])
    response = fetcher.open_resource(url, normalize_url(source["base_url"]))
    if response is None:
        raise DownloadError(fetcher.last_failure or "request_failed")
    temporary = None
    started = utc_now()
    try:
        final_url = normalize_url(response.geturl())
        source_base = normalize_url(source["base_url"])
        allowed = set(source.get("resource_hosts", [])) | {urlsplit(source_base).hostname, urlsplit(url).hostname}
        if not final_url or urlsplit(final_url).hostname not in allowed:
            raise DownloadError("Unapproved final resource host")
        if response.getcode() != 200:
            raise DownloadError("Expected HTTP 200 (partial responses are not resumed)")
        mime = response.headers.get_content_type().lower()
        kind = 'pdf' if mime in PDF_MIMES else 'html' if mime in HTML_MIMES else None
        if kind not in settings.get('accepted_formats', ['pdf']):
            raise DownloadError(f"Not a supported resource MIME type: {mime}")
        byte_limit = min(settings['max_bytes'], 2097152) if kind == 'html' else settings['max_bytes']
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise DownloadError("Compressed transport is not supported")
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) > byte_limit):
            raise DownloadError("Invalid or excessive Content-Length")
        if progress:
            progress.begin_transfer(int(declared) if declared is not None else None)
        folder = settings["raw_root"] / kind / row["doc_id"]
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".download-", suffix=".tmp", dir=folder)
        temporary = Path(name)
        digest, size, prefix, tail = hashlib.sha256(), 0, b"", b""
        with os.fdopen(fd, "wb") as stream:
            read = getattr(response, "read1", response.read)
            while True:
                if fetcher._remaining() <= 0:
                    raise DownloadError("time_limit")
                chunk = read(min(65536, byte_limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > byte_limit:
                    raise DownloadError("Resource exceeds byte limit")
                prefix = (prefix + chunk)[:2048]
                if kind == 'pdf' and len(prefix) >= 5 and not prefix.startswith(b"%PDF-"):
                    raise DownloadError("PDF signature missing; possible HTML/login/error response")
                tail = (tail + chunk)[-2048:]
                digest.update(chunk)
                stream.write(chunk)
                if progress:
                    progress.transfer(size, int(declared) if declared is not None else None)
            if declared is not None and size != int(declared):
                raise DownloadError("Content-Length mismatch; interrupted response")
            if kind == 'pdf' and (not prefix.startswith(b"%PDF-") or b"%%EOF" not in tail):
                raise DownloadError("Incomplete PDF signature/end marker")
            if kind == 'html' and b'<html' not in prefix.lower() and b'<!doctype html' not in prefix.lower():
                raise DownloadError('Missing HTML document signature')
            stream.flush()
            os.fsync(stream.fileno())
        if progress:
            progress.update(force=True, phase="persisting")
        sha = digest.hexdigest()
        artifact = folder / f"{sha}.{kind}"
        if artifact.exists():
            if file_hash(artifact) != sha:
                raise DownloadError("Existing raw artifact is corrupted; refusing overwrite")
        else:
            os.replace(temporary, artifact)
            sync_directory(folder)
        receipt = {"schema_version": "raw-download-1", "doc_id": row["doc_id"], "source_id": source["id"],
                   "format": kind, "charset": response.headers.get_content_charset() or '',
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


def run(settings: dict, sources: list[dict], *, source_id=None, doc_ids=None, dry_run=False, refresh=False, progress_mode=None) -> dict:
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
        progress = ProgressReporter("download", run_id=events.stem, path=events.with_suffix(".progress.json"), mode=progress_mode) if progress_mode is not None else None
        if progress:
            report["progress_path"] = str(progress.path)
            progress.update(force=True, counts={"jobs_total": len(jobs), "jobs_completed": 0, "excluded": len(excluded), "deferred": sum(r["reason"] == "batch_limit" for r in excluded), **{key: 0 for key in ("downloaded", "verified_existing", "recovered", "failed", "catalog_conflict")}})
        fetchers = {}
        try:
            with events.open("x", encoding="utf-8") as audit:
                for row, source in jobs:
                    result = {"doc_id": row["doc_id"], "at_utc": utc_now()}
                    if progress:
                        if progress.state.get("source_id") != source["id"]:
                            progress.update(counts={"requests": 0, "retries": 0})
                        progress.update(force=True, phase="verifying_existing", source_id=source["id"], item={"doc_id": row["doc_id"], "title": row["title"]}, transfer={}, robots_outcome="")
                    try:
                        receipt = None if refresh else recover(row, settings["raw_root"])
                        if receipt is None:
                            if source["id"] not in fetchers:
                                fetchers[source["id"]] = PoliteFetcher(
                                    settings["request_delay_seconds"], settings["timeout_seconds"], logging.getLogger(__name__),
                                    max_requests=settings["max_requests"], max_seconds=settings["max_seconds"],
                                    max_retries=settings["max_retries"], max_retry_wait=settings["max_retry_wait"],
                                    user_agent="SinhalaCorpusDownload/0.1 (+educational corpus resource downloader)",
                                    allowed_hosts=set(source.get("resource_hosts", [])) | {urlsplit(normalize_url(source["base_url"])).hostname})
                            if progress:
                                fetchers[source["id"]].progress = progress
                            receipt = persist_pdf(row, source, settings, fetchers[source["id"]], progress)
                            result["outcome"] = "downloaded"
                        else:
                            result["outcome"] = "verified_existing" if row["status"] == "DOWNLOADED" else "recovered"
                        result["sha256"] = receipt["sha256"]
                        updates = {"status": "DOWNLOADED", "sha256": receipt["sha256"],
                                   "local_filename": receipt["local_filename"], "pipeline_version": VERSION,
                                   "last_processed": utc_now(), "error": ""}
                        if progress:
                            progress.update(force=True, phase="catalog_checkpoint")
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
                    if progress:
                        progress.update(force=True, phase="job_finished", counts={"jobs_completed": len(report["results"]), **{key: sum(r["outcome"] == key for r in report["results"]) for key in ("downloaded", "verified_existing", "recovered", "failed", "catalog_conflict")}})
        except BaseException as exc:
            if progress:
                progress.finish("interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
            raise
        if progress:
            progress.finish("failed" if any(r["outcome"] in {"failed", "catalog_conflict"} for r in report["results"]) else "completed")
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
    parser.add_argument("--progress", choices=("auto", "plain", "off"), default="auto")
    parser.add_argument("--quiet", action="store_true", help="Suppress terminal progress (snapshots still saved)")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.max_documents is not None:
            if args.max_documents < 1:
                raise ValueError("max-documents must be positive")
            settings["max_documents"] = args.max_documents
        report = run(settings, load_sources(args.sources), source_id=args.source, doc_ids=args.doc_ids,
                     dry_run=args.dry_run, refresh=args.refresh, progress_mode="off" if args.quiet else args.progress)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(any(r["outcome"] in {"failed", "catalog_conflict"} for r in report["results"]))
    except KeyboardInterrupt:
        print("Download interrupted; inspect the progress snapshot and event log.", file=sys.stderr)
        return 130
    except (OSError, ValueError, CatalogError) as exc:
        parser.exit(2, f"Download configuration/catalog error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
