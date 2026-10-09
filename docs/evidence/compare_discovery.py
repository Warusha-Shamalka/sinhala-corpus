"""Compare fixed independent fixtures with reviewed commit 373ce62, offline.

Run: python3 -B docs/evidence/compare_discovery.py
Loads trusted repository Python from Git; no network or catalog writes.
"""

import json
import subprocess
import sys
import types
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline.discovery import parser


def baseline_file(path):
    return subprocess.check_output(["git", "show", f"373ce62:{path}"], cwd=ROOT)


def main():
    package = types.ModuleType("review_baseline")
    package.__path__ = []
    sys.modules[package.__name__] = package
    for name in ("filters", "parser"):
        module = types.ModuleType(f"review_baseline.{name}")
        module.__package__ = package.__name__
        sys.modules[module.__name__] = module
        exec(compile(baseline_file(f"pipeline/discovery/{name}.py"), f"baseline/{name}.py", "exec"), module.__dict__)
    old = sys.modules["review_baseline.parser"]
    old_config = yaml.safe_load(baseline_file("configs/subjects.yaml"))
    new_config = yaml.safe_load((ROOT / "configs/subjects.yaml").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "tests/fixtures/discovery_candidates.json").read_text(encoding="utf-8"))
    for name, implementation, config in (("373ce62", old, old_config), ("working tree", parser, new_config)):
        accepted = correct = true_positives = 0
        for case in cases:
            _, decision = implementation.evaluate_link(
                implementation.Link(case["path"], case["title"]), "Resources", "https://school.test/",
                {"name": "School", "language": "si"}, config,
            )
            accepted += decision.accepted
            correct += decision.accepted == case["expected"]
            true_positives += decision.accepted and case["expected"]
        positive_count = sum(case["expected"] for case in cases)
        print(json.dumps({"revision": name, "examples": len(cases), "accepted": accepted,
                          "correct": correct, "precision": true_positives / accepted,
                          "fixture_recall": true_positives / positive_count}))


if __name__ == "__main__":
    main()
