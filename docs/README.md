# SinhalaMMLU preparation documents

Prepared on 8 October 2026 from repository commit `373ce62`, the competition rules supplied in chat, local tests, and historical discovery logs. This is a documentation-first review: the proposed pipeline and fixes are not implemented by these documents.

Read in this order:

Implementation update: the [9 October discovery validation results](DISCOVERY_VALIDATION_RESULTS.md) document completed fixes and current verification. The original current-state review below remains a dated baseline rather than a claim that every listed defect is still open.

The subsequent [catalog integrity results](CATALOG_INTEGRITY_RESULTS.md) describe transaction-safe local discovery appends and row validation.

The latest [discovery reliability and audit results](DISCOVERY_AUDIT_RESULTS.md) cover robots policies, budgets, exit codes and persisted decisions.

| Document | Purpose |
| --- | --- |
| [TODO.md](TODO.md) | Completed milestones and the ordered remaining checklist |
| [DISCOVERY_REVIEW_GUIDE.md](DISCOVERY_REVIEW_GUIDE.md) | Label the generated candidate sample and calculate quality reports |
| [CURRENT_STATE_REVIEW.md](CURRENT_STATE_REVIEW.md) | What exists, measured progress, limitations, and confirmed bugs |
| [IMPLEMENTATION_BACKLOG.md](IMPLEMENTATION_BACKLOG.md) | Ordered work, proposed branches, dependencies, and acceptance criteria |
| [COMPETITION_COMPLIANCE.md](COMPETITION_COMPLIANCE.md) | Rules supplied by the team, data separation, parameter accounting, and reproducibility |
| [DATA_ACQUISITION_PLAN.md](DATA_ACQUISITION_PLAN.md) | Source selection, coverage, provenance, and collection strategy |
| [PIPELINE_DESIGN.md](PIPELINE_DESIGN.md) | Stage contracts, recovery, extraction, MCQ generation, and quality gates |
| [DATA_CONTRACTS.md](DATA_CONTRACTS.md) | Proposed document, page, MCQ, split, and release schemas |
| [EVALUATION_AND_EXPERIMENTS.md](EVALUATION_AND_EXPERIMENTS.md) | Development evaluation, ablations, and model-selection protocol |
| [templates/SYSTEM_DESCRIPTION.md](templates/SYSTEM_DESCRIPTION.md) | Finalist report template with the required paper citation |
| [templates/model_manifest.example.yaml](templates/model_manifest.example.yaml) | Model manifest template; intentionally incomplete and not a usable manifest |
| [templates/data_release.example.yaml](templates/data_release.example.yaml) | Training release provenance template |
| [evidence/reproduce_review.py](evidence/reproduce_review.py) | Offline review probes; reports current behavior without changing the catalog |
| [evidence/REVIEW_RESULTS.md](evidence/REVIEW_RESULTS.md) | Exact review commands, observed outcomes, and preservation checks |
| [evidence/compare_discovery.py](evidence/compare_discovery.py) | Offline comparison against the reviewed baseline on fixed examples |

The existing [PIPELINE_GUIDE.md](PIPELINE_GUIDE.md) remains the current discovery usage guide. The documents above describe the competition-specific target and distinguish planned behavior from implemented behavior.

## Evidence and unresolved inputs

- `python3 -m unittest discover -s tests -v`: 19 tests passed during review. No live crawl was run.
- Catalog: eight rows, all `DISCOVERED`; no usable source URLs, licenses, downloaded artifacts, or hashes recorded.
- Historical completed AlApiEdu dry run: 61 visited pages and 1,406 candidate URLs. This measures discovery output, not verified documents or MCQs.
- The [shared conversation](https://chatgpt.com/share/6ac770a3-d8d4-83e8-aa51-50dda29bba4a) could not be fetched on two attempts. The user then supplied its handover text, which is incorporated as project context. The original linked conversation itself remains unread.
- Competition rules are transcribed from the user's message, not independently verified against a current organiser publication. The authorised development set, submission schema, hardware budget, and inference limits are not present in this repository.
- The required [SinhalaMMLU paper citation](https://aclanthology.org/2025.emnlp-main.1673/) was checked through ACL Anthology. Benchmark question files were not downloaded or inspected.

## Working branch

This review uses `docs/sinhalammlu-pipeline-review`, created from `dev`. Keep implementation in the small branches proposed in the backlog. No push or commit is performed as part of this review.

## Decisions preserved from the supplied handover

Keep the existing modular Python stages, CSV catalog, stable document IDs, source and subject configurations, and corpus/dataset separation. Raw source files are immutable. Google Drive is the intended persistent corpus store; Colab is temporary execution/compute. `verified` means approval to crawl a source, not academic verification of its documents. The eight catalog entries are intended pilot documents, not fabricated discoveries. Their URLs still need evidence before downloading.

The immediate priority remains discovery filtering and validation. Several handover tasks are already implemented at the reviewed commit: separate `should_crawl` and candidate classification, integer scores/reasons, navigation/category rejection tests, and dry-run safety. Do not repeat that work or interpret the historical count of 1,465 as the current baseline. The supplied handover names MathsAPI; it is not in the current source configuration and is a proposed addition only. Grade ranges are collection targets unless independently supported. General corpus RAG outputs may be built later, but are excluded from challenge inference.

- [Development and automated checks](DEVELOPMENT_CHECKS.md): pinned setup, CI and teammate review validation.

- [Resource-local discovery evidence](DISCOVERY_LOCAL_EVIDENCE_RESULTS.md): generic-link handling, regression coverage and bounded live comparison.
