"""Offline stratified sampling and reporting for independent discovery review."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from pipeline.discovery.filters import DOCUMENT_EXTENSIONS, is_within_domain, normalize_url

FIELDS = (
    "audit_id", "source_id", "candidate_url", "predicted_accepted", "scope", "format",
    "text_hint", "score_band", "stratum", "population_count", "sample_count", "title",
    "score", "subject", "grade", "document_type", "referring_url", "reasons", "evidence",
    "observations", "conflicting_decisions", "review_label", "reviewer", "review_notes", "review_evidence",
)
EDITABLE = {"review_label", "reviewer", "review_notes", "review_evidence"}
LABELS = {"", "resource", "non_resource", "unsure", "inaccessible"}
ROOT = Path(__file__).resolve().parents[2]


def read_population(paths: list[Path], sources_path: Path) -> tuple[list[dict], dict]:
    configuration = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in configuration["sources"]}
    unique, inputs, skipped = {}, [], 0
    for path in sorted(paths):
        if not path.name.endswith(".decisions.jsonl"):
            raise ValueError("Input must be a discovery .decisions.jsonl file")
        summary_path = path.with_name(path.name.removesuffix(".decisions.jsonl") + ".summary.json")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("schema_version") != "discovery-run-1":
            raise ValueError("Unsupported discovery summary schema")
        inputs.append({"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                       "run_id": summary["run_id"], "run_outcome": summary["outcome"]})
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            row = json.loads(line)
            if row.get("schema_version") != "discovery-decision-1" or row.get("run_id") != summary["run_id"]:
                raise ValueError(f"Invalid decision schema/run ID at {path}:{line_number}")
            if type(row.get("accepted")) is not bool or type(row.get("score")) is not int:
                raise ValueError(f"Invalid decision types at {path}:{line_number}")
            source_id = row["source_id"]
            source = sources.get(source_id)
            if not source or source.get("enabled") is not True or source.get("verified") is not True:
                raise ValueError(f"Source {source_id!r} is not in the current crawl-approved configuration")
            url = normalize_url(row["candidate_url"])
            if not url:
                skipped += 1
                continue
            in_scope = is_within_domain(url, source["base_url"])
            if row["accepted"] and not in_scope:
                raise ValueError("Accepted URL is outside its configured source domain")
            key = (source_id, url)
            if key not in unique:
                unique[key] = {"record": row, "url": url, "observations": 1,
                               "decisions": {row["accepted"]}, "in_scope": in_scope}
            else:
                item = unique[key]
                item["observations"] += 1
                item["decisions"].add(row["accepted"])
                # Match discovery's first accepted record, rather than majority vote.
                if row["accepted"] and not item["record"]["accepted"]:
                    item["record"] = row
    records = []
    for key, item in sorted(unique.items()):
        row, url = item["record"], item["url"]
        accepted = str(row["accepted"]).lower()
        scope = "in_domain" if item["in_scope"] else "external_control"
        file_format = "document_url" if urlsplit(url).path.lower().endswith(DOCUMENT_EXTENSIONS) else "html_or_opaque"
        text = str(row.get("title", "")) + json.dumps(row.get("evidence", {}), ensure_ascii=False)
        hint = "sinhala_present" if any("\u0d80" <= char <= "\u0dff" for char in text) else "no_sinhala_signal"
        band = "below_threshold" if row["score"] < 4 else "near_threshold" if row["score"] <= 6 else "high_score"
        stratum = "|".join((key[0], accepted, scope, file_format, hint, band))
        record = {name: "" for name in FIELDS}
        record.update(audit_id=hashlib.sha256((key[0] + "\n" + url).encode()).hexdigest()[:20],
                      source_id=key[0], candidate_url=url, predicted_accepted=accepted, scope=scope,
                      format=file_format, text_hint=hint, score_band=band, stratum=stratum,
                      title=row.get("title", ""), score=str(row["score"]), subject=row.get("subject", ""),
                      grade=row.get("grade", ""), document_type=row.get("document_type", ""),
                      referring_url=row["referring_url"], reasons=json.dumps(row["reasons"], ensure_ascii=False),
                      evidence=json.dumps(row.get("evidence", {}), ensure_ascii=False, sort_keys=True),
                      observations=str(item["observations"]), conflicting_decisions=str(len(item["decisions"]) > 1).lower())
        records.append(record)
    return records, {"inputs": inputs, "invalid_url_observations_excluded": skipped,
                     "sources_config_sha256": hashlib.sha256(sources_path.read_bytes()).hexdigest(),
                     "source_bases": {source_id: source["base_url"] for source_id, source in sources.items()}}


def make_sample(paths: list[Path], sources_path: Path, output: Path, *, per_stratum: int = 12, seed: int = 42) -> dict:
    if per_stratum < 1:
        raise ValueError("per_stratum must be positive")
    population, provenance = read_population(paths, sources_path)
    if not population:
        raise ValueError("No reviewable URLs; do not audit an empty/failed crawl")
    groups = {}
    for row in population:
        groups.setdefault(row["stratum"], []).append(row)
    rng = random.Random(seed)
    samples, strata = [], {}
    for name, members in sorted(groups.items()):
        selected = sorted(rng.sample(members, min(per_stratum, len(members))), key=lambda row: row["audit_id"])
        for row in selected:
            row.update(population_count=str(len(members)), sample_count=str(len(selected)))
        samples.extend(selected)
        strata[name] = {"population": len(members), "sample": len(selected)}
    manifest = {"schema_version": "discovery-review-1", "seed": seed, "per_stratum": per_stratum,
                "population_urls": len(population), "population_accepted": sum(row["predicted_accepted"] == "true" for row in population),
                "strata": strata, "sample_rows": samples, **provenance,
                "limitations": ["Discovery metadata only; document content/rights are unverified.",
                                "Stratified precision estimates describe these observed URLs, not all site resources.",
                                "Rejected-resource rate is not global recall; incomplete crawls omit unseen resources.",
                                "Sinhala text hint is not verified document language."]}
    # Never replace an existing review directory or its labels.
    output.mkdir(parents=True, exist_ok=False)
    with (output / "review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(samples)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def wilson(successes: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.96
    probability = successes / count
    denominator = 1 + z * z / count
    midpoint = (probability + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(probability * (1 - probability) / count + z * z / (4 * count * count)) / denominator
    return [max(0, midpoint - radius), min(1, midpoint + radius)]


def report_review(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "discovery-review-1":
        raise ValueError("Unsupported review manifest")
    expected = {row["audit_id"]: row for row in manifest["sample_rows"]}
    with (folder / "review.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("Review CSV headers changed")
        rows = list(reader)
    seen, groups = set(), {}
    for row in rows:
        audit_id = row["audit_id"]
        if audit_id not in expected or audit_id in seen:
            raise ValueError("Unexpected or duplicate review row")
        if any(row[key] != expected[audit_id][key] for key in FIELDS if key not in EDITABLE):
            raise ValueError(f"Immutable sample evidence changed: {audit_id}")
        if any(not isinstance(value, str) for value in row.values()) or row["review_label"] not in LABELS:
            raise ValueError(f"Invalid review row/label: {audit_id}")
        if row["review_label"] and (not row["reviewer"].strip() or not row["review_notes"].strip()):
            raise ValueError("Labeled rows require reviewer and notes")
        if row["scope"] == "external_control" and row["review_label"] == "resource":
            raise ValueError("External URLs are outside the sampling source's eligibility; label non_resource or unsure")
        seen.add(audit_id)
        groups.setdefault(row["stratum"], []).append(row)
    if seen != set(expected):
        raise ValueError("Review rows are missing")
    results = {}
    for name, members in sorted(groups.items()):
        labels = Counter(row["review_label"] for row in members)
        known = labels["resource"] + labels["non_resource"]
        results[name] = {**manifest["strata"][name], "labels": dict(labels),
                         "resource_rate_on_resolved_rows": labels["resource"] / known if known else None,
                         "wilson_95_on_resolved_rows": wilson(labels["resource"], known),
                         "unresolved": len(members) - known}

    def weighted(accepted: bool):
        strata = [name for name, members in groups.items()
                  if members[0]["predicted_accepted"] == str(accepted).lower() and members[0]["scope"] == "in_domain"]
        population = sum(results[name]["population"] for name in strata)
        if not population:
            return {"population": 0, "estimate": None, "unresolved_label_bounds": None}
        lower = upper = 0.0
        unresolved = 0
        for name in strata:
            result = results[name]
            count, resource = result["sample"], result["labels"].get("resource", 0)
            weight = result["population"] / population
            lower += weight * resource / count
            upper += weight * (resource + result["unresolved"]) / count
            unresolved += result["unresolved"]
        return {"population": population, "estimate": lower if not unresolved else None,
                "unresolved_label_bounds": [lower, upper], "unresolved_sample_rows": unresolved}

    accepted, rejected = weighted(True), weighted(False)
    unresolved = sum(result["unresolved"] for result in results.values())
    return {"schema_version": "discovery-review-report-1", "status": "complete" if not unresolved else "pending_review",
            "sample_rows": len(rows), "unresolved_rows": unresolved, "strata": results,
            "weighted_accepted_precision": accepted, "weighted_rejected_resource_rate": rejected,
            "proposed_precision_point_target_met": accepted["estimate"] >= 0.95 if accepted["estimate"] is not None else None,
            "gate": "NOT_APPROVED", "limitations": manifest["limitations"] + [
                "Unresolved-label bounds are not confidence intervals or guarantees about unsampled URLs.",
                "Stratum Wilson intervals are approximate and ignore the finite-population correction.",
                "A precision point target alone does not approve downloading; fixture recall, rights and source review remain required."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("--decisions", type=Path, nargs="+", required=True)
    sample.add_argument("--sources", type=Path, default=ROOT / "configs/sources.yaml")
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--per-stratum", type=int, default=12)
    sample.add_argument("--seed", type=int, default=42)
    report = commands.add_parser("report")
    report.add_argument("folder", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "sample":
            result = make_sample(args.decisions, args.sources, args.output, per_stratum=args.per_stratum, seed=args.seed)
            print(json.dumps({"folder": str(args.output), "population_urls": result["population_urls"],
                              "sample_rows": len(result["sample_rows"]), "strata": len(result["strata"])}))
        else:
            print(json.dumps(report_review(args.folder), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, csv.Error, yaml.YAMLError) as exc:
        parser.exit(2, f"Review error: {exc}\n")


if __name__ == "__main__":
    main()
