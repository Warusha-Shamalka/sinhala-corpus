# Project progress and TODO

Updated: 9 October 2026. This checklist tracks implemented work separately from planned stages. Detailed acceptance criteria remain in [IMPLEMENTATION_BACKLOG.md](IMPLEMENTATION_BACKLOG.md).

## Completed

- [x] Establish the modular corpus pipeline and keep source corpus separate from derived datasets.
- [x] Configure sources, subjects, education levels and controlled document types.
- [x] Define the catalog schema and preserve eight intended pilot document IDs.
- [x] Implement bounded discovery, source approval checks, domain restrictions, logging, transparent candidate scoring and catalog-safe dry runs.
- [x] Prepare the repository review, bug inventory, acquisition plan, pipeline/data contracts, competition constraints and report/manifest templates.
- [x] Fix malformed/non-HTTP URLs and resolve relative links against redirected page URLs.
- [x] Encode spaces and Unicode URL paths for requests.
- [x] Improve subject matching, add eight initial Sinhala aliases, retain grade ranges and reject conflicting metadata.
- [x] Exclude script/style/template content from discovery evidence.
- [x] Reject navigation and subject-filtered listing pages while keeping them crawlable.
- [x] Separate source language hints from unverified document language.
- [x] Compare fixed discovery examples against the original revision: 11/13 correct improved to 13/13.
- [x] Complete a bounded live discovery check: 10 pages, 481 direct-document candidates; no catalog edits or resource downloads.
- [x] Merge discovery fixes into `dev` (merge commit `550f7d6`).
- [x] Lock catalog read–validation–deduplication–ID allocation–write as one local POSIX operation.
- [x] Validate catalog rows and reject malformed/duplicate records without rewriting invalid input.
- [x] Preserve existing IDs/extension columns; reallocate stale preview IDs and skip repeated URLs.
- [x] Annotate the eight incomplete pilots in `corpus/catalog/pilots.json` without inventing source URLs.
- [x] Test concurrent processes, lock timeouts, failed replacement and actual committed-row reporting.
- [x] Pass all 46 tests, including 12 catalog integrity tests.
- [x] Commit catalog integrity changes (`bde8829`).
- [x] Merge catalog integrity and TODO work into `dev` (`b4d4574`).
- [x] Implement conservative robots outcomes, bounded retries and server wait handling.
- [x] Deduplicate/bound the crawl queue, requests and per-source elapsed time.
- [x] Reject/report truncated and undecodable HTML/robots responses.
- [x] Persist decision evidence and run summaries with honest source outcomes/exit codes.
- [x] Pass all 63 tests and verify the audit on a bounded live dry run.

Verification details: [discovery results](DISCOVERY_VALIDATION_RESULTS.md) and [catalog integrity results](CATALOG_INTEGRITY_RESULTS.md). The small fixed examples are regression checks, not a real-source quality audit. Locking is verified on a local POSIX filesystem, not for concurrent Drive-mounted writers.

## Next: finish discovery reliability

- [ ] Review/commit the discovery reliability checkpoint on `feat/discovery-audit`, then merge into `dev`.
- [ ] Add resource-local evidence for generic download links without inheriting unrelated page context.
- [ ] Extend reviewed Sinhala aliases and explicit grade/level forms without merging distinct subjects.
- [ ] Add an explicit mapping between project taxonomy and benchmark taxonomy; keep grade targets separate from verified curriculum facts.

## Before downloading

- [ ] Record source approval/URL evidence, allowed resource hosts, robots observations and rights decisions.
- [ ] Capture suitable offline source-shaped fixtures for e-Thaksalawa, NIE and AlApiEdu.
- [ ] Annotate a stratified real-source sample of accepted/rejected candidates.
- [ ] Measure candidate precision and fixture resource recall with sample sizes and limitations.
- [ ] Confirm navigation rejection and preservation of PDFs, papers, notes, guides and answer keys.
- [ ] Fill the eight pilot source URLs from real evidence, preserving their IDs.
- [ ] Add MathsAPI only after source review and crawl approval; it is not currently configured.
- [ ] Declare supported Python and pin required dependencies; add offline CI checks.
- [ ] Remove tracked bytecode/transient logs from version control through a reviewed maintenance change.

**Gate:** do not begin bulk downloading until discovery quality and provenance are accepted.

## Pilot download and persistent storage

- [ ] Implement a download queue that excludes incomplete/unapproved records.
- [ ] Stream downloads with safe filenames, size/time limits, redirect checks and bounded retries.
- [ ] Validate MIME/signatures and reject login/error pages disguised as documents.
- [ ] Store immutable raw artifacts with SHA256 and requested/final URL provenance.
- [ ] Make retries/resume idempotent; preserve changed source versions separately.
- [ ] Configure Drive as persistent storage and Colab as temporary compute; keep one persistent-store catalog writer.
- [ ] Checkpoint catalog/artifact manifests and demonstrate recovery from persistent storage on the pilot.
- [ ] Add `configs/pipeline.yaml` when its first consuming stage exists.

## Extraction, OCR and cleaning

- [ ] Extract born-digital PDF/HTML content with page/block provenance and reading order.
- [ ] Preserve equations, tables, option labels and figure references.
- [ ] Measure Sinhala OCR quality on reviewed scans and select a reproducible tool/configuration.
- [ ] Route only failed/scan pages to OCR; retain page-level outcomes for mixed PDFs.
- [ ] Clean conservatively without losing Sinhala characters, negation, units or option meaning.
- [ ] Record transforms and metadata evidence; quarantine incomplete/low-quality pages.

## Corpus and dataset releases

- [ ] Implement exact SHA256 and near-duplicate grouping while retaining source aliases.
- [ ] Validate language, provenance, content integrity and release rights.
- [ ] Extract complete MCQ stems and ordered options.
- [ ] Pair papers with authoritative marking schemes using subject, medium, session/year and version evidence.
- [ ] Verify one supported answer; quarantine ambiguous, incomplete and unsupported visual questions.
- [ ] Group related documents/questions and synthetic families before assigning dataset splits.
- [ ] Produce separate pretraining, instruction, QA and evaluation products with versioned manifests/hashes.
- [ ] Audit label correctness and dataset quality before release.
- [ ] Add synthetic training MCQs only with provenance, independent verification and generator disclosure.

## Later: competition model and submission

- [ ] Obtain authorised development data, official input/output schema, rule version, runtime/hardware limits and available compute budget.
- [ ] Establish a reproducible open-weight baseline and an honest development holdout policy.
- [ ] Compare clean-text adaptation and verified MCQ supervision through controlled experiments.
- [ ] Enforce the summed 8B inference cap and the model release cutoff; complete the actual model manifest.
- [ ] Keep hidden tests out of collection, training, tuning and prompt design.
- [ ] Package automatic inference without internet, closed APIs, retrieval, dictionaries or corpus lookups.
- [ ] Reproduce the frozen system offline and complete the system report with the required SinhalaMMLU citation.

## Current data reality

The catalog still contains eight `DISCOVERED` pilot rows without source URLs. No raw-document download, extraction/OCR stage, labeled MCQ training release, model training or competition submission has been implemented. Candidate URLs are not verified documents or training examples.
