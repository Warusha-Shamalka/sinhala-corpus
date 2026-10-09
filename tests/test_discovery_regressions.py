import io
import json
import logging
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import yaml

from pipeline.discovery import crawler
from pipeline.discovery.filters import (
    classify_candidate, extract_grade, is_within_domain, normalize_url,
    resolve_url, should_crawl, subject_matches,
)
from pipeline.discovery.parser import Link, evaluate_link, parse_html


CONFIG = yaml.safe_load(crawler.SUBJECTS_PATH.read_text(encoding="utf-8"))
SOURCE = {"id": "sample", "name": "School", "base_url": "https://school.test/",
          "enabled": True, "verified": True, "language": "si"}
LIMITS = {"max_depth": 2, "max_pages_per_source": 10,
          "request_delay_seconds": 0, "timeout_seconds": 1}
LOGGER = logging.getLogger("discovery-regressions")


class MetadataRegressionTests(unittest.TestCase):
    def test_fixed_candidate_examples(self):
        cases = json.loads((Path(__file__).parent / "fixtures/discovery_candidates.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(path=case["path"]):
                _, decision = evaluate_link(Link(case["path"], case["title"]), "Resources",
                                            SOURCE["base_url"], SOURCE, CONFIG)
                self.assertEqual(decision.accepted, case["expected"])

    def test_filtered_listing_routes_use_actual_subject_taxonomy(self):
        for url, title in (
            ("https://school.test/teacher-guides?subject=Biology", "Biology"),
            ("https://school.test/Paper?subject=Physics", "2024 Physics past papers"),
            ("https://school.test/category/economics", "2024 Economics past papers"),
        ):
            self.assertTrue(should_crawl(url))
            self.assertFalse(classify_candidate(url, {"title": title}, CONFIG).accepted)
        for title, path in (
            ("Grade 11 History Teacher Guide", "/teacher-guides/history-grade-11"),
            ("2024 Physics past paper", "/Paper/physics-2024"),
            ("History marking scheme", "/files/history-marking-scheme.pdf"),
            ("ඉතිහාසය සටහන්", "/history-notes"),
        ):
            self.assertTrue(classify_candidate("https://school.test" + path, {"title": title}, CONFIG).accepted)

    def test_actual_taxonomy_prefers_specific_contained_names(self):
        for name, domain in (("History of Sri Lanka", "Humanities"),
                             ("Sinhala Language and Literature", "Language"),
                             ("Business and Accounting Studies", "Business Studies")):
            self.assertEqual(subject_matches(name, CONFIG), (name, domain))
        self.assertEqual(subject_matches("History of Sri Lanka and History", CONFIG), ("", ""))
        self.assertEqual(subject_matches("History and Science", CONFIG), ("", ""))

    def test_sinhala_aliases_and_boundaries(self):
        self.assertEqual(subject_matches("ඉතිහාසය සටහන්", CONFIG), ("History", "Humanities"))
        self.assertEqual(subject_matches("භෞතික විද්‍යාව", CONFIG), ("Physics", "STEM"))
        self.assertEqual(subject_matches("දේශපාලන විද්‍යාව", CONFIG), ("Political Science", "Social Science"))
        self.assertEqual(subject_matches("ඉතිහාසයේ", CONFIG), ("", ""))
        self.assertEqual(subject_matches("ඉතිහාසය සහ විද්‍යාව", CONFIG), ("", ""))

    def test_distinct_subjects_remain_distinct(self):
        for text in ("Eastern Music and Oriental Music", "Dancing and Dancing Indigenous",
                     "Buddhism and Buddhist Civilization", "Christianity and Catholicism"):
            self.assertEqual(subject_matches(text, CONFIG), ("", ""))

    def test_grade_ranges_and_conflicts(self):
        cases = {
            "Grade 8-9 History": ("8-9", "Junior Secondary"),
            "Grades 10–11": ("10-11", "O-Level"),
            "8 ශ්‍රේණිය ඉතිහාසය": ("8", "Junior Secondary"),
            "ශ්‍රේණිය 8": ("8", "Junior Secondary"),
            "10-11 ශ්‍රේණිය": ("10-11", "O-Level"),
            "උසස් පෙළ ආර්ථික විද්‍යාව": ("12-13", "A-Level"),
            "සාමාන්‍ය පෙළ": ("10-11", "O-Level"),
            "GCE O / L Grade 11": ("11", "O-Level"),
            "Grade 8 Grade 9": ("", ""),
            "Grade 8 O/L": ("", ""),
            "A/L and O/L": ("", ""),
            "Grade 15": ("", ""),
            "Grade 9-8": ("", ""),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract_grade(text, CONFIG), expected)

    def test_source_language_is_only_a_hint(self):
        candidate, _ = evaluate_link(Link("/english.pdf", "English History textbook"),
                                     "Resources", SOURCE["base_url"], SOURCE, CONFIG)
        self.assertEqual(candidate["language"], "")
        self.assertEqual(candidate["_language_hint"], "si")


class URLAndParserRegressionTests(unittest.TestCase):
    def test_unicode_and_space_urls_are_request_safe_and_idempotent(self):
        url = normalize_url("https://school.test/files/ඉතිහාසය සටහන්.pdf?label=අ බ")
        self.assertTrue(url.isascii())
        self.assertNotIn(" ", url)
        self.assertEqual(normalize_url(url), url)
        candidate, _ = evaluate_link(Link(url, "Download"), "Resources", SOURCE["base_url"], SOURCE, CONFIG)
        self.assertEqual(candidate["subject"], "History")

    def test_invalid_urls_are_rejected_by_all_entrypoints(self):
        for url in ("https://[bad/path", "https://school.test:bad/a", "ftp://school.test/a.pdf",
                    "javascript:alert(1)", "https://user:secret@school.test/", "https://bad host/a"):
            with self.subTest(url=url):
                self.assertEqual(normalize_url(url), "")
                self.assertEqual(resolve_url(SOURCE["base_url"], url), "")
                self.assertFalse(should_crawl(url))
                self.assertFalse(is_within_domain(url, SOURCE["base_url"]))
                self.assertFalse(classify_candidate(url, {"title": "History textbook"}, CONFIG).accepted)
                self.assertIsNone(evaluate_link(Link(url, "History textbook"), "Resources",
                                               SOURCE["base_url"], SOURCE, CONFIG)[0])

    def test_noncontent_tags_cannot_supply_link_evidence(self):
        page = parse_html('<title>Resources</title><script>History textbook</script>'
                          '<style>Grade 8</style><template><a href="/hidden.pdf">History</a></template>'
                          '<a href="/opaque">Download</a>')
        self.assertEqual(len(page.links), 1)
        self.assertNotIn("History", page.text)
        self.assertNotIn("Grade", page.links[0].context)
        self.assertIsNone(evaluate_link(page.links[0], page.title, SOURCE["base_url"], SOURCE, CONFIG)[0])

    def test_redirected_response_retains_final_url(self):
        class Response(io.BytesIO):
            headers = Message()
            headers["Content-Type"] = "text/html; charset=utf-8"

            def geturl(self):
                return "https://school.test/resources/"

        fetcher = crawler.PoliteFetcher(0, 1, LOGGER)
        with patch.object(fetcher, "_request", return_value=Response(b'<a href="history.pdf">History</a>')):
            page = fetcher.fetch_html(SOURCE["base_url"], SOURCE["base_url"])
        self.assertEqual(page.final_url, "https://school.test/resources/")
        self.assertIn("history.pdf", page.html)

    def test_crawl_survives_bad_links_and_resolves_redirects(self):
        class Fetcher:
            error_count = 0
            requested = []

            def __init__(self, *args, **kwargs):
                pass

            def robots_allowed(self, url):
                return True

            def fetch_html(self, url, base):
                self.requested.append(url)
                return crawler.FetchedPage(
                    '<title>Resources</title><a href="https://[bad/x">bad</a>'
                    '<a href="ftp://school.test/history.pdf">History textbook</a>'
                    '<a href="history.pdf">8 ශ්‍රේණිය ඉතිහාසය පෙළපොත</a>'
                    '<a href="/category/history">History Category</a>',
                    "https://school.test/resources/",
                )

        with patch.object(crawler, "PoliteFetcher", Fetcher):
            rows, _ = crawler.discover_source(SOURCE, CONFIG, {**LIMITS, "max_depth": 0}, LOGGER)
        self.assertEqual(Fetcher.requested, [SOURCE["base_url"]])
        self.assertEqual([row["source_url"] for row in rows], ["https://school.test/resources/history.pdf"])
        self.assertEqual(rows[0]["grade"], "8")
        self.assertEqual(rows[0]["subject"], "History")


class ConfigurationRegressionTests(unittest.TestCase):
    def load(self, sources, subjects):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path, subject_path, catalog_path = (root / name for name in ("sources.yaml", "subjects.yaml", "catalog.csv"))
            source_path.write_text(yaml.safe_dump(sources), encoding="utf-8")
            subject_path.write_text(yaml.safe_dump(subjects), encoding="utf-8")
            catalog_path.write_text(",".join(crawler.CATALOG_COLUMNS) + "\n", encoding="utf-8")
            with patch.object(crawler, "SOURCES_PATH", source_path), patch.object(crawler, "SUBJECTS_PATH", subject_path), patch.object(crawler, "CATALOG_PATH", catalog_path):
                return crawler.load_configuration()

    def test_actual_configuration_loads(self):
        self.assertEqual(len(crawler.load_configuration()[0]), 3)

    def test_disabled_unverified_source_can_await_a_url(self):
        sources, _ = self.load({"sources": [{**SOURCE, "enabled": False, "verified": False, "base_url": ""}]}, CONFIG)
        self.assertEqual(sources[0]["base_url"], "")

    def test_invalid_configuration_is_actionable(self):
        invalid = [
            (42, CONFIG),
            ({"sources": [None]}, CONFIG),
            ({"sources": [SOURCE, SOURCE]}, CONFIG),
            ({"sources": [{**SOURCE, "verified": "true"}]}, CONFIG),
            ({"sources": [{**SOURCE, "base_url": "https://[bad"}]}, CONFIG),
            ({"sources": [SOURCE]}, {"domains": {"STEM": None}}),
            ({"sources": [SOURCE]}, {**CONFIG, "education_levels": {"O-Level": None}}),
            ({"sources": [SOURCE]}, {**CONFIG, "grade_markers": []}),
        ]
        for sources, subjects in invalid:
            with self.subTest(sources=sources, subjects=subjects):
                with self.assertRaises(ValueError):
                    self.load(sources, subjects)


if __name__ == "__main__":
    unittest.main()
