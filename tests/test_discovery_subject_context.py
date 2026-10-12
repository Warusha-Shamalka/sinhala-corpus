import copy
import unittest

import yaml

from pipeline.discovery import crawler
from pipeline.discovery.filters import extract_medium_hint, subject_matches
from pipeline.discovery.parser import Link, evaluate_link
from tests import test_discovery_regressions as regressions


CONFIG = yaml.safe_load(crawler.SUBJECTS_PATH.read_text(encoding="utf-8"))


class SubjectContextTests(unittest.TestCase):
    def test_medium_wording_does_not_become_a_subject(self):
        for title in ("Physics Sinhala medium notes", "Sinhala-medium Physics notes",
                      "Physics medium Sinhala", "Physics සිංහල මාධ්‍යයෙන්"):
            with self.subTest(title=title):
                self.assertEqual(subject_matches(title, CONFIG), ("Physics", "STEM"))
                self.assertEqual(extract_medium_hint(title, CONFIG), "si")
        self.assertEqual(subject_matches("Sinhala medium notes", CONFIG), ("", ""))

    def test_explicit_sinhala_subject_survives_medium_masking(self):
        for title, subject in (
            ("Sinhala Language and Literature Sinhala medium textbook", "Sinhala Language and Literature"),
            ("Sinhala Sinhala medium notes", "Sinhala"),
            ("Sinhala Language and Literature English medium", "Sinhala Language and Literature"),
        ):
            self.assertEqual(subject_matches(title, CONFIG), (subject, "Language"))

    def test_conflicting_medium_and_independent_subjects_remain_unknown(self):
        self.assertEqual(extract_medium_hint("Physics Sinhala medium Tamil medium", CONFIG), "")
        self.assertEqual(subject_matches("History and Physics Sinhala medium", CONFIG), ("", ""))
        self.assertEqual(extract_medium_hint("Sinhala notes", CONFIG), "")

    def test_biology_history_contexts_are_not_history_subjects(self):
        for title in ("Biology life history notes", "Biology evolutionary history textbook",
                      "Biology biological history notes"):
            self.assertEqual(subject_matches(title, CONFIG), ("Biology", "STEM"))
        self.assertEqual(subject_matches("Life history notes", CONFIG), ("", ""))
        self.assertEqual(subject_matches("History of Sri Lanka textbook", CONFIG),
                         ("History of Sri Lanka", "Humanities"))
        self.assertEqual(subject_matches("Life history and History textbook", CONFIG), ("History", "Humanities"))
        self.assertEqual(subject_matches("Biology and History textbook", CONFIG), ("", ""))

    def test_candidate_has_explainable_hint_without_verified_language(self):
        source = {"name": "School", "language": "ta"}
        candidate, decision = evaluate_link(
            Link("/physics-sinhala-medium-grade-12.pdf", "Grade 12 Physics Sinhala medium notes"),
            "Other subjects", "https://school.test/", source, CONFIG)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["subject"], "Physics")
        self.assertEqual(candidate["language"], "")
        self.assertEqual(candidate["_language_hint"], "ta")
        self.assertEqual(candidate["_medium_hint"], "si")
        self.assertEqual(decision.medium_hint, "si")
        self.assertIn("explicit_medium_hint:si (unverified; not a subject)", decision.reasons)

    def test_context_rules_are_configured_and_boundaries_are_respected(self):
        config = copy.deepcopy(CONFIG)
        del config["medium_markers"]
        self.assertEqual(subject_matches("Sinhala medium Physics", config), ("", ""))
        self.assertEqual(subject_matches("Physics Sinhala mediumship", CONFIG), ("", ""))
        history = next(item for item in config["domains"]["Humanities"]["subjects"] if item["name"] == "History")
        del history["excluded_phrases"]
        self.assertEqual(subject_matches("Biology life history notes", config), ("", ""))


class ContextConfigurationTests(unittest.TestCase):
    load = regressions.ConfigurationRegressionTests.load

    def test_invalid_context_configuration_is_rejected(self):
        for markers in ([], {"si": "Sinhala medium"}, {"": ["Sinhala medium"]}, {"si": [None]}):
            with self.subTest(markers=markers), self.assertRaises(ValueError):
                self.load({"sources": []}, {**CONFIG, "medium_markers": markers})
        config = copy.deepcopy(CONFIG)
        config["domains"]["STEM"]["subjects"][0]["excluded_phrases"] = "not a list"
        with self.assertRaises(ValueError):
            self.load({"sources": []}, config)
