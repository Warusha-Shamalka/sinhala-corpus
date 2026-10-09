# Current state and bug review

Review date: 8 October 2026. Baseline: `373ce62` on `dev`. Findings describe that revision, not future implementations. Severity expresses impact on this project: P0 blocks safe training-data preparation; P1 affects reliability or dataset correctness; P2 improves coverage, maintenance, or efficiency.

## Actual progress

| Area | Evidence | Assessment |
| --- | --- | --- |
| Source inventory | `configs/sources.yaml`: e-Thaksalawa, NIE, AlApiEdu; all enabled and marked verified | Crawl approval switch exists; notes about URL verification are stale/ambiguous, not document quality evidence |
| Subject taxonomy | `configs/subjects.yaml`: six domain groups, grade ranges, education levels | Usable starting vocabulary; aliases and challenge-label mapping missing |
| Discovery | `pipeline/discovery/{crawler,filters,parser}.py` | Bounded breadth-first crawler, HTML requests, same-host/subdomain restriction, robots parsing, scored filtering |
| Catalog | 23 columns and eight rows in `corpus/catalog/documents.csv` | Eight metadata placeholders; all source/source_url/license fields are blank |
| Tests | `tests/test_discovery.py`, 19 passing tests | Tests cover selected filters, domain checks, BFS, ID assignment, and dry-run catalog safety |
| Historical runs | 14 tracked discovery logs | Some complete, some incomplete; not evidence that all configured sources work |
| Download through dataset release | README files under the later pipeline directories | No executable implementations |
| Training/evaluation/submission | No corresponding scripts or model manifest | Not implemented |

Useful existing foundations: configuration-driven sources, conservative unknown fields, source-domain redirect handler, normalized URL deduplication, request delays, discovery dry run, and atomic CSV replacement. Preserve these strengths while fixing edge cases.

The completed log `corpus/logs/discovery/discovery_20261008T101223Z_212870.log` reports AlApiEdu at 61 visited pages, 1,406 candidates, 58 excluded listing pages, four excluded navigation pages, and one request error (robots.txt HTTP 404). A preceding run reports 1,451 candidates. These are historical counts from the environment recorded in the logs; they are not a new crawl or a precision measurement. The newest log contains only startup lines and cannot establish successful completion. No authorised competition development data or training-ready examples were found.

## Confirmed defects and inconsistent data

Offline probes are in `docs/evidence/reproduce_review.py`. They report behavior rather than assert that current bugs are correct. Existing unit tests remain unchanged.

| ID / priority | Location at reviewed revision | Observed behavior | Recommended fix and verification |
| --- | --- | --- | --- |
| B01 / P0 | `filters.py:70`, URL parsing callers | `normalize_url('https://[bad/path')` raises `ValueError` before the existing port guard. A malformed anchor can abort a source/run. | Guard the entire parse, validate HTTP(S), log a rejected URL; crawl fixture with malformed anchors must finish. |
| B02 / P1 | `filters.py:70`; `crawler.py:process_link` | FTP URLs normalize successfully and a same-host FTP PDF can be accepted as a catalog candidate. `should_crawl` rejects FTP, but candidate insertion has no matching scheme gate. | Require HTTP(S) for catalog resources, redirects, and source bases; test both discovery and normalization. |
| B03 / P1 | `filters.py:105` + actual subject config | `History of Sri Lanka` matches both it and `History`; `Sinhala Language and Literature` matches both it and `Sinhala`. Both return empty subject/domain. | Prefer a specific phrase over a contained shorter alias; preserve genuinely independent subject ambiguity. Test the actual config. |
| B04 / P1 | `filters.py:105,121`; `configs/subjects.yaml` | `ඉතිහාසය` and `8 ශ්‍රේණිය ඉතිහාසය` produce no subject/grade. Subject names are English-only and grade patterns are English-only. | Add reviewed Sinhala aliases and explicit Sinhala grade/level forms in config; retain original labels as evidence. |
| B05 / P1 | `filters.py:121` | `Grade 8-9 History` becomes grade `8`, losing the range; multiple grades also use the first match. | Parse ranges and multiple mentions, keep conflicts unknown or reviewable; test ranges and subject grade constraints. |
| B06 / P1 | `parser.py:97` | `page_title` is accepted but never used. A `Download` anchor at `/download` under `Grade 8 History textbook` is rejected even when the page title contains useful evidence. | Use resource-local headings/page title as lower-confidence fallback for generic links, with negative controls for unrelated neighboring resources. |
| B07 / P1 | `parser.py:65` | Script/style text enters `page_parts` and link context. `<script>History textbook</script>` appears in a following link's `before` context. | Exclude scripts/styles and segment context by semantic resource blocks; test misleading script and navigation content. |
| B08 / P1 | `parser.py:124` | Every candidate inherits the source-wide `language: si`. A link explicitly titled `English History textbook` is still labeled Sinhala. | Separate language hint from confirmed page/document language; reject or quarantine unsupported language at quality validation. |
| B09 / P1 | `crawler.py:assign_ids`, `append_catalog` | Two batches assigned from an empty snapshot and appended sequentially produce duplicate `LK-EDU-000001` IDs. Read/replace atomicity is not a transaction. Concurrent writes can also lose updates. | Lock read–dedup–ID allocation–write together, or use transactional storage; test stale snapshots, duplicate URLs, and competing writers. |
| B10 / P0 | `corpus/catalog/documents.csv` | All eight intended pilot rows have empty source and source URL. They pass the header-only catalog validation but cannot be fetched. | Preserve rows and IDs, record their pilot status in a sidecar, and block downloads until provenance is filled from evidence. Do not invent URLs. |
| B11 / P2 | `configs/sources.yaml` | `verified: true` means crawl approval per supplied handover, but notes still say official URL verification is needed. | Preserve the approval meaning; update notes and record approval/URL evidence separately from document validation and rights evidence. |
| B12 / P1 | `crawler.py:read_catalog` | Required headers are checked, but row completeness, ID uniqueness, field count, status values, and URL consistency are not. Malformed rows can reach ID or write code. | Validate each row and return an actionable error; preserve the original catalog when invalid. |

