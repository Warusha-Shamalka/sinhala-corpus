import csv
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from pipeline.quality.discovery_review import FIELDS, make_sample, read_population, report_review


class DiscoveryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources.yaml"
        self.sources.write_text(yaml.safe_dump({"sources": [{"id": "school", "base_url": "https://school.test/",
                                                            "enabled": True, "verified": True}]}))
        self.decisions = self.root / "run.decisions.jsonl"
        self.root.joinpath("run.summary.json").write_text(json.dumps({"schema_version": "discovery-run-1",
                                                                      "run_id": "run", "outcome": "partial"}))
        self.rows = [self.decision("https://school.test/" + str(i) + ".pdf", True, 5) for i in range(8)]
        self.rows += [self.decision("https://school.test/high.pdf", True, 12),
                      self.decision("https://school.test/category", False, 0),
                      self.decision("https://external.test/a", False, 5)]
        self.save()

    def decision(self, url, accepted, score):
        return {"schema_version": "discovery-decision-1", "run_id": "run", "source_id": "school",
                "candidate_url": url, "accepted": accepted, "score": score, "title": "History resource",
                "referring_url": "https://school.test/", "reasons": [], "evidence": {}}

    def save(self):
        self.decisions.write_text("".join(json.dumps(row) + "\n" for row in self.rows))

    def sample(self, name="review", **kwargs):
        folder = self.root / name
        manifest = make_sample([self.decisions], self.sources, folder, **kwargs)
        return folder, manifest

    def edit(self, folder, edit):
        with (folder / "review.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        edit(rows)
        with (folder / "review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_sampling_reproducible_and_stratum_sizes_capped(self):
        first, a = self.sample("first", per_stratum=3, seed=17)
        second, b = self.sample("second", per_stratum=3, seed=17)
        self.assertEqual(a["sample_rows"], b["sample_rows"])
        self.assertEqual((first / "review.csv").read_bytes(), (second / "review.csv").read_bytes())
        self.assertEqual(a["population_urls"], 11)
        self.assertEqual(a["population_accepted"], 9)
        self.assertTrue(all(row["review_label"] == "" for row in a["sample_rows"]))
        self.assertEqual(max(stratum["sample"] for stratum in a["strata"].values()), 3)

    def test_repeated_observations_deduplicate_and_acceptance_wins(self):
        url = self.rows[0]["candidate_url"]
        self.rows.insert(0, self.decision(url + "#fragment", False, 0))
        self.save()
        population, _ = read_population([self.decisions], self.sources)
        record = next(row for row in population if row["candidate_url"] == url)
        self.assertEqual(len(population), 11)
        self.assertEqual(record["observations"], "2")
        self.assertEqual(record["conflicting_decisions"], "true")
        self.assertEqual(record["predicted_accepted"], "true")

    def test_unreviewed_sample_never_reports_accuracy_or_passes_gate(self):
        folder, _ = self.sample()
        report = report_review(folder)
        self.assertEqual(report["status"], "pending_review")
        self.assertIsNone(report["weighted_accepted_precision"]["estimate"])
        self.assertEqual(report["weighted_accepted_precision"]["unresolved_label_bounds"], [0, 1])
        self.assertEqual(report["gate"], "NOT_APPROVED")

    def test_report_weights_population_not_unbalanced_sample(self):
        folder, _ = self.sample(per_stratum=1)
        def label(rows):
            for row in rows:
                row.update(review_label="non_resource" if row["score_band"] == "high_score" or row["scope"] == "external_control" else "resource",
                           reviewer="fixture", review_notes="independent fixture judgment")
        self.edit(folder, label)
        report = report_review(folder)
        self.assertEqual(report["status"], "complete")
        self.assertAlmostEqual(report["weighted_accepted_precision"]["estimate"], 8 / 9)
        self.assertEqual(report["weighted_rejected_resource_rate"]["estimate"], 1)
        self.assertEqual(report["weighted_rejected_resource_rate"]["population"], 1)
        self.assertEqual(report["gate"], "NOT_APPROVED")

    def test_unsure_and_inaccessible_remain_unresolved(self):
        folder, _ = self.sample(per_stratum=1)
        def label(rows):
            for index, row in enumerate(rows):
                row.update(review_label="unsure" if index % 2 else "inaccessible", reviewer="fixture", review_notes="cannot verify")
        self.edit(folder, label)
        report = report_review(folder)
        self.assertEqual(report["unresolved_rows"], report["sample_rows"])
        self.assertIsNone(report["weighted_accepted_precision"]["estimate"])

    def test_modified_evidence_missing_duplicate_rows_or_labels_are_rejected(self):
        edits = [lambda rows: rows[0].update(candidate_url="https://school.test/changed"),
                 lambda rows: rows.pop(), lambda rows: rows.append(dict(rows[0])),
                 lambda rows: rows[0].update(review_label="correct"),
                 lambda rows: rows[0].update(review_label="resource")]
        for index, edit in enumerate(edits):
            folder, _ = self.sample(f"invalid-{index}")
            self.edit(folder, edit)
            with self.assertRaises(ValueError):
                report_review(folder)

    def test_sample_cannot_overwrite_existing_review(self):
        folder, _ = self.sample()
        before = (folder / "review.csv").read_bytes()
        with self.assertRaises(FileExistsError):
            make_sample([self.decisions], self.sources, folder)
        self.assertEqual((folder / "review.csv").read_bytes(), before)

    def test_mismatched_run_and_nonboolean_decisions_rejected(self):
        for field, value in (("run_id", "different"), ("accepted", "true"), ("score", "5")):
            self.rows[0] = self.decision("https://school.test/0.pdf", True, 5)
            self.rows[0][field] = value
            self.save()
            with self.assertRaises(ValueError):
                read_population([self.decisions], self.sources)

    def test_unknown_or_unapproved_sources_rejected(self):
        self.rows[0]["source_id"] = "unknown"
        self.save()
        with self.assertRaises(ValueError):
            read_population([self.decisions], self.sources)

    def test_accepted_external_url_is_invalid(self):
        self.rows[-1]["accepted"] = True
        self.save()
        with self.assertRaises(ValueError):
            read_population([self.decisions], self.sources)


if __name__ == "__main__":
    unittest.main()
