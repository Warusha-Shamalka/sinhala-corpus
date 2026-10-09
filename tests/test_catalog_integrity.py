import csv
import fcntl
import io
import multiprocessing
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
import logging
from pathlib import Path
from unittest.mock import patch

from pipeline.discovery import crawler


def candidate(url, **changes):
    return {"title": "History resource", "source": "School", "source_url": url,
            "document_type": "textbook", **changes}


def concurrent_append(path, index, start, results):
    start.wait(10)
    try:
        rows = crawler.append_catalog(Path(path), [candidate(f"https://school.test/{index}.pdf"),
                                                  candidate("https://school.test/shared.pdf")])
        results.put(("ok", len(rows)))
    except Exception as exc:
        results.put(("error", str(exc)))


class CatalogIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "documents.csv"
        self.write([])

    def write(self, rows, header=None):
        with self.path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=header or crawler.CATALOG_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def test_stale_previews_receive_fresh_ids(self):
        a = crawler.assign_ids([candidate("https://school.test/a.pdf")], [])
        b = crawler.assign_ids([candidate("https://school.test/b.pdf")], [])
        self.assertEqual(a[0]["doc_id"], b[0]["doc_id"])
        first = crawler.append_catalog(self.path, a)
        second = crawler.append_catalog(self.path, b)
        self.assertEqual([first[0]["doc_id"], second[0]["doc_id"]], ["LK-EDU-000001", "LK-EDU-000002"])

    def test_repeated_urls_within_and_across_batches_are_idempotent(self):
        rows = crawler.append_catalog(self.path, [candidate("https://school.test/a.pdf#one"),
                                                 candidate("https://school.test/a.pdf#two")])
        self.assertEqual(len(rows), 1)
        before = self.path.read_bytes()
        self.assertEqual(crawler.append_catalog(self.path, [candidate("https://school.test/a.pdf")]), [])
        self.assertEqual(self.path.read_bytes(), before)

    def test_independent_processes_preserve_every_record_and_shared_url(self):
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Event(), ctx.Queue()
        workers = [ctx.Process(target=concurrent_append, args=(str(self.path), i, start, results)) for i in range(4)]
        try:
            for worker in workers:
                worker.start()
            start.set()
            outcomes = [results.get(timeout=15) for _ in workers]
            for worker in workers:
                worker.join(15)
                self.assertEqual(worker.exitcode, 0)
            self.assertTrue(all(outcome[0] == "ok" for outcome in outcomes), outcomes)
            rows = crawler.read_catalog(self.path)
            self.assertEqual(len(rows), 5)
            self.assertEqual(len({row["doc_id"] for row in rows}), 5)
            self.assertEqual(len({row["source_url"] for row in rows}), 5)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
            results.close()

    def test_lock_timeout_preserves_catalog(self):
        before = self.path.read_bytes()
        with self.path.with_name(".documents.csv.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(crawler.CatalogError, "Timed out"):
                crawler.append_catalog(self.path, [candidate("https://school.test/a.pdf")], lock_timeout=0.05)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(crawler.append_catalog(self.path, [candidate("https://school.test/a.pdf")])), 1)

    def test_invalid_catalog_is_never_rewritten(self):
        row = crawler.assign_ids([candidate("https://school.test/a.pdf")], [])[0]
        for change in ({"doc_id": "bad"}, {"status": "UNKNOWN"}, {"source_url": "ftp://school.test/a"},
                       {"sha256": "not-a-hash"}, {"page_count": "-1"}, {"quality_score": "nan"},
                       {"source_url": "", "source": ""}, {"grade": "11-10"}, {"status": "DOWNLOADED"}):
            with self.subTest(change=change):
                self.write([{**row, **change}])
                before = self.path.read_bytes()
                with self.assertRaises(crawler.CatalogError):
                    crawler.append_catalog(self.path, [candidate("https://school.test/b.pdf")])
                self.assertEqual(self.path.read_bytes(), before)

    def test_duplicate_ids_and_urls_are_rejected(self):
        rows = crawler.assign_ids([candidate("https://school.test/a.pdf"), candidate("https://school.test/b.pdf")], [])
        for field, value in (("doc_id", rows[0]["doc_id"]), ("source_url", rows[0]["source_url"] + "#fragment")):
            self.write([rows[0], {**rows[1], field: value}])
            with self.assertRaises(crawler.CatalogError):
                crawler.read_catalog(self.path)

    def test_malformed_csv_headers_and_row_width(self):
        header = ",".join(crawler.CATALOG_COLUMNS)
        for content in (header + ",doc_id\n", header + "\nonly,three,fields\n",
                        header + "\n" + ",".join([""] * 24) + "\n"):
            self.path.write_text(content)
            with self.assertRaises(crawler.CatalogError):
                crawler.read_catalog(self.path)

    def test_invalid_candidates_do_not_partially_commit(self):
        for changes in ({"source_url": ""}, {"source": ""}, {"title": ""}, {"document_type": "made_up"},
                        {"status": "READY"}, {"page_count": None}, {"unknown": "discard me"}):
            before = self.path.read_bytes()
            with self.assertRaises(crawler.CatalogError):
                crawler.append_catalog(self.path, [candidate("https://school.test/good.pdf"),
                                                   candidate("https://school.test/bad.pdf", **changes)])
            self.assertEqual(self.path.read_bytes(), before)

    def test_extension_columns_and_existing_ids_preserved(self):
        row = crawler.assign_ids([candidate("https://school.test/old.pdf")], [])[0]
        row.update(doc_id="LK-EDU-000009", annotation="keep me")
        self.write([row], [*crawler.CATALOG_COLUMNS, "annotation"])
        added = crawler.append_catalog(self.path, [candidate("https://school.test/new.pdf", annotation="new")])
        records = crawler.read_catalog(self.path)
        self.assertEqual(records[0], row)
        self.assertEqual(added[0]["doc_id"], "LK-EDU-000010")
        self.assertEqual(records[1]["annotation"], "new")

    def test_replace_failure_preserves_original_and_releases_lock(self):
        before = self.path.read_bytes()
        with patch.object(crawler.os, "replace", side_effect=OSError("injected failure")):
            with self.assertRaises(OSError):
                crawler.append_catalog(self.path, [candidate("https://school.test/a.pdf")])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertEqual(len(crawler.append_catalog(self.path, [candidate("https://school.test/a.pdf")])), 1)

    def test_pilot_rows_and_ids_are_preserved(self):
        self.path.write_bytes(crawler.CATALOG_PATH.read_bytes())
        before = crawler.read_catalog(self.path)
        added = crawler.append_catalog(self.path, [candidate("https://school.test/new.pdf")])
        self.assertEqual(crawler.read_catalog(self.path)[:8], before)
        self.assertEqual(added[0]["doc_id"], "LK-EDU-000009")
        self.assertTrue(all(not row["source_url"] for row in before))

    def test_run_reports_only_rows_committed_after_a_racing_writer(self):
        item = candidate("https://school.test/shared.pdf")
        source = {"id": "school", "name": "School", "base_url": "https://school.test/",
                  "enabled": True, "verified": True}

        def discover(*args):
            crawler.append_catalog(self.path, [item])
            return [item], {"pages_visited": 1, "errors": 0}

        args = Namespace(source="school", max_depth=1, max_pages=1, delay=0, timeout=1, dry_run=False)
        output = io.StringIO()
        with patch.object(crawler, "CATALOG_PATH", self.path), \
             patch.object(crawler, "load_configuration", return_value=([source], {})), \
             patch.object(crawler, "discover_source", side_effect=discover), \
             patch.object(crawler, "create_logger", return_value=(logging.getLogger("catalog-run-test"), self.path.parent / "run.log")), \
             redirect_stdout(output):
            self.assertEqual(crawler.run(args), 0)
        self.assertIn("Appended 0 candidate(s)", output.getvalue())
        self.assertEqual(len(crawler.read_catalog(self.path)), 1)


if __name__ == "__main__":
    unittest.main()
