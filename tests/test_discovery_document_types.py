import unittest

import yaml

from pipeline.discovery import crawler
from pipeline.discovery.filters import classify_candidate, detect_document_type


CONFIG = yaml.safe_load(crawler.SUBJECTS_PATH.read_text(encoding="utf-8"))


class DocumentTypeContextTests(unittest.TestCase):
    def test_version_wording_preserves_the_named_resource_type(self):
        cases = {
            "Physics new syllabus notes": "lesson",
            "Chemistry old syllabus workbook": "workbook",
            "Grade 10 History revised syllabus worksheet": "workbook",
            "Biology updated curriculum lesson": "lesson",
            "Physics new syllabus 2024 paper": "past_paper",
            "Grade 12 Physics paper revised curriculum": "past_paper",
            "Sinhala new syllabus textbook": "textbook",
            "Biology new syllabus teacher guide": "teacher_guide",
            "Physics old syllabus marking scheme": "marking_scheme",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(detect_document_type("https://school.test/file.pdf", title), expected)

    def test_standalone_syllabus_documents_are_preserved(self):
        for title in ("Physics syllabus", "Biology new syllabus", "Chemistry revised curriculum",
                      "History විෂය නිර්දේශය", "Physics new syllabus notes and official syllabus"):
            with self.subTest(title=title):
                self.assertEqual(detect_document_type("https://school.test/file.pdf", title), "syllabus")

    def test_url_and_title_each_supply_context(self):
        self.assertEqual(detect_document_type("https://school.test/new-syllabus-physics-notes.pdf", "Download"), "lesson")
        self.assertEqual(detect_document_type("https://school.test/new-syllabus.pdf", "Physics notes"), "lesson")
        self.assertEqual(detect_document_type("https://school.test/syllabus.pdf", "Physics notes"), "syllabus")

    def test_phrase_boundaries_and_unknown_resources_are_conservative(self):
        self.assertEqual(detect_document_type("https://school.test/file.pdf", "Physics overview"), "other")
        self.assertEqual(detect_document_type("https://school.test/file.pdf", "Physics renew syllabus notes"), "syllabus")
        self.assertEqual(detect_document_type("https://school.test/file.pdf", "New syllabuses notes"), "lesson")

    def test_candidate_audit_explains_suppressed_version_label(self):
        decision = classify_candidate("https://school.test/biology-new-syllabus-notes.pdf",
                                      {"title": "Biology new syllabus notes"}, CONFIG)
        self.assertTrue(decision.accepted)
        self.assertEqual((decision.subject, decision.document_type), ("Biology", "lesson"))
        self.assertIn("syllabus_version_wording_not_used_as_document_type", decision.reasons)
        syllabus = classify_candidate("https://school.test/biology-new-syllabus.pdf",
                                      {"title": "Biology new syllabus"}, CONFIG)
        self.assertEqual(syllabus.document_type, "syllabus")
        self.assertNotIn("syllabus_version_wording_not_used_as_document_type", syllabus.reasons)
