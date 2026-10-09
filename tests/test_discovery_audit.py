import io
import json
import logging
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pipeline.discovery import crawler


LOGGER = logging.getLogger("audit-tests")
BASE = "https://school.test/"
SOURCE = {"id": "school", "name": "School", "base_url": BASE, "enabled": True, "verified": True}
SUBJECTS = {"domains": {}, "education_levels": {}}


class Response(io.BytesIO):
    def __init__(self, body=b"", content_type="text/plain", url=BASE + "robots.txt"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.url = url

    def geturl(self):
        return self.url


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FetchPolicyTests(unittest.TestCase):
    def policy(self, status):
        fetcher = crawler.PoliteFetcher(0, 1, LOGGER, max_retries=0)
        error = HTTPError(BASE + "robots.txt", status, "fixture", Message(), None)
        with patch.object(crawler, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            allowed = fetcher.robots_allowed(BASE)
        return allowed, fetcher

    def test_robots_absent_forbidden_and_transient_failures_are_distinct(self):
        for status, expected, outcome in ((404, True, "absent"), (410, True, "absent"),
                                         (403, False, "forbidden"), (401, False, "forbidden"),
                                         (429, False, "unavailable"), (503, False, "unavailable")):
            with self.subTest(status=status):
                allowed, fetcher = self.policy(status)
                self.assertEqual(allowed, expected)
                self.assertEqual(fetcher.robots_outcomes[BASE.rstrip("/")], outcome)
                self.assertEqual(fetcher.request_count, 1)

    def test_robots_timeout_is_cached_and_blocks_pages(self):
        fetcher = crawler.PoliteFetcher(0, 1, LOGGER, max_retries=0)
        with patch.object(crawler, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("timeout")
            self.assertFalse(fetcher.robots_allowed(BASE))
            self.assertFalse(fetcher.robots_allowed(BASE + "second"))
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_robots_rules_delays_and_request_rate(self):
        response = Response(b"User-agent: *\nDisallow: /private\nCrawl-delay: 4\nRequest-rate: 1/6\n")
        fetcher = crawler.PoliteFetcher(1, 1, LOGGER)
        with patch.object(fetcher, "_request", return_value=response):
            self.assertFalse(fetcher.robots_allowed(BASE + "private"))
            self.assertTrue(fetcher.robots_allowed(BASE + "public"))
        self.assertEqual(fetcher.delay, 6)
        self.assertTrue(response.closed)

    def test_invalid_or_truncated_robots_blocks_crawl(self):
        for response in (Response(b"x" * 512001), Response(b"\xff"), Response(b"<html>login</html>", "text/html")):
            fetcher = crawler.PoliteFetcher(0, 1, LOGGER)
            with patch.object(fetcher, "_request", return_value=response):
                self.assertFalse(fetcher.robots_allowed(BASE))
            self.assertEqual(fetcher.robots_outcomes[BASE.rstrip("/")], "unavailable")
            self.assertTrue(response.closed)

    def test_retry_after_is_honored_and_recovery_is_counted(self):
        clock = Clock()
        headers = Message()
        headers["Retry-After"] = "7"
        error = HTTPError(BASE, 429, "limited", headers, None)
        with patch.object(crawler.time, "monotonic", clock.monotonic), patch.object(crawler.time, "sleep", clock.sleep), patch.object(crawler, "build_opener") as opener:
            opener.return_value.open.side_effect = [error, Response(b"ok", "text/html", BASE)]
            fetcher = crawler.PoliteFetcher(0, 1, LOGGER)
            self.assertIsNotNone(fetcher._request(BASE, BASE))
        self.assertEqual(clock.sleeps, [7])
        self.assertEqual(fetcher.request_count, 2)
        self.assertEqual(fetcher.retry_count, 1)
        self.assertEqual(fetcher.last_failure, "")

    def test_http_date_and_malformed_retry_after(self):
        fetcher = crawler.PoliteFetcher(0, 1, LOGGER)
        self.assertEqual(fetcher._retry_after("Thu, 01 Jan 1970 00:00:00 GMT"), 0)
        self.assertIsNone(fetcher._retry_after("not a date"))

    def test_retry_delay_is_deferred_instead_of_shortened(self):
        headers = Message()
        headers["Retry-After"] = "120"
        with patch.object(crawler, "build_opener") as opener, patch.object(crawler.time, "sleep") as sleep:
            opener.return_value.open.side_effect = HTTPError(BASE, 503, "wait", headers, None)
            fetcher = crawler.PoliteFetcher(0, 1, LOGGER, max_retry_wait=5)
            self.assertIsNone(fetcher._request(BASE, BASE))
            self.assertEqual(opener.return_value.open.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(fetcher.last_failure, "retry_deferred")

    def test_retries_and_requests_have_separate_caps(self):
        clock = Clock()
        with patch.object(crawler.time, "monotonic", clock.monotonic), patch.object(crawler.time, "sleep", clock.sleep), patch.object(crawler, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("offline")
            fetcher = crawler.PoliteFetcher(0, 1, LOGGER, max_retries=2, max_requests=2)
            self.assertIsNone(fetcher._request(BASE, BASE))
        self.assertEqual(opener.return_value.open.call_count, 2)
        self.assertEqual(fetcher.budget_reason, "request_limit")

    def test_wait_cannot_exceed_source_time_budget(self):
        clock = Clock()
        with patch.object(crawler.time, "monotonic", clock.monotonic), patch.object(crawler.time, "sleep", clock.sleep):
            fetcher = crawler.PoliteFetcher(0, 1, LOGGER, max_seconds=2)
            self.assertFalse(fetcher._wait(3))
            self.assertEqual(fetcher.budget_reason, "time_limit")
        self.assertEqual(clock.sleeps, [])

    def test_redirect_hops_are_charged_to_the_request_budget(self):
        fetcher = crawler.PoliteFetcher(0, 1, LOGGER, max_requests=1)
        def open_redirect(handler):
            class Opener:
                def open(self, request, **kwargs):
                    return handler.redirect_request(request, None, 302, "redirect", Message(), BASE + "next")
            return Opener()
        with patch.object(crawler, "build_opener", side_effect=open_redirect):
            self.assertIsNone(fetcher._request(BASE, BASE))
        self.assertEqual(fetcher.request_count, 1)
        self.assertEqual(fetcher.budget_reason, "request_limit")

    def test_html_truncation_and_decode_failure_never_produce_partial_pages(self):
        for response, reason in ((Response(b"x" * 2000001, "text/html", BASE), "truncated_response"),
                                 (Response(b"\xff", "text/html; charset=utf-8", BASE), "page_read_error")):
            fetcher = crawler.PoliteFetcher(0, 1, LOGGER)
            with patch.object(fetcher, "_request", return_value=response):
                self.assertIsNone(fetcher.fetch_html(BASE, BASE))
            self.assertEqual(fetcher.last_failure, reason)
            self.assertTrue(response.closed)


class CrawlAndAuditTests(unittest.TestCase):
    def test_unavailable_policy_prevents_html_requests_and_reports_failed_source(self):
        with patch.object(crawler, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("offline")
            rows, stats = crawler.discover_source(SOURCE, SUBJECTS, {"max_retries": 0}, LOGGER)
        self.assertEqual(rows, [])
        self.assertEqual(stats["outcome"], "failed")
        self.assertEqual(stats["pages_visited"], 0)
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_request_limit_stops_after_robots_without_fetching_html(self):
        with patch.object(crawler, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError(BASE + "robots.txt", 404, "absent", Message(), None)
            _, stats = crawler.discover_source(SOURCE, SUBJECTS, {"max_requests": 1}, LOGGER)
        self.assertEqual(stats["stop_reason"], "request_limit")
        self.assertEqual(stats["outcome"], "failed")
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_failed_audit_write_aborts_before_catalog_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            catalog.write_text(",".join(crawler.CATALOG_COLUMNS) + "\n")
            args = Namespace(source="school", max_pages=1, max_depth=1, delay=0, timeout=1, dry_run=False)
            class BrokenAudit(io.StringIO):
                def write(self, value):
                    raise OSError("disk full")
            real_open = Path.open
            def open_path(path, *args, **kwargs):
                return BrokenAudit() if path.name.endswith(".decisions.jsonl") else real_open(path, *args, **kwargs)
            def discover(source, subjects, limits, logger, sink):
                sink({"accepted": True})
                self.fail("Audit failure must stop processing")
            with patch.object(crawler, "CATALOG_PATH", catalog), patch.object(crawler, "load_configuration", return_value=([SOURCE], SUBJECTS)), patch.object(crawler, "create_logger", return_value=(LOGGER, root / "audit.log")), patch.object(crawler, "discover_source", side_effect=discover), patch.object(Path, "open", open_path), patch.object(crawler, "append_catalog") as append, redirect_stdout(io.StringIO()):
                self.assertEqual(crawler.run(args), 2)
                append.assert_not_called()
            summary = json.loads((root / "audit.summary.json").read_text())
            self.assertEqual(summary["outcome"], "failed")
            self.assertEqual(summary["error"], "disk full")

    def test_queue_deduplicates_and_drops_overflow_without_losing_pdf_candidates(self):
        requests = []
        class Fetcher:
            error_count = 0
            def __init__(self, *args, **kwargs):
                pass
            def robots_allowed(self, url):
                return True
            def fetch_html(self, url, base):
                requests.append(url)
                return crawler.FetchedPage(
                    '<title>Resources</title><a href="/one">one</a><a href="/one#x">one</a>'
                    '<a href="/two">two</a><a href="/three">three</a>'
                    '<a href="/history.pdf">History textbook</a>', url)
        decisions = []
        with patch.object(crawler, "PoliteFetcher", Fetcher):
            rows, stats = crawler.discover_source(SOURCE, SUBJECTS, {"max_queue": 1, "max_depth": 1}, LOGGER, decisions.append)
        self.assertEqual(requests, [BASE, BASE + "one"])
        self.assertEqual(stats["queue_peak"], 1)
        self.assertEqual(stats["queue_dropped"], 2)
        self.assertEqual(stats["stop_reason"], "queue_limit")
        self.assertEqual(stats["outcome"], "partial")
        self.assertEqual(rows[0]["source_url"], BASE + "history.pdf")
        self.assertTrue(any(row["accepted"] for row in decisions))
        self.assertTrue(any(not row["accepted"] for row in decisions))

    def run_fixture(self, outcome, *, enabled=True, dry_run=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            catalog.write_text(",".join(crawler.CATALOG_COLUMNS) + "\n")
            before = catalog.read_bytes()
            args = Namespace(source="school", max_pages=1, max_depth=1, delay=0, timeout=1, dry_run=dry_run)
            def discover(source, subjects, limits, logger, sink):
                sink({"accepted": False, "candidate_url": BASE, "score": 0, "reasons": [], "referring_url": BASE})
                return [], {"outcome": outcome, "pages_visited": 1, "errors": int(outcome == "failed")}
            with patch.object(crawler, "CATALOG_PATH", catalog), patch.object(crawler, "load_configuration", return_value=([{**SOURCE, "enabled": enabled}], SUBJECTS)), patch.object(crawler, "create_logger", return_value=(LOGGER, root / "audit.log")), patch.object(crawler, "discover_source", side_effect=discover), redirect_stdout(io.StringIO()):
                result = crawler.run(args)
            summary = json.loads((root / "audit.summary.json").read_text())
            decisions = [json.loads(line) for line in (root / "audit.decisions.jsonl").read_text().splitlines()]
            self.assertEqual(before, catalog.read_bytes())
            self.assertFalse((root / ".catalog.csv.lock").exists())
            return result, summary, decisions

    def test_failed_partial_success_empty_and_disabled_runs_have_honest_exit_codes(self):
        for outcome, code, expected in (("failed", 2, "failed"), ("partial", 1, "partial"), ("success", 0, "success")):
            result, summary, decisions = self.run_fixture(outcome)
            self.assertEqual(result, code)
            self.assertEqual(summary["exit_code"], code)
            self.assertEqual(summary["outcome"], expected)
            self.assertEqual(decisions[0]["run_id"], summary["run_id"])
            if outcome == "success":
                self.assertEqual(summary["sources"][0]["outcome"], "success_empty")
        result, summary, decisions = self.run_fixture("success", enabled=False)
        self.assertEqual(result, 2)
        self.assertEqual(summary["outcome"], "skipped")
        self.assertEqual(decisions, [])

    def test_nonfinite_or_negative_limits_are_invalid(self):
        for key, value in (("max_seconds", float("nan")), ("max_retry_wait", float("inf")),
                           ("max_requests", 0), ("max_queue", 0), ("max_retries", -1)):
            with self.assertRaises(ValueError):
                crawler._validate_limits({**crawler.DEFAULT_LIMITS, key: value})


if __name__ == "__main__":
    unittest.main()
