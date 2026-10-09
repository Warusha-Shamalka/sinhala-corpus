"""Report current edge cases offline; not regression expectations or a test suite.

Run from the root: python3 -B docs/evidence/reproduce_review.py
Only a temporary catalog is written. No network or source/catalog changes.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml

from pipeline.discovery import crawler
from pipeline.discovery.filters import extract_grade, normalize_url, subject_matches
from pipeline.discovery.parser import Link, evaluate_link, parse_html


def main() -> None:
    subjects = yaml.safe_load((ROOT / "configs/subjects.yaml").read_text(encoding="utf-8"))
    report: dict = {"scope": "offline probes; no hidden-test or network inputs"}
    report["metadata"] = [
        {"input": text, "subject": subject_matches(text, subjects), "grade": extract_grade(text, subjects)}
        for text in (
            "History of Sri Lanka", "Sinhala Language and Literature", "ඉතිහාසය",
            "8 ශ්‍රේණිය ඉතිහාසය", "Grade 8-9 History",
        )
    ]
    report["urls"] = []
    for url in ("https://[bad/path", "ftp://school.test/history.pdf"):
        try:
            result = {"input": url, "normalized": normalize_url(url)}
        except ValueError as exc:
            result = {"input": url, "error": type(exc).__name__, "message": str(exc)}
        report["urls"].append(result)
    page = parse_html('<script>History textbook</script><a href="/download">Download</a>')
    report["script_context"] = page.links[0].before
    report["candidates"] = []
    for link, page_title in (
        (Link("/download", "Download"), "Grade 8 History textbook"),
        (Link("/English/history.pdf", "English History textbook"), "Resources"),
        (Link("ftp://school.test/history.pdf", "History textbook"), "Resources"),
    ):
        candidate, decision = evaluate_link(
            link, page_title, "https://school.test/", {"name": "School", "language": "si"}, subjects,
        )
        report["candidates"].append({
            "href": link.href, "accepted": decision.accepted, "subject": decision.subject,
            "language": candidate.get("language") if candidate else None,
        })
    with tempfile.TemporaryDirectory(prefix="sinhalammlu-review-") as directory:
        catalog = Path(directory) / "documents.csv"
        with catalog.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=crawler.CATALOG_COLUMNS)
            writer.writeheader()
        first = crawler.assign_ids([{"source_url": "https://school.test/a.pdf"}], [])
        stale = crawler.assign_ids([{"source_url": "https://school.test/b.pdf"}], [])
        crawler.append_catalog(catalog, first)
        crawler.append_catalog(catalog, stale)
        report["stale_writer_ids"] = [row["doc_id"] for row in crawler.read_catalog(catalog)]
    rows = crawler.read_catalog(ROOT / "corpus/catalog/documents.csv")
    report["catalog"] = {
        "rows": len(rows), "missing_source_urls": sum(not row["source_url"] for row in rows),
        "missing_licenses": sum(not row["license"] for row in rows),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
