import csv
import logging
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml  # type: ignore[import-not-found]

from pipeline.discovery import crawler
from pipeline.discovery.filters import (
    classify_candidate,
    detect_document_type,
    extract_grade,
    is_candidate,
    is_within_domain,
    normalize_url,
    should_crawl,
    subject_matches,
)


SUBJECTS = {
    "domains": {
        "Humanities": {"subjects": [
            {"name": "History", "grade_min": 6, "grade_max": 13},
            {"name": "Economics", "grade_min": 12, "grade_max": 13},
        ]},
        "STEM": {"subjects": [
            {"name": "Science", "grade_min": 6, "grade_max": 11},
            {"name": "Physics", "grade_min": 12, "grade_max": 13},
        ]},
    },
    "education_levels": {
        "Junior Secondary": {"grade_min": 6, "grade_max": 9},
        "O-Level": {"grade_min": 10, "grade_max": 11},
        "A-Level": {"grade_min": 12, "grade_max": 13},
    },
}


class DiscoveryFilterTests(unittest.TestCase):
    def candidate(self, title, url=None, surrounding=""):
        url = url or f"https://school.test/{title.lower().replace(' ', '-')}"
        return classify_candidate(url, {
            "title": title,
            "anchor_text": title,
            "filename": url.rsplit("/", 1)[-1],
            "surrounding_text": surrounding,
        }, SUBJECTS)

    def test_url_normalization_removes_fragment_and_default_port(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.COM:443/a/../b#section"),
            "https://example.com/b",
        )

    def test_domain_restriction_rejects_external_and_lookalike_hosts(self):
        base = "https://school.example.org/"
        self.assertTrue(is_within_domain("https://learn.school.example.org/page", base))
        self.assertFalse(is_within_domain("https://example.org/page", base))
        self.assertFalse(is_within_domain("https://school.example.org.attacker.net/", base))

    def test_subject_matching_uses_config_and_avoids_ambiguous_matches(self):
        self.assertEqual(subject_matches("Grade 8 History", SUBJECTS), ("History", "Humanities"))
        self.assertEqual(subject_matches("History and Science", SUBJECTS), ("", ""))

    def test_grade_extraction_and_education_level(self):
        self.assertEqual(extract_grade("History Grade 10", SUBJECTS), ("10", "O-Level"))
        self.assertEqual(extract_grade("History textbook", SUBJECTS), ("", ""))

    def test_document_type_detection(self):
        self.assertEqual(detect_document_type("https://x.test/a.pdf", ""), "other")
        self.assertEqual(detect_document_type("https://x.test/history", "History past paper"), "past_paper")
        self.assertEqual(detect_document_type("https://x.test/Paper", "Paper Hub"), "other")

    def test_navigation_pages_rejected_but_remain_crawlable(self):
        for title, url in (
            ("Home", "https://school.test/"),
            ("About", "https://school.test/about"),
            ("Contact", "https://school.test/contact"),
            ("Paper Hub", "https://school.test/Paper"),
            ("Note Hub", "https://school.test/Note"),
            ("Teacher Guides", "https://school.test/teacher-guides"),
            ("History Category", "https://school.test/category/history"),
        ):
            with self.subTest(title=title):
                decision = self.candidate(title, url)
                self.assertFalse(decision.accepted)
                self.assertTrue(should_crawl(url))

    def test_paper_hub_and_category_routes_rejected(self):
        for title, url in (
            ("Paper Hub", "https://school.test/Paper"),
            ("Paper", "https://school.test/Category/paper_hub/PaperSubject?subject=History"),
        ):
            with self.subTest(url=url):
                decision = self.candidate(title, url)
                self.assertFalse(decision.accepted)
                self.assertLess(decision.score, 4)

    def test_direct_pdf_is_accepted_as_strong_evidence(self):
        decision = self.candidate("Download", "https://school.test/files/history-resource.pdf")
        self.assertTrue(decision.accepted)
        self.assertGreaterEqual(decision.score, 4)

    def test_past_paper_and_marking_scheme_are_accepted(self):
        paper = self.candidate("2024 A/L Economics Paper")
        marking = self.candidate("2024 O/L History Marking Scheme")
        self.assertTrue(paper.accepted)
        self.assertEqual(paper.document_type, "past_paper")
        self.assertTrue(marking.accepted)
        self.assertEqual(marking.document_type, "marking_scheme")

    def test_teacher_guide_is_accepted_with_controlled_type(self):
        guide = self.candidate("Grade 11 History Teacher Guide")
        self.assertTrue(guide.accepted)
        self.assertEqual(guide.document_type, "teacher_guide")

    def test_subject_matching_and_unknown_subject_behavior(self):
        economics = self.candidate("2024 A/L Economics Paper")
        unknown = self.candidate("2024 A/L General Knowledge Paper")
        self.assertEqual(economics.subject, "Economics")
        self.assertEqual(economics.domain, "Humanities")
        self.assertTrue(unknown.accepted)
        self.assertEqual(unknown.subject, "")

    def test_grade_and_level_detection(self):
        self.assertEqual(extract_grade("Grade 8 History", SUBJECTS), ("8", "Junior Secondary"))
        self.assertEqual(extract_grade("GCE O/L History Paper", SUBJECTS), ("10-11", "O-Level"))
        self.assertEqual(extract_grade("Advanced Level Economics", SUBJECTS), ("12-13", "A-Level"))
        self.assertEqual(extract_grade("2024 History Paper", SUBJECTS), ("", ""))

    def test_category_page_is_not_candidate_but_resource_route_is(self):
        category = self.candidate("Economics Past Papers", "https://school.test/category/economics")
        resource = self.candidate(
            "2024 A/L Economics Paper", "https://school.test/Paper/2024-al-economics"
        )
        nested_lesson = self.candidate(
            "Grade 8 History Lesson 05", "https://school.test/Paper/grade-8-history-lesson-05"
        )
        self.assertFalse(category.accepted)
        self.assertTrue(should_crawl("https://school.test/category/economics"))
        self.assertTrue(resource.accepted)
        self.assertTrue(nested_lesson.accepted)

    def test_filtered_listing_routes_and_incidental_context_are_rejected(self):
        teacher_list = self.candidate(
            "Biology", "https://school.test/teacher-guides?subject=Biology"
        )
        timetable = self.candidate(
            "2027 A/L Timetable", "https://school.test/wait", "download past paper resources"
        )
        self.assertFalse(teacher_list.accepted)
        self.assertFalse(timetable.accepted)

    def test_sinhala_educational_signal_is_supported(self):
        decision = self.candidate("ඉතිහාසය සටහන්", "https://school.test/history-notes")
        self.assertTrue(decision.accepted)

    def test_duplicate_normalized_urls_and_external_domain(self):
        records = [{"source_url": "https://school.test/resource#page"}]
        self.assertIn("https://school.test/resource", crawler.catalog_url_set(records))
        self.assertFalse(is_within_domain("https://evil.test/resource", "https://school.test/"))
        self.assertFalse(is_candidate(
            "https://school.test/about", {"title": "About"}, SUBJECTS
        ))


