# Corpus review quality reports

This report helps choose the next review work and checks the current review packet
before a training release. It runs offline, loads no OCR model and changes no source,
draft, catalog or approval. It accepts production `corpus-review-1` packets, not the
independent OCR benchmark packets. Use [OCR_ACCURACY_GUIDE.md](OCR_ACCURACY_GUIDE.md)
for independent reference-based OCR comparisons.

## Run a report

After `prepare-review`, run this command with your actual packet directory:

```bash
python3 -B -m pipeline.workflow quality \
  --packet /tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001
```

Without `--output`, the command prints JSON and writes nothing. Save an immutable
JSON/Markdown report outside the packet when you want to archive a review snapshot:

```bash
python3 -B -m pipeline.workflow quality \
  --packet /tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001 \
  --output /tmp/sinhala-corpus-production/corpus/logs/quality/batch_001_before_review
```

Open `report.md` for the summary and `report.json` for full coverage, diagnostics and
queue details. Existing output folders are never overwritten. After corrections or
approval, generate a new report folder, such as `batch_001_after_review`. The production
Colab notebook saves these reports to Drive after preparing its review packet.

## What it reports

- Pending/rejected/approved decisions and valid versus invalid approvals.
- Edited drafts still pending review and prioritized review IDs: invalid approvals
  first, then pending pages with warnings.
- Original versus current draft warnings, OCR completion statuses and failure outcomes.
- Subject/domain/grade/language/license/source/method/backend coverage, separately
  for all selected pages and valid approvals. These remain **metadata hints**.
- Selected page numbers grouped by source document/version. Selection does not prove
  whole-document coverage: the report does not know whether unselected pages are missing.
- Source-document/version split conflicts and exact/near duplicate groups.
- Bounded correction distances for valid approved text, plus explicit skipped coverage.
- Hashes of source evidence, current drafts, reviews and reporting components.

Missing metadata appears as `(unknown)`. A missing catalog license is not evidence of
permission; approvals require the separate `rights_evidence` declaration. A checksum
verifies consistency, not source correctness, reviewer independence or authenticity.

## Correction burden versus accuracy

Distances compare the initial extraction with the current, valid approved correction.
They measure editing burden on that selected review set. Reviewers saw the prediction,
so these corrections are **not independent OCR references** and the report must not
be presented as an OCR accuracy score or a held-out model comparison.

Character units are NFC Unicode codepoints, not Sinhala grapheme clusters. Word units
are whitespace-separated tokens. Edit rates divide the summed exact Levenshtein edits
by the corresponding corrected reference units across scored pages. Insertion-heavy
output can produce a rate above 1. Equations, option order, missing lines and layout
still need source review even when edit rates are low. An unchanged approved draft
has zero correction distance; this does not prove it was transcribed correctly.

Pending, rejected and invalidly approved pages are excluded from correction metrics.
Metric coverage is printed alongside the rate; no verified approvals means `null`,
not zero. Fully corrected failed/empty predictions remain counted as editing burden.

Default computational limits:

| Limit | Default | Behavior |
| --- | ---: | --- |
| `--max-metric-cells` | 1,000,000 | Maximum reference × prediction units for one dynamic-programming comparison |
| `--total-metric-cells` | 5,000,000 | Combined budget across character and word comparisons |
| `--max-dedup-pages` | 1,000 | Maximum approved pages for duplicate preflight |

Identical sequences and empty predictions have direct exact distances without using
the dynamic-programming budget. Budget-skipped comparisons are excluded from metric
denominators, with explicit skip reasons. These limits bound expensive comparisons;
source verification, reading files and tokenization remain outside the metric budget.
Larger packets may require a higher reviewed limit or smaller review batches. If
duplicate checking is deferred, preflight stays blocked; it does not silently pass.
Near matching uses the existing word 5-gram/Jaccard rules, which do not detect every
translation, paraphrase or short near duplicate.

## Export preflight and command exits

Preflight is blocked by invalid approvals, no valid approvals, source split leakage,
cross-split duplicates or deferred duplicate checking. Same-split duplicate groups
are reported; the exporter retains one representative with a duplicate audit trail.
Passing preflight means the present review declarations and split checks passed;
it does not establish independent accuracy or create training data.

For a shell check that fails when export preflight is blocked:

```bash
python3 -B -m pipeline.workflow quality \
  --packet /tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001 \
  --require-exportable
```

- Exit `0`: report completed; with `--require-exportable`, preflight also passed.
- Exit `1`: report completed but the explicitly requested preflight gate is blocked.
- Exit `2`: malformed/corrupt evidence, changing review snapshot, invalid limits or
  an output publication failure prevented a trustworthy report.

Approved text changed after sealing is displayed as an invalid approval so reviewers
can find and recheck it. Normal dataset loading/export remains strict and rejects that
approval. Source-image or immutable-record corruption prevents reporting entirely.
The report checks input hashes again before returning; keep one writer and stop
editing while reporting. This is not a distributed lock for concurrent Drive writers.

## Suggested workflow

1. Prepare the review packet and generate a before-review report.
2. Correct source text and resolve high-priority warnings. Reject unusable pages.
3. Have two different people check the full source, equations and reading order;
   record permission evidence and an explicit split, then seal the correction.
4. Generate an after-review report and address invalid approvals/split blockers.
5. Export with the existing reviewed exporter and run `verify-release`.
6. Keep independent OCR reference measurement and the actual GPU/Drive trial as
   separate validation. Report production coverage honestly before scaling.

The reporter never executes steps 2–5 on your behalf.

Local verification on 12 October 2026: eleven new regression tests pass, and the
full offline suite ran 237 tests (236 passed, one Tesseract test skipped). The ten
production notebook code cells and embedded setup programs parse without saved
outputs. These checks use local fixtures; the new reporting cell has not yet run
on a real production Drive packet in Colab.
