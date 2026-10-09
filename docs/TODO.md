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
- [x] Build reproducible stratified candidate sampling and reports that require independent review labels.
- [x] Prepare an 80-row AlApiEdu review sample, with labels blank and the quality gate pending.
- [x] Pass all 73 tests, including 10 review-tool tests.

Verification details: [discovery results](DISCOVERY_VALIDATION_RESULTS.md) and [catalog integrity results](CATALOG_INTEGRITY_RESULTS.md). The small fixed examples are regression checks, not a real-source quality audit. Locking is verified on a local POSIX filesystem, not for concurrent Drive-mounted writers.

## Next: finish discovery reliability

- [x] Bring discovery-audit and discovery-quality into `dev` (verified at merge `d204a38`).
- [x] Commit and merge the discovery review tool and Git-trackable 80-row review bundle.
- [ ] Complete the teammate review issue; validate the first 10-row PR before finishing the sample.
- [x] Add bounded structural evidence for generic download links, preserving item boundaries and recording audit reasons.
- [x] Commit/push local discovery evidence changes; implementation is present on `dev` (`d4e113c`).
- [ ] Distinguish language-medium tokens from subject names and syllabus-version wording from document type.
- [ ] Extend reviewed Sinhala aliases and explicit grade/level forms without merging distinct subjects.
- [ ] Keep this repository focused on corpus acquisition; coordinate benchmark taxonomy/model work with the separate training repository when needed.

## Before downloading

- [ ] Record source approval/URL evidence, allowed resource hosts, robots observations and rights decisions.
- [ ] Capture suitable offline source-shaped fixtures for e-Thaksalawa, NIE and AlApiEdu.
- [ ] Annotate a stratified real-source sample of accepted/rejected candidates.
- [ ] Measure candidate precision and fixture resource recall with sample sizes and limitations.
- [ ] Confirm navigation rejection and preservation of PDFs, papers, notes, guides and answer keys.
- [ ] Fill the eight pilot source URLs from real evidence, preserving their IDs.
- [ ] Add MathsAPI only after source review and crawl approval; it is not currently configured.
- [x] Declare Linux/POSIX Python 3.11–3.14 CI targets, pin PyYAML, and implement automated offline regression/review checks.
- [x] Commit/push the checks branch; all four Python CI jobs passed (reported by maintainer).
- [ ] Remove tracked bytecode/transient logs from version control through a reviewed maintenance change.

**Current decision:** the maintainer authorised proceeding with candidate suitability as a provisional assumption. Human labels and measured precision remain pending; do not mark the review as completed or claim measured accuracy. Start bounded download batches, retain uncertain metadata and record provenance.

## Pilot download and persistent storage

- [x] Implement a download queue that excludes incomplete/unapproved records.
- [x] Stream PDF downloads with safe filenames, size/time limits, robots/redirect checks and bounded request retries.
- [x] Validate PDF MIME/signatures and reject login/error pages disguised as documents.
- [x] Store immutable PDF artifacts and receipts with SHA256 and requested/final URL provenance.
- [x] Verify/recover successful raw artifacts on restart and retain changed versions; interrupted bodies restart from the beginning.
- [ ] Configure Drive as persistent storage and Colab as temporary compute; keep one persistent-store catalog writer.
- [ ] Checkpoint catalog/artifact manifests and demonstrate recovery from persistent storage on the pilot.
- [x] Add `configs/pipeline.yaml` with download paths and bounded transfer settings.

- [ ] Commit/push `feat/pilot-downloader`, verify CI and merge into `dev`.
- [ ] Add real approved resource URLs to the master catalog, preserving the eight pilot IDs.
- [ ] Extend downloading to HTML/scans/other formats only with format-specific validation.

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

The catalog still contains eight `DISCOVERED` pilot rows without source URLs. A PDF download stage is implemented and one 2.1 MB real PDF was verified in an isolated smoke catalog; the production catalog still has zero downloadable jobs. All 109 tests pass. See [download validation](DOWNLOAD_VALIDATION_RESULTS.md).

Extraction/OCR and derived-dataset stages remain planned. Model training and competition submission belong in the separate training repository. Candidate URLs are not verified documents or training examples.
