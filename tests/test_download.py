import csv
import hashlib
from http.client import IncompleteRead
import io
import json
import logging
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.robotparser import RobotFileParser

from pipeline.discovery import crawler
from pipeline.download import downloader as d


PDF = b"%PDF-1.4\nsynthetic transport fixture, not a parseable school document\n%%EOF\n"
SOURCE = {"id": "school", "name": "School", "base_url": "https://school.test/",
          "enabled": True, "verified": True}


class Response(io.BytesIO):
    def __init__(self, content=PDF, mime="application/pdf", final="https://school.test/paper.pdf", length=None, status=200):
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = mime
        self.headers["Content-Length"] = str(len(content) if length is None else length)
        self.final, self.status = final, status

    def geturl(self):
        return self.final

    def getcode(self):
        return self.status


class Fetcher:
    calls = []
    response_factory = staticmethod(Response)

    def __init__(self, *args, **kwargs):
        self.last_failure = "mock_request_failed"
        self.robots_outcomes = {"https://school.test": "available"}

    def open_resource(self, url, base):
        self.calls.append(url)
        return self.response_factory()

    def _remaining(self):
        return 100


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = d.load_settings(d.PIPELINE_PATH)
        self.settings.update(catalog_path=self.root / "documents.csv", raw_root=self.root / "raw", log_root=self.root / "logs")
        self.row = {key: "" for key in crawler.CATALOG_COLUMNS}
        self.row.update(doc_id="LK-EDU-000009", title="History paper", document_type="past_paper",
                        source="School", source_url="https://school.test/paper.pdf", status="DISCOVERED")
        self.write_catalog([self.row])
        Fetcher.calls = []
        Fetcher.response_factory = staticmethod(Response)

    def write_catalog(self, rows, extra=()):
        with self.settings["catalog_path"].open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=(*crawler.CATALOG_COLUMNS, *extra))
            writer.writeheader()
            writer.writerows(rows)

    def execute(self, **kwargs):
        with patch.object(d, "PoliteFetcher", Fetcher):
            return d.run(self.settings, [SOURCE], **kwargs)

    def test_dry_run_has_no_network_catalog_or_artifact_writes(self):
        before = self.settings["catalog_path"].read_bytes()
        report = self.execute(dry_run=True)
        self.assertEqual(report["planned"], [self.row["doc_id"]])
        self.assertEqual(Fetcher.calls, [])
        self.assertEqual(self.settings["catalog_path"].read_bytes(), before)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {"documents.csv"})

    def test_queue_excludes_pilots_unapproved_and_external_resources(self):
        pilot = {**self.row, "doc_id": "LK-EDU-000001", "title": "Grade 6 History", "source_url": ""}
        external = {**self.row, "doc_id": "LK-EDU-000010", "source_url": "https://evil.test/file.pdf"}
        subdomain = {**self.row, "doc_id": "LK-EDU-000011", "source_url": "https://cdn.school.test/file.pdf"}
        jobs, excluded = d.plan_downloads([pilot, external, subdomain, self.row], [SOURCE])
        self.assertEqual(len(jobs), 1)
        self.assertEqual({r["reason"] for r in excluded}, {"missing_source_url", "resource_host_not_approved"})
        jobs, _ = d.plan_downloads([self.row], [{**SOURCE, "verified": False}])
        self.assertEqual(jobs, [])

    def test_download_writes_hash_receipt_and_preserves_catalog_extensions(self):
        self.row["review_note"] = "preserve"
        self.write_catalog([self.row], extra=("review_note",))
        result = self.execute()["results"][0]
        row = crawler.read_catalog(self.settings["catalog_path"])[0]
        self.assertEqual(result["outcome"], "downloaded")
        self.assertEqual(row["status"], "DOWNLOADED")
        self.assertEqual(row["sha256"], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(Path(row["local_filename"]).read_bytes(), PDF)
        self.assertEqual(row["review_note"], "preserve")
        receipt = json.loads(Path(row["local_filename"]).with_suffix(".json").read_text())
        self.assertEqual(receipt["requested_url"], self.row["source_url"])
        self.assertEqual(receipt["http_status"], 200)

    def test_rerun_verifies_existing_without_network_or_extra_artifacts(self):
        self.execute()
        before = list(self.settings["raw_root"].rglob("*.pdf"))
        Fetcher.calls.clear()
        report = self.execute()
        self.assertEqual(report["results"][0]["outcome"], "verified_existing")
        self.assertEqual(Fetcher.calls, [])
        self.assertEqual(list(self.settings["raw_root"].rglob("*.pdf")), before)

    def test_refresh_preserves_old_and_stores_changed_version(self):
        self.execute()
        old = crawler.read_catalog(self.settings["catalog_path"])[0]
        new_pdf = PDF.replace(b"fixture", b"changed fixture")
        Fetcher.response_factory = staticmethod(lambda: Response(new_pdf))
        self.execute(refresh=True)
        new = crawler.read_catalog(self.settings["catalog_path"])[0]
        self.assertNotEqual(new["sha256"], old["sha256"])
        self.assertEqual(Path(old["local_filename"]).read_bytes(), PDF)
        self.assertEqual(Path(new["local_filename"]).read_bytes(), new_pdf)
        self.assertEqual(len(list(self.settings["raw_root"].rglob("*.pdf"))), 2)

    def test_failed_refresh_preserves_successful_catalog_and_artifact(self):
        self.execute()
        before = self.settings["catalog_path"].read_bytes()
        Fetcher.response_factory = staticmethod(lambda: Response(b"<html>login</html>", mime="text/html"))
        self.assertEqual(self.execute(refresh=True)["results"][0]["outcome"], "failed")
        self.assertEqual(self.settings["catalog_path"].read_bytes(), before)

    def test_resume_after_receipt_saved_but_catalog_checkpoint_interrupted(self):
        with patch.object(d, "checkpoint", side_effect=RuntimeError("simulated crash")):
            with self.assertRaises(RuntimeError):
                self.execute()
        self.assertEqual(crawler.read_catalog(self.settings["catalog_path"])[0]["status"], "DISCOVERED")
        Fetcher.calls.clear()
        self.assertEqual(self.execute()["results"][0]["outcome"], "recovered")
        self.assertEqual(Fetcher.calls, [])

    def test_corrupted_existing_artifact_is_not_overwritten(self):
        self.execute()
        row = crawler.read_catalog(self.settings["catalog_path"])[0]
        artifact = Path(row["local_filename"])
        artifact.write_bytes(b"corruption")
        before = self.settings["catalog_path"].read_bytes()
        self.assertEqual(self.execute()["results"][0]["outcome"], "failed")
        self.assertEqual(artifact.read_bytes(), b"corruption")
        self.assertEqual(self.settings["catalog_path"].read_bytes(), before)

    def test_html_bad_magic_truncated_length_and_missing_eof_fail_cleanly(self):
        factories = [lambda: Response(b"<html>login</html>", mime="text/html"),
                     lambda: Response(b"<html>login</html>"),
                     lambda: Response(PDF, length=len(PDF) + 10),
                     lambda: Response(b"%PDF-1.4\nunfinished"),
                     lambda: Response(PDF, status=206)]
        for factory in factories:
            with self.subTest(factory=factory):
                Fetcher.response_factory = staticmethod(factory)
                result = self.execute()["results"][0]
                self.assertEqual(result["outcome"], "failed")
                self.assertEqual(crawler.read_catalog(self.settings["catalog_path"])[0]["status"], "DOWNLOAD_FAILED")
                self.assertEqual(list(self.settings["raw_root"].rglob("*.pdf")), [])
                self.assertEqual(list(self.settings["raw_root"].rglob("*.tmp")), [])

    def test_size_limits_work_with_and_without_content_length(self):
        self.settings["max_bytes"] = len(PDF) - 1
        self.assertEqual(self.execute()["results"][0]["outcome"], "failed")
        def chunked():
            response = Response()
            del response.headers["Content-Length"]
            return response
        Fetcher.response_factory = staticmethod(chunked)
        self.assertEqual(self.execute()["results"][0]["outcome"], "failed")
        self.assertEqual(list(self.settings["raw_root"].rglob("*.tmp")), [])

    def test_read_interruption_cleans_partial_files_and_can_retry(self):
        class Interrupted(Response):
            def read1(self, size=-1):
                raise IncompleteRead(b"%PDF-", 100)
        Fetcher.response_factory = staticmethod(Interrupted)
        self.assertEqual(self.execute()["results"][0]["outcome"], "failed")
        self.assertEqual(list(self.settings["raw_root"].rglob("*.tmp")), [])
        Fetcher.response_factory = staticmethod(Response)
        self.assertEqual(self.execute()["results"][0]["outcome"], "downloaded")

    def test_external_final_response_and_failed_request_are_rejected(self):
        for factory in (lambda: Response(final="https://evil.test/file.pdf"), lambda: None):
            Fetcher.response_factory = staticmethod(factory)
            self.assertEqual(self.execute()["results"][0]["outcome"], "failed")

    def test_catalog_compare_and_set_preserves_concurrent_metadata_change(self):
        changed = {**self.row, "title": "Reviewed title"}
        self.write_catalog([changed])
        self.assertFalse(d.checkpoint(self.settings["catalog_path"], self.row, {"status": "DOWNLOAD_FAILED"}))
        self.assertEqual(crawler.read_catalog(self.settings["catalog_path"])[0]["title"], "Reviewed title")

    def test_batch_limit_and_unknown_id_are_explicit(self):
        another = {**self.row, "doc_id": "LK-EDU-000010", "source_url": "https://school.test/other.pdf"}
        jobs, excluded = d.plan_downloads([self.row, another], [SOURCE], maximum=1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(excluded[0]["reason"], "batch_limit")
        with self.assertRaises(ValueError):
            d.plan_downloads([self.row], [SOURCE], doc_ids=["LK-EDU-999999"])

    def test_identical_refresh_does_not_duplicate_or_overwrite_raw_bytes(self):
        self.execute()
        artifact = next(self.settings["raw_root"].rglob("*.pdf"))
        before = artifact.stat().st_mtime_ns
        self.execute(refresh=True)
        self.assertEqual(len(list(self.settings["raw_root"].rglob("*.pdf"))), 1)
        self.assertEqual(artifact.stat().st_mtime_ns, before)

    def test_expired_stream_budget_does_not_leave_an_artifact(self):
        with patch.object(Fetcher, "_remaining", return_value=0):
            self.assertEqual(self.execute()["results"][0]["outcome"], "failed")
        self.assertEqual(list(self.settings["raw_root"].rglob("*.pdf")), [])
        self.assertEqual(list(self.settings["raw_root"].rglob("*.tmp")), [])

    def test_worker_lock_blocks_second_downloader_before_requests(self):
        with crawler._catalog_lock(self.settings["catalog_path"].with_name("download-worker"), 0):
            with self.assertRaises(crawler.CatalogError):
                self.execute()
        self.assertEqual(Fetcher.calls, [])

    def test_malformed_receipt_fails_without_changing_successful_catalog(self):
        self.execute()
        receipt = next(self.settings["raw_root"].rglob("*.json"))
        receipt.write_text("[]")
        before = self.settings["catalog_path"].read_bytes()
        self.assertEqual(self.execute()["results"][0]["outcome"], "failed")
        self.assertEqual(self.settings["catalog_path"].read_bytes(), before)


class DownloadTransportTests(unittest.TestCase):
    def test_redirect_robots_disallow_is_checked_before_target_request(self):
        fetcher = crawler.PoliteFetcher(0, 2, logging.getLogger("download-test"), allowed_hosts={"school.test"})
        robots = RobotFileParser()
        robots.parse(["User-agent: *", "Disallow: /private"])
        fetcher.robots["https://school.test"] = robots
        calls = []
        class Opener:
            def __init__(self, handler):
                self.handler = handler
            def open(self, request, timeout):
                calls.append(request.full_url)
                return self.handler.redirect_request(request, io.BytesIO(), 302, "redirect", Message(),
                                                     "https://school.test/private/paper.pdf")
        with patch.object(crawler, "build_opener", side_effect=lambda handler: Opener(handler)):
            self.assertIsNone(fetcher.open_resource("https://school.test/paper.pdf", SOURCE["base_url"]))
        self.assertEqual(calls, ["https://school.test/paper.pdf"])
        self.assertEqual(fetcher.last_failure, "http_302")

    def test_initial_unapproved_host_is_rejected_without_robots_or_http(self):
        fetcher = crawler.PoliteFetcher(0, 2, logging.getLogger("download-test"), allowed_hosts={"school.test"})
        with patch.object(fetcher, "_request") as request:
            self.assertIsNone(fetcher.open_resource("https://cdn.school.test/paper.pdf", SOURCE["base_url"]))
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
