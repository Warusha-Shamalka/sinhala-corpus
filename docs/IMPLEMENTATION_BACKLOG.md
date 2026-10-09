# Ordered implementation backlog

This backlog preserves the supplied project decisions and current crawler architecture. Branch names are recommendations; only `docs/sinhalammlu-pipeline-review` is created by this documentation task. Do not start bulk downloading before discovery validation. Model construction is a later use case, not the immediate task.

## Phase 1: finish discovery reliability and filtering

| Order / proposed branch | Scope | Acceptance criteria |
| --- | --- | --- |
| 1 — `fix/discovery-url-validation` | B01/B02/R02/R04: safe URL parsing, HTTP(S) gates, nested config validation, final redirect URL handling | Malformed anchors cannot crash a crawl; FTP resources never cataloged; same-host relative redirect fixture resolves correctly; bad YAML gets actionable errors; catalog unchanged in dry run |
| 2 — `fix/discovery-sinhala-metadata` | B03–B08: aliases, specific subject matching, Sinhala grade/range detection, resource-local evidence, script/style exclusion, language hint distinction | Tests with real config detect nested names and Sinhala aliases; independent mixed subjects stay unknown; ranges preserved; generic downloads recovered only with local evidence; English hints not asserted as verified Sinhala |
| 3 — `fix/catalog-integrity` | B09/B10/B12: locked dedup/ID allocation/write, row validation, pilot evidence annotations | Stale/concurrent batches cannot create duplicate IDs or drop records; invalid rows preserve original bytes; all eight pilot IDs remain intact; missing source URLs cannot enter a download queue |
| 4 — `feat/discovery-audit` | R01/R03/R05/R06/R10: robots outcomes, queue budgets, source outcomes, truncation reports, structured decisions | Offline 404/403/429/5xx/timeout fixtures show intended policy; no unbounded queue; failed run distinguishable from valid empty run; decision evidence persists; no document bodies fetched |
| 5 — `test/discovery-source-validation` | Fixed offline source-shaped fixtures and labeled sample protocol | Current and changed code evaluated on same fixtures; precision/recall reported with denominators; navigation remains crawlable but excluded; PDFs/papers/notes/guides/keys retained; bounded live dry run leaves catalog byte-identical |

Existing navigation tests and scoring already exist. Extend them instead of implementing a competing classifier. Integer rule scores are acceptable; do not pretend they are calibrated probabilities. Run offline tests before intentional live checks. Do not compare a new count to 1,465 without accounting for code and source-content changes.

Phase 1 exit gate: no open crash/catalog-corruption defects, discovery sample precision accepted by the team, known resource recall preserved, source approval and rights evidence tracked, and dry-run safety verified. Proposed quantitative starting targets are in the acquisition plan; actual measurements are not yet available.

## Phase 2: download the pilot and recover it

Branch `feat/pilot-downloader`, dependent on Phase 1:

- Fill the eight pilot source URLs from evidence; add a marking scheme and extraction fixture categories as needed.
- Implement approved download queue, safe names, streaming limits, MIME/signature validation, redirect policy, retries, immutable SHA256 artifacts and durable persistence.
- Test non-PDF error pages, duplicate content, changed source versions, interrupted downloads, and restart after artifact/catalog checkpoint failure.
- Demonstrate recovery from persistent Drive artifacts after deleting only disposable Colab scratch in a controlled test; do not delete source data.
- Add dependencies and `configs/pipeline.yaml` only as required by implemented consumers.

Exit gate: small pilot downloads are reproducible and hashes verified in persistent storage; no large-scale collection yet.

## Phase 3: extraction, OCR and cleaning

| Branch | Scope | Acceptance criteria |
| --- | --- | --- |
| `feat/page-extraction` | Born-digital PDF/HTML parsing with layout/page provenance | Pilot pages preserve headings, columns, options, equations and assets; no login/navigation text mislabeled as lessons |
| `feat/selective-sinhala-ocr` | Page-level OCR routing and measured tool selection | Reviewed Sinhala scanned pages have recorded error estimates; mixed PDFs OCR only failed pages; low-quality pages quarantine correctly |
| `feat/sinhala-cleaning-metadata` | Conservative normalization, repeated boilerplate handling, evidence-based enrichment | Meaning/negation/option labels preserved; transformations traceable; unknown metadata stays unknown; raw hashes unchanged |

Exit gate: reviewed clean pages trace back to immutable source bytes, with failed pages visible and recoverable. Select OCR/extraction dependencies after pilot comparison, not by assumption.

## Phase 4: corpus release and supervised MCQs

| Branch | Scope | Acceptance criteria |
| --- | --- | --- |
| `feat/corpus-dedup-quality` | Exact and near duplicates, quality reports, rights/eligibility | Duplicates preserve aliases; accepted/rejected corpus decisions reproducible; no silent unverified quality scores |
| `feat/mcq-answer-pairing` | Stems/options, marking-scheme joins and single-answer labels | Paper/session/medium/version joins have evidence; answer indexes valid; visual/incomplete/ambiguous items quarantined; stratified answer audit reported |
| `feat/dataset-release` | Pretraining/instruction/QA products, grouped splits, manifests | Sibling/duplicate/synthetic families do not cross splits; provenance complete; development-overlap filtering avoids hidden tests; release rebuild has matching hashes |

Synthetic MCQ generation is a subsequent `feat/synthetic-mcq` experiment using eligible passages. Require provenance, explicit synthetic labels, independent checks, and generator disclosure. It must not delay verifying real answer-key joins.

## Phase 5: later benchmark training and reproduction

Use `feat/mmlu-baseline` only after the corpus work is stable and authorised development/schema/hardware inputs exist. Follow the separate evaluation document for inference-only baseline, training ablations, cap checks, and frozen submission packaging. Do not introduce retrieval into competition inference.

## Maintenance alongside relevant stages

Use `chore/reproducible-python-env` for a supported Python version, pinned concrete dependencies, CI and removal of tracked bytecode/transient logs from the index. Do not delete useful historical evidence without an archived review summary. Update READMEs as stages become operational. Keep the current CSV; evaluate database migration only if measured concurrency/scale warrants it, with Drive/Colab constraints considered.

## Required result record for each implementation branch

Record baseline revision, files/behavior changed and why, tests added and exact results, fixture comparison, bounded live dry-run results when relevant, catalog before/after hash, remaining defects and next dependency. No unexplained catalog edits, generated data commits, unsupported source approval changes, or claims that planned stages are implemented.
