# Discovery implementation and validation — 9 October 2026

Branch: `fix/discovery-validation`, based on the reviewed `373ce62` revision. Previous documentation remains in the working tree. No commit or push was performed.

## What changed and why

| Files | Change |
| --- | --- |
| `pipeline/discovery/filters.py` | Safe HTTP(S) URL normalization/resolution, encoded Unicode/space paths, malformed URL rejection, specific-name subject matching, configured aliases and grade/range/level conflict handling |
| `pipeline/discovery/parser.py` | Exclude script/style/template text and anchors; reject malformed links safely; distinguish source language hints from unknown document language |
| `pipeline/discovery/crawler.py` | Validate nested configuration before network work; carry final redirected page URL into parsing/link resolution; suppress revisits of final URL aliases |
| `configs/subjects.yaml` | Eight initial Sinhala subject aliases, configurable grade markers and Sinhala O/L/A/L aliases; existing canonical labels/ranges preserved |
| `tests/test_discovery.py` | Update the fake fetcher to return HTML together with its final URL |
| `tests/test_discovery_regressions.py`, `tests/fixtures/discovery_candidates.json` | Actual-taxonomy, malformed-link, redirect, Sinhala, range/conflict, noncontent parser, language-hint, listing and resource preservation checks |
| `docs/evidence/compare_discovery.py` | Reproducible offline comparison with the original reviewed revision |

The live check exposed subject-filtered `/teacher-guides` listings accepted as documents. The old Biology test used a miniature taxonomy without Biology, so it passed without exercising the real bug. Listing routes now cannot override their listing status merely by naming a subject/year; actual nested resource routes and direct documents retain acceptance. Category pages remain crawlable.

No resource bodies were downloaded, no extraction/model work was added, and no catalog rows were appended. Generic page-title inheritance remains deliberately unresolved until resource-local context can be established.

## Offline results

```bash
python3 -B -m unittest discover -s tests -v
python3 -B docs/evidence/compare_discovery.py
python3 -B docs/evidence/reproduce_review.py
```

All 34 tests passed: the original 19 plus 15 new regression tests. The fixed comparison set contains 13 independently constructed examples, including navigation/listings and actual-resource-shaped examples; it contains no benchmark questions.

| Version | Accepted | Correct decisions | Candidate precision | Recall within fixture resources |
| --- | --- | --- | --- | --- |
| Reviewed `373ce62` + original config | 6 | 11/13 | 5/6 | 5/6 |
| Working code + updated config | 6 | 13/13 | 6/6 | 6/6 |

This small constructed fixture set demonstrates regression behavior, not measured global source precision or satisfaction of the scale-up quality gate.

The review probes now show safe malformed/FTP rejection, recognized nested names and Sinhala aliases, preserved grade ranges, no script-context contamination, and blank unverified document language. They still reproduce stale-writer duplicate IDs, which is an open catalog issue.

## Bounded live dry runs

Command for both network-enabled runs:

```bash
python3 -B -m pipeline.discovery.crawler --source alapiedu --dry-run --max-pages 10 --max-depth 2 --delay 1 --timeout 8
```

The initial sandbox attempt failed DNS resolution and produced zero candidates; that was a network failure, not valid filtering evidence. It was rerun with approved network access.

| Measure | First network-enabled run | Final run after listing/URL corrections |
| --- | --- | --- |
| Pages visited | 10 | 10 |
| Candidates | 489 | 481 |
| Direct document URLs | 481 | 481 |
| HTML/other candidate URLs | 8 | 0 |
| Navigation URLs excluded | 4 | 4 |
| Listing URLs excluded | 20 | 26 |
| Queued entries left at page cap | 99 | 99 |
| Request errors | 1 | 1 |
| Runtime | 22.29 seconds | 28.15 seconds |

The one error in each successful run is robots.txt returning HTTP 404. Both runs are live observations, not identical saved HTML snapshots; candidate-count differences alone are not a controlled precision measurement. The controlled fixture comparison above isolates behavior.

Final discovered types: 375 `other`, 86 `past_paper`, eight `teacher_guide`, eight `lesson`, four `syllabus`. These are inferred discovery types, not verified content or labeled MCQ counts. The many unknown titles/types show that subject-local metadata and content validation are still necessary.

Logs are local under `corpus/logs/discovery/`:

- `discovery_20261009T075530Z_23928.log`: first network-enabled run.
- `discovery_20261009T075652Z_25933.log`: final run.

Catalog bytes match the reviewed baseline. SHA256:

```text
1b2f0e7e32e004810b04dfe4194ab66e1aff9087975836810a525501f39c9055
```

## Remaining work

1. Protect catalog read–dedup–ID allocation–write as one transaction; validate rows and preserve eight pilot IDs/provenance gaps.
2. Refine robots failure policy, failed-run exit status, queue budgets and structured decision persistence.
3. Add resource-local context for generic links and extend reviewed Sinhala aliases without conflating subjects.
4. Annotate a stratified real-source sample and source-shaped fixtures, then measure candidate precision/recall before bulk downloading.

Normal-mode catalog concurrency is not fixed by this change. The eight pilot rows still have no source URLs. The new aliases are a starting set, not full Sinhala taxonomy coverage.