B06 is a recall/design gap, not permission to classify every generic download link from broad page context. B08 records an unverified language claim, not evidence that the underlying file is English. B09's duplicate-ID case was reproduced without concurrency; lost updates are an additional code-level concurrency risk.

## Reliability and coverage risks found by inspection

| ID / priority | Evidence | Improvement |
| --- | --- | --- |
| R01 / P1 | `robots_allowed` turns every failed robots request into allow-all | Distinguish absent robots (404) from 403/429/5xx, DNS failure, and timeout; pause transient failures, honor crawl delay and Retry-After |
| R02 / P1 | `fetch_html` resolves links against requested URL; redirect response's final URL is discarded | Return final URL with page content and resolve relative links there; deduplicate canonical aliases |
| R03 / P1 | Only per-request timeouts, depth and page counts; queue can contain repeated/unbounded entries | Track queued URLs, bound queue and run time, cap retries, and use per-source request budgets |
| R04 / P1 | Only mapping/list presence validated in config | Validate nested types, duplicate source IDs, valid URLs, booleans, ranges, and finite numeric limits; handle null/scalar YAML cleanly |
| R05 / P1 | `run` returns zero even when every network request fails or all selected sources are skipped | Distinguish successful-empty, skipped, partial, and failed source/run outcomes with machine-readable summaries |
| R06 / P1 | Reads stop at 2 MB HTML / 512 KB robots without truncation reports | Detect truncation and decoding failure; avoid silently treating partial HTML as complete evidence |
| R07 / P2 | Extension-based classification and only anchor parsing | Explicit adapters for opaque PDF endpoints, Moodle resource pages, embedded files, image-alt link labels, and verified external asset hosts |
| R08 / P2 | Subdomains of a configured host allowed, sibling host/CDN/storage links dropped | Keep deny-by-default boundary; add exact approved resource hosts with provenance rather than broadening to arbitrary domains |
| R09 / P1 | Every direct document extension adds five points; no content validation yet | Document extension alone means candidate, never accepted training material; check educational scope, actual type, and language after download |
| R10 / P2 | Scores/reasons stripped before CSV write; logging mainly aggregate | Structured decision sidecar with source ID, referring URL, evidence, rule version, timestamp, and content hash when available |
| R11 / P2 | PyYAML imported but no dependency/packaging file; tracked `__pycache__` and logs | Declare supported Python and pinned dependencies; remove tracked generated artifacts in a separate maintenance change |
| R12 / P1 | Only 19 tests, mostly English examples | Add source-shaped offline fixtures and precision/recall annotation; tests do not establish production extraction or dataset quality |

## Missing capabilities that matter for this competition

The pipeline needs approved download queues, resumable downloads, content hashes, page extraction with layout, selective OCR, Sinhala-aware normalization, question/option segmentation, paper-to-marking-scheme pairing, label verification, question-level deduplication, source-grouped splits, dataset manifests, and reproducible evaluation. Generic clean text alone is not a labeled MCQ dataset.

For model work, add a rule-compliant baseline first, then compare curriculum adaptation, supervised MCQ training, and independently generated synthetic MCQs. Record subject/difficulty accuracy and invalid outputs. Do not spend the entire schedule collecting documents before measuring a baseline.

## Review limits

No live source crawl, file download, OCR benchmark, training run, hidden-test inspection, or actual submission was performed. Historical logs cannot establish availability or classification precision today. The shared conversation could not be fetched; the user's pasted handover was incorporated. Model choice and quality targets remain proposals until measured against the authorised development set and available hardware. The immediate task is reliable corpus discovery, not model construction.