class CatalogTests(unittest.TestCase):
    def test_catalog_duplicate_urls_and_stable_next_id(self):
        records = [
            {"doc_id": "LK-EDU-000001", "source_url": "https://example.org/a#old"},
            {"doc_id": "LK-EDU-000009", "source_url": "https://example.org/b"},
        ]
        self.assertEqual(crawler.catalog_url_set(records), {
            "https://example.org/a", "https://example.org/b",
        })
        self.assertEqual(crawler.next_document_number(records), 10)
        self.assertEqual(crawler.make_doc_id(10), "LK-EDU-000010")

    def test_breadth_first_discovery_never_fetches_resources_or_external_hosts(self):
        source = {"id": "sample", "name": "Sample", "base_url": "https://sample.test/", "language": "si"}
        pages = {
            "https://sample.test/": (
                '<html><title>School learning resources</title><body>'
                '<a href="/grade-8-history">Grade 8 History lessons</a>'
                '<a href="/files/history.pdf">Grade 8 History textbook PDF</a>'
                '<a href="https://other.test/grade-8-history">Grade 8 History external</a>'
                '</body></html>'
            ),
            "https://sample.test/grade-8-history": (
                '<html><title>Grade 8 History lessons</title><body>Lesson materials</body></html>'
            ),
        }

        class FakeFetcher:
            requested = []

            def __init__(self, delay, timeout, logger, **kwargs):
                self.error_count = 0

            def robots_allowed(self, url):
                return True

            def fetch_html(self, url, base_url):
                self.requested.append(url)
                return crawler.FetchedPage(pages[url], url) if url in pages else None

        logger = logging.getLogger("discovery-bfs-test")
        with patch.object(crawler, "PoliteFetcher", FakeFetcher):
            candidates, stats = crawler.discover_source(source, SUBJECTS, {
                "max_depth": 2, "max_pages_per_source": 10,
                "request_delay_seconds": 0.0, "timeout_seconds": 1.0,
            }, logger)
        urls = {candidate["source_url"] for candidate in candidates}
        self.assertIn("https://sample.test/files/history.pdf", urls)
        self.assertNotIn("https://other.test/grade-8-history", urls)
        self.assertEqual(FakeFetcher.requested, [
            "https://sample.test/", "https://sample.test/grade-8-history",
        ])
        self.assertEqual(stats["pages_visited"], 2)

    def test_dry_run_does_not_modify_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_file = root / "sources.yaml"
            subjects_file = root / "subjects.yaml"
            catalog = root / "documents.csv"
            source_file.write_text(yaml.safe_dump({"sources": [{
                "id": "sample", "name": "Sample", "base_url": "https://sample.test/",
                "enabled": True, "verified": True, "language": "si",
            }]}), encoding="utf-8")
            subjects_file.write_text(yaml.safe_dump(SUBJECTS), encoding="utf-8")
            catalog.write_text(",".join(crawler.CATALOG_COLUMNS) + "\n", encoding="utf-8")
            before = catalog.read_bytes()
            candidate = {"title": "Grade 8 History textbook", "subject": "History",
                         "domain": "Humanities", "grade": "8", "education_level": "Junior Secondary",
                         "document_type": "textbook", "source": "Sample",
                         "source_url": "https://sample.test/history.pdf", "language": "si",
                         "status": "DISCOVERED"}
            args = Namespace(source="sample", max_depth=3, max_pages=10, delay=0.0,
                             timeout=1.0, dry_run=True)
            logger = logging.getLogger("discovery-test")
            with (
                patch.object(crawler, "SOURCES_PATH", source_file),
                patch.object(crawler, "SUBJECTS_PATH", subjects_file),
                patch.object(crawler, "CATALOG_PATH", catalog),
                patch.object(crawler, "create_logger", return_value=(logger, root / "run.log")),
                patch.object(crawler, "discover_source", return_value=([candidate], {
                    "pages_visited": 0, "pages_skipped": 0,
                    "candidates_discovered": 1, "errors": 0,
                })),
                patch.object(crawler, "append_catalog") as append_catalog,
            ):
                self.assertEqual(crawler.run(args), 0)
            append_catalog.assert_not_called()
            self.assertEqual(catalog.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()