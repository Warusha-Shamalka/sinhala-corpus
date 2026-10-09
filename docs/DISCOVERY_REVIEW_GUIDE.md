# Manual discovery quality review

Prepared on 9 October 2026 on `feat/discovery-quality`. This branch starts from `0eaa6d9`, the completed discovery-audit implementation. After refreshing remote refs, that implementation was merged into `origin/main` (`da9804c`), while `origin/dev` remained at `b4d4574`. This task changes neither branch; merge the dependency into `dev` before merging this branch there.

## What is ready

The offline review tool converts decision observations into unique source/URL candidates, makes a seeded stratified sample, and calculates reports from independent labels. It writes no catalog entries and performs no network requests or document downloads.

Current local sample: `corpus/logs/discovery/reviews/alapiedu_20261009/review.csv`. Its manifest and initial `report.json` are in the same directory. They are generated review artifacts under ignored `corpus/logs/`, not committed datasets; preserve copies and manifests in persistent storage before an environment reset.

The underlying 10-page partial run contains 1,372 observations, deduplicated into 556 source/URL candidates: 481 accepted, 31 rejected in-domain and 44 rejected external controls. The review sample contains 80 rows: 43 accepted, 18 rejected in-domain and 19 external controls. All 80 labels are blank. Precision has not been measured and downloading is not approved.

The nine sampling groups combine source, predicted decision, source-domain scope, URL format, Sinhala-text hint, and score band. The text hint is based on visible title/context, not verified document language. Up to 12 URLs are selected per group using seed 42; small groups are reviewed entirely.

## Review the CSV

Open `review.csv` in an editor or spreadsheet preserving UTF-8 Sinhala text, column names, text values, and all rows. Inspect source URL, referring page, title and local evidence. Hide predicted decision/score/reasons while making an initial judgment if practical, to reduce agreement bias. The purpose is to judge whether a link is an eligible individual educational-resource candidate, not whether its answer labels, language, contents or license are verified.

Edit only these four columns:

| Column | What to enter |
| --- | --- |
| `review_label` | `resource`, `non_resource`, `unsure`, or `inaccessible` |
| `reviewer` | Stable reviewer name/identifier |
| `review_notes` | Short reason supporting the judgment and any uncertainty |
| `review_evidence` | Optional evidence location or observation details |

Leave URL, audit ID, sample/population counts, scores and other evidence columns unchanged. The report rejects missing/duplicate rows, unexpected labels and changed immutable evidence. Labels require reviewer and notes. Do not edit `manifest.json` to make changed rows pass validation.

## Label rules

- **resource:** an individual Sri Lankan educational document or content page within the configured source domain, with evidence of relevance. PDFs, lessons, paper records, teacher guides and marking schemes can qualify. A document extension alone is insufficient evidence of educational relevance. Keep content/language/rights verification separate.
- **non_resource:** navigation, hubs, filtered listings, login/privacy/contact pages, unrelated material, or links outside this source's permitted domain. An external control may be educational elsewhere, but is not an eligible resource under this source's current boundary. Explain that distinction in notes.
- **unsure:** available evidence does not establish an individual educational resource or its relevance. Do not infer certainty from the crawler's score or force a borderline item into a binary label.
- **inaccessible:** resource status cannot be judged because the supporting evidence cannot be accessed. An inaccessible item is unresolved, not automatically irrelevant.

Use saved metadata and referring-page evidence first. This review does not authorize bulk fetching or moving documents to READY. There are no benchmark questions in this sample; never add hidden-test questions or benchmark mirrors to resolve uncertainty. Record source rights/approval evidence separately.

For example, a `/teacher-guides?subject=Biology` listing is `non_resource` even if it links to relevant individual guides. An individual guide with adequate educational identity can be `resource`. A generically named PDF with no useful supporting context may be `unsure`.

## Recalculate the report

From the repository root:

```bash
python3 -B -m pipeline.quality.discovery_review report corpus/logs/discovery/reviews/alapiedu_20261009
```

The command prints JSON. To save it after labeling:

```bash
python3 -B -m pipeline.quality.discovery_review report corpus/logs/discovery/reviews/alapiedu_20261009 > corpus/logs/discovery/reviews/alapiedu_20261009/report.json
```

Read the status, unresolved counts, per-group labels and these measures:

- `weighted_accepted_precision`: proportion of accepted candidates independently judged eligible, weighted by each group's population size. The overall point estimate stays null while any accepted sample label is unresolved.
- `weighted_rejected_resource_rate`: eligible resources among rejected in-domain candidates. This measures missed resources among the observed rejected population; it is not global recall or a substitute for fixture recall.
- `unresolved_label_bounds`: possible estimates if unresolved sample labels are assigned either way; these are not confidence intervals or guarantees about unsampled candidates.
- Per-group Wilson intervals on resolved labels: approximate uncertainty within groups; missing-label selection and finite-population effects limit interpretation.

External controls appear in group reports and completion counts, but are excluded from rejected-resource estimates. Stratified estimates differ from pooling the 80 labels as one uniform sample. The report always retains `gate: NOT_APPROVED`: a point estimate above the proposed 95% precision target does not replace rights/source checks, fixture recall, independent review and sufficient uncertainty assessment.

## Make a new sample

Supply a decisions file and its matching `.summary.json`; the tool validates run IDs, source approval and input schemas. Choose a new output directory so completed labels are never overwritten:

```bash
python3 -B -m pipeline.quality.discovery_review sample --decisions corpus/logs/discovery/discovery_20261009T084155Z_4dc532a7_100917.decisions.jsonl --output corpus/logs/discovery/reviews/alapiedu_second_review --per-stratum 12 --seed 42
```

The same inputs/seed/settings reproduce the same sample. Repeated normalized URLs are collapsed within each source. If observations disagree, the first accepted observation wins, matching discovery's resource insertion behavior; observation/conflict counts remain visible. Source boundaries use the current approved configuration and its hash is saved in the manifest. Source changes require deliberate re-review.

Do not combine multiple sampled reviews as though they were independent complete-site inventories. Future source fixtures should include explicit positive and negative examples and support a separate fixture recall measurement.

## Implementation verification and next work

All 73 tests passed, including 10 new sampling/report tests. Tests cover deterministic selection, deduplication/conflicts, weighting, unresolved labels, sample preservation, invalid edits, schema/run mismatch and source boundaries. The existing fixed discovery examples still classify 13/13 correctly. The real catalog and source configurations remain unchanged.

Next: independently label the 80 rows, adjudicate disagreements/uncertainty, collect approval/rights evidence, and capture suitable source-shaped fixtures for additional sources. Downloader work remains behind the discovery quality gate.
