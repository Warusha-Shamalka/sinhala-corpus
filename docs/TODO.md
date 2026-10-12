# Project progress and TODO

Updated: 12 October 2026. This checklist tracks implemented work separately from planned stages. Detailed acceptance criteria remain in [IMPLEMENTATION_BACKLOG.md](IMPLEMENTATION_BACKLOG.md).

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
- [x] Distinguish configured medium phrases from subject names, preserving unverified medium hints in discovery audit decisions.
- [x] Distinguish known English syllabus-version wording from a competing named resource type; preserve standalone syllabus candidates.
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
- [x] Add 481 production discovery candidates with real URLs, preserving the eight initial pilot IDs.
- [x] Complete the first production download plus a five-document batch; verify all six saved PDFs against receipts on 11 October 2026.
- [ ] Commit the production catalog checkpoint and progress-reporting TODO updates after the batch is complete.
- [ ] Extend downloading to HTML/scans/other formats only with format-specific validation.

## Progress reporting across pipeline stages

- [x] Add shared progress reporting for discovery and downloading; provide a reusable reporter for future stages.
- [x] Discovery: show current source/page, pages visited, queued URLs, candidates accepted/rejected, request count, elapsed time and the reason for stopping. The crawl's total is unknown; do not present the page cap as percent completion of the website.
- [x] Downloading: show current document ID/title, job number out of selected jobs, bytes transferred, known file size, transfer speed and estimated remaining time when enough information exists. Show bytes without a percentage when Content-Length is unknown.
- [x] Show active phases such as robots lookup, connecting, transferring, retry wait, stored-file verification and catalog checkpoint so users can distinguish work from waiting.
- [x] Count downloaded, verified-existing, recovered, failed and conflicted jobs separately; explain batch-limited exclusions as deferred jobs rather than errors. Report missing robots.txt as an absent policy while retaining its HTTP observation.
- [x] Write human-readable progress to stderr and keep the final JSON report on stdout; support quiet/noninteractive modes and throttle updates so redirected logs and Colab remain readable.
- [x] Persist a lightweight per-run progress snapshot with run ID, stage, current item, counts and last-update time, allowing a read-only status command to inspect background runs. Distinguish running, completed, failed, interrupted and potentially stale snapshots without claiming a stale heartbeat proves failure.
- [ ] Future page-processing stages: report documents/pages completed, OCR-required pages, failures and rejected records; estimate completion only when the task total is known.
- [x] Add offline tests for known/unknown file sizes, retries, silent/redirected output, interrupted runs and final progress totals matching actual outcomes. Document the progress and background-status commands before marking this feature complete.

See [PROGRESS_GUIDE.md](PROGRESS_GUIDE.md) for usage and limitations.

## Extraction, OCR and cleaning

- [x] Extract native PDF text with page/block/word coordinates, raw provenance, versioned immutable outputs, OCR routing, recovery and progress.
- [ ] Add HTML extraction and validate native Sinhala PDF fonts/layouts using reviewed source pages.
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

Verified on 11 October 2026: the production catalog contains 489 records: 482 `DISCOVERED` and seven `DOWNLOADED`. All seven production PDFs (IDs 9–15) match their stored receipt sizes and SHA256 hashes. The eight original pilots still have blank URLs and remain excluded from downloading. The earlier 2.1 MB smoke PDF is separate from these production files. The implemented code previously passed all 109 tests; see [download validation](DOWNLOAD_VALIDATION_RESULTS.md).

Native PDF extraction, OCR, static HTML, conservative cleaning and reviewed pretraining export are implemented. Real source review and the first approved release remain pending. Model training and competition submission belong in the separate training repository. Candidate URLs are not verified documents or training examples.

## PDF extraction checkpoint — 11 October 2026

- [x] Inspect seven downloaded PDFs and verify raw hashes/receipts.
- [x] Trial native extraction on a copied catalog: 132 pages, zero native text, seven OCR-routed documents, zero failed jobs; production catalog unchanged.
- [x] Document extraction commands, output contracts, limits and observed pilot results.
- [ ] Manually review representative scanned/handwritten pages and review the extraction PR into `dev`.
- [x] Implement selective OCR separately; handwriting/equation accuracy checks remain pending, and empty-native-text bundles are not promoted into datasets.

## Selective OCR baseline checkpoint — 11 October 2026

- [x] Add local Tesseract Sinhala/English backend, bounded rendering/recognition and selective page CLI.
- [x] Preserve native artifacts/catalog; write immutable per-page PNG/TSV/text/provenance with pending review.
- [x] Add model hashes, restart/corruption checks, progress, tests and setup/validation guides.
- [x] Trial two handwritten pages from LK-EDU-000011; recognition is poor and remains unapproved.
- [ ] Prepare reviewed references and measure Sinhala handwriting/equation errors before choosing a stronger backend.
- [ ] Add explicit review outcomes/quality-stage catalog transitions and accepted merged document text.
- [ ] Defer bulk processing of 132 scanned pages until recognition quality is established.

## Accuracy-first OCR / Colab checkpoint — 11 October 2026

- [x] Prepare ten immutable source-image samples across seven downloaded documents, with raw-hash grouped calibration/holdout and empty human-reference files.
- [x] Add independent-reference verification, hash checks and offline CER/WER reporting with honest missing coverage.
- [x] Add optional Gemma/DeepSeek snapshot adapters and a beginner Colab notebook; keep heavyweight dependencies outside core requirements.
- [x] Mark every raw neural result as pending review and unapproved for training; preserve production catalog/native bundles.
- [ ] Have two Sinhala readers transcribe/verify the ten samples; currently zero verified references.
- [ ] Finish the Gemma Colab pilot and archive its dependency/model manifests. Maintainer supplied T4 results for two pages; the first hit a repetition/token-limit failure.
- [ ] Validate DeepSeek upstream environment on a BF16-capable GPU and implement completion detection; completion-unverified output is currently excluded from accuracy scoring.
- [ ] Expand evaluation beyond the current source pilot to printed Sinhala, MCQs, tables, diagrams and subject diversity.
- [x] Add phase progress plus Gemma repetition-loop/soft-deadline stopping; stopped output remains truncated. Local fixture checks pass; updated GPU behavior remains pending.
- [ ] Review holdout CER/WER plus missing-line, option, number and equation errors before selecting an OCR backend.
- [ ] Implement reviewed-page acceptance and an exporter that rejects pending/reserved evaluation documents.
- [ ] Keep bulk OCR/training export deferred until these accuracy and acceptance checks pass.

See [Colab guide](COLAB_OCR_GUIDE.md) and [accuracy guide](OCR_ACCURACY_GUIDE.md). Preparing a workflow is not a completed neural model comparison.

## Guarded Gemma pilot evidence — 11 October 2026

- [x] Review ten maintainer-supplied page artifacts: six normal completions, four repetition-loop stops; compare two completed outputs with their source images and identify substantial text/formula errors.
- [ ] Archive the final `finished` run manifest; supplied snapshot still shows nine completed pages and the last page running.
- [ ] Create independently verified calibration references before further full-page batches; no training acceptance or measured accuracy is available.
- [ ] Design a bounded calibration-only region/crop experiment, preserving source coordinates and original images; evaluate printed Sinhala separately.

See [Gemma pilot review](GEMMA_PILOT_REVIEW.md). Generation stopping works on the observed loops, but the present full-page configuration is not suitable for automatic training-data extraction.

## Broader OCR diagnostic pilot

- [x] Prepare 14 public-source pages across six subject groups, with printed/handwritten examples, diagrams, equations, columns and a table.
- [x] Add frozen explicit page selection, isolated source acquisition/configuration and provenance receipts; keep production catalog unchanged.
- [x] Add Qwen2.5-VL-3B adapter and a one-page Colab compatibility trial default.
- [x] Report prediction outcomes before references and subject/style metrics after reference verification.
- [ ] Run Qwen on T4: one page first, then all 14 in a new run folder.
- [ ] Run Gemma on the identical broad packet in a fresh runtime.
- [ ] Transcribe/verify independent references and compare complete runs; do not promote raw predictions into training data.
- [ ] Fill missing handwritten Language/History/Business, printed Physics, Economics and MCQ coverage with inspected public sources.
- [x] Fix discovery subject detection for configured medium phrases and biological history contexts; preserve genuine explicit subject matches and ambiguity.

See [OCR_BROAD_PILOT.md](OCR_BROAD_PILOT.md) for prepared pages, storage, limitations and Colab steps.

## Surya trial after Qwen handwriting failure

- [x] Record supplied Qwen first-page failure: Hindi/Devanagari output from a Sinhala physics image; no training approval.
- [x] Add pinned Surya 0.17.1 adapter with local recognition/detection checkpoint hashes, offline inference, regional termination checks and preserved boxes/confidences.
- [x] Update Colab to default to Surya, one page, a fresh T4 runtime and isolated pinned Python/dependencies.
- [x] Inspect the shared Surya T4 run: 10 selected pages finished, 7 predicted and 3 truncated; spot-check native Sinhala, handwritten Physics and History source pairs. Formal accuracy remains pending references.
- [ ] If compatible, run all 14 frozen pages in a new run directory; verify references before numerical comparison or training acceptance.

See [SURYA_OCR_TRIAL.md](SURYA_OCR_TRIAL.md). Shared run `surya_20261011T174018Z` executed successfully; its output is not training-approved.

## Native text acquisition while OCR is evaluated

- [x] Implement conservative NFC/line-ending normalization and Sinhala/native extraction rejection reasons.
- [x] Prepare review packets with immutable extraction/text identities and source provenance, without catalog changes.
- [x] Export approved text into JSONL with review evidence, exact deduplication and source-PDF split boundaries.
- [x] Extract 95 pages from four local printed pilot PDFs: 2 review candidates, 93 quarantined at the default 80% Sinhala-letter threshold; no real pages approved or training dataset exported.
- [ ] Acquire better sources with correctly encoded copyable Sinhala; current worksheet candidate has mapping errors and History candidate is a title page.
- [ ] Implement HTML main-content extraction to collect public educational prose.
- [ ] Investigate legacy PDF font decoding and validate mapping accuracy against source images.
- [ ] Review usable native pages, record source-use evidence and deliver the first small pretraining release to the training repository.
- [ ] Add near-duplicate/document-version grouping before scaling train/evaluation releases.

See [NATIVE_TEXT_DATASET_GUIDE.md](NATIVE_TEXT_DATASET_GUIDE.md).

## Production corpus path (12 October 2026)

- [x] Create `feat/corpus-pipeline`; commit the completed native-text path separately.
- [x] Add replaceable OCR factory, defaulting to pinned Surya with frozen local checkpoints.
- [x] Process verified PDFs into immutable native/OCR page bundles with source images, raw outputs, warnings, progress, selected-page support and restart verification.
- [x] Add explicitly enabled HTML download, strict static main-content extraction and provenance; flag visual/math/table content for review.
- [x] Build side-by-side review packets, editable correction drafts and two-reviewer approval sealing.
- [x] Export reviewed text with exact/near deduplication and source-document/version split protection.
- [x] Configure persistent store initialization, discovery path overrides and common collect/process/status/review/export commands.
- [x] Add a production Colab notebook with an isolated pinned environment and two-page initial trial.
- [x] Push and merge `feat/corpus-pipeline` into `dev` (merge `5194669`); retain the teammate's working branch.
- [ ] Execute the two-page production Surya trial in Colab; verify Drive artifacts and restart behavior.
- [ ] Complete real source review, source-use evidence and the first approved pretraining release.
- [ ] Measure OCR accuracy on independent references before considering automated acceptance for any source/style.
- [ ] Add richer verified subject/grade metadata and instruction/QA outputs when the text corpus is validated.

See [CORPUS_PRODUCTION_GUIDE.md](CORPUS_PRODUCTION_GUIDE.md) for current limits and supported formats. No accurate training release is claimed from test fixtures.

## Discovery metadata context (12 October 2026)

- [x] Validate configurable medium/exclusion phrases, mask only known contexts and preserve explicit subject distinctions.
- [x] Keep verified document language blank; store conflicting/unknown medium hints conservatively.
- [x] Add seven regression tests; offline suite ran 221 tests (220 passed, one Tesseract test skipped).
- [ ] Review additional source wording and correct existing catalog metadata in a separate evidence-backed change; current fixes apply to newly evaluated links.

## Discovery document types (12 October 2026)

- [x] Separate new/old/revised/updated syllabus or curriculum wording from notes, workbooks and paper resource types.
- [x] Preserve standalone syllabus documents and explicit syllabus mentions; explain suppressed version signals in rule `discovery-0.5` audits.
- [x] Add five regression tests covering resource types, URL/title evidence, phrase boundaries and audit explanations.
- [x] Run the complete offline checks: 226 tests ran, 225 passed and one Tesseract test was skipped.
- [ ] Review Sinhala syllabus-version wording and other real-source formats before extending the rules.

## Corpus review quality reporting (12 October 2026)

- [x] Add offline review coverage, OCR outcomes/warnings, edited-pending drafts and prioritized review IDs.
- [x] Diagnose invalid approvals without weakening the strict exporter; verify source evidence and reject changing report snapshots.
- [x] Add approved-correction editing distances with bounded computation and explicit scored/skipped coverage; do not label these as independent OCR accuracy.
- [x] Check source/version and duplicate split conflicts, with an optional shell preflight gate.
- [x] Save immutable JSON/Markdown reports outside review packets; include input/component hashes and unverified metadata coverage.
- [x] Add a production Colab reporting cell and default its clone branch to merged `dev`; set a pushed feature branch explicitly when trialing unmerged changes.
- [x] Add eleven regression tests covering pending reviews, corrections, invalid approval, failures, budgets, split leakage, duplicates, corruption, concurrent edits and CLI gate behavior.
- [x] Pass the full offline suite: 237 tests ran, 236 passed and one Tesseract test was skipped; validate all ten production notebook code cells and embedded setup programs syntactically.
- [ ] Generate reports from actual Colab production packets before/after source-checked human review; real GPU/Drive testing and the first approved release remain pending.

See [CORPUS_QUALITY_GUIDE.md](CORPUS_QUALITY_GUIDE.md). Keep these changes with the document-type fix for one larger PR into `dev` when ready.

## Batch acquisition while review is deferred (12 October 2026)

- [x] Add bounded collect/process cycles with source/document selection, total download-job/page caps and persistent journals/config snapshots.
- [x] Isolate collection and OCR in separate Python processes so offline OCR cannot disable later downloads.
- [x] Verify/reuse completed pages and avoid repeatedly retrying the same failing document in one invocation.
- [x] Add immutable provisional text snapshots with explicit unreviewed status, warnings, source/model hashes and empty-page exclusions.
- [x] Preserve the reviewed exporter and approvals; no estimated accuracy is promoted into a quality certificate.
- [x] Pass fourteen new regression tests and the complete offline suite: 251 ran, 250 passed and one Tesseract test was skipped. Syntax-check all twelve production notebook code cells and embedded setup programs.
- [ ] Verify recovery in a fresh Colab runtime and increase acquisition caps gradually after inspecting flagged outputs.
- [x] Inspect maintainer-supplied Colab batch `batch_20261012T062841Z_ea700048`: five cycles, ten unique saved bundles, nine predicted pages and one completion-unverified page; no reported execution errors. Prior pages were verified in later cycles. Cross-runtime recovery and accuracy remain unverified.
- [x] Fix the new-page budget counter to include completion-unverified and future outcome labels whenever a new bundle was saved; add a regression test.
- [x] Pass the updated offline suite after the counter fix: 252 tests ran, 251 passed and one Tesseract test was skipped.
- [ ] Select useful provisional pages for later spot checks/source review; handwriting, equations and source-style accuracy remain unmeasured.

See [BATCH_COLLECTION_GUIDE.md](BATCH_COLLECTION_GUIDE.md). Full manual Sinhala retyping is not required to continue acquisition.

## Daily training handoff (12 October 2026)

- [x] Build immutable cumulative/delta experimental text candidates from provisional or reviewed releases.
- [x] Filter incomplete/warning-bearing OCR; record quarantines and scanner-footer normalization.
- [x] Deduplicate across the cumulative lineage and preserve document/raw/URL/duplicate-family splits.
- [x] Prevent replay of prior training text in deltas; preserve verified upgrades and record explicit replacements/removals.
- [x] Write training handoffs with release identity, checksums, checkpoint lineage and required run-record fields.
- [x] Verify source/text identities, split/duplicate consistency, delta content and handoff hashes.
- [x] Add twelve daily-release regression tests; the full offline suite ran 264 tests (263 passed, one Tesseract test skipped). Syntax-check all thirteen notebook code cells and embedded setup programs.
- [x] Maintainer reported a real Colab release `daily_20261012T074447316202Z`: 20 train rows, one quarantine, zero validation rows from one Biology document. Independent accuracy remains unverified.
- [ ] Connect the separate training repository and configure its daily checkpoint/evaluation/submission workflow.
- [ ] Produce independently supported MCQ/instruction data separately; text adaptation does not invent QA labels.

See [DAILY_TRAINING_RELEASE_GUIDE.md](DAILY_TRAINING_RELEASE_GUIDE.md).

## Separate theory and MCQ products (12 October 2026)

- [x] Establish daily page text as an intermediate mixed-content release.
- [x] Add public-source line annotation packets; preserve unclassified pages instead of assuming theory.
- [x] Export separate theory and MCQ training/validation files with source provenance.
- [x] Require source question/choice checks and answer evidence for labeled MCQs; retain incomplete candidates separately.
- [x] Preserve upstream splits, reject cross-split answer evidence and conflicting duplicate answer keys, and verify frozen exports.
- [x] Add optional Colab packet/export controls and the practical task dataset guide.
- [x] Add nine task-export tests using invented sources only; the offline suite ran 273 tests (272 passed, one Tesseract test skipped). All 15 notebook code cells parse with no saved outputs.
- [ ] Validate a real mixed-source task release; current 20-page release is not an MCQ dataset.
- [ ] Add automatic layout-aware MCQ candidate detection and cross-page question/answer-key assembly.
- [ ] Evaluate synthetic MCQs generated exclusively from permitted public theory, with generator provenance and answer checks.
- [ ] Add task-level incremental exports and connect separate theory/MCQ training loaders.

See [THEORY_AND_MCQ_GUIDE.md](THEORY_AND_MCQ_GUIDE.md). No hidden test material is an input to this work.

## Public paper and answer-key matching (12 October 2026)

- [x] Validate explicit paper/key identities including exam, subject, year, paper number, language and variant.
- [x] Detect simple numbered MCQ line blocks and join strict key rows by pair, section and original question number.
- [x] Report missing/duplicate questions or keys, incomplete choices, unsupported key lines and unverified pairs without approving labels.
- [x] Import numeric processed key pages as evidence only, with artifact verification and originating-release split checks.
- [x] Preserve input annotations and raw sources; freeze pairing configuration, matching report and bundle receipts in task exports.
- [x] Add a configuration template, CLI command, Colab controls and source-review instructions.
- [x] Pass 18 new answer-matching tests; full offline suite: 291 tests ran, 290 passed and one Tesseract test skipped. All 16 production notebook code cells and embedded scripts parse.
- [ ] Run a real public paper/key pilot; current catalog has no entries labeled marking_scheme.
- [ ] Add geometry-aware table parsing, cross-page assembly and Sinhala option label support using independently checked public examples.
- [ ] Carry paper/key families into future global dataset split planning before those key documents enter other training releases.

See [MCQ_ANSWER_MATCHING_GUIDE.md](MCQ_ANSWER_MATCHING_GUIDE.md).

## Build the public paper/key catalog

- [x] Prepare an editable pairing index from existing catalog/title hints, without approving identities.
- [x] Suggest compatible paper/key candidates with matched/missing fields, ambiguity and unresolved reports.
- [ ] Identify actual Pesuru/past-paper source sites and check their crawl configuration and source-use conditions.
- [x] Run bounded ALapi marking-scheme discovery; retain local resource-card headings and recognize answer-key labels.
- [x] Add unverified subject/medium title hints and normalize Roman paper numbers in the pairing index.
- [ ] Collect matching paper counterparts and recover missing identity evidence from their originals.
- [ ] Extract exam, subject, year, paper number, language and edition evidence from public document headers.
- [ ] Review suggested pairs against both originals and record confirmed metadata and pairing decisions.
- [ ] Track Pesuru/other compilation editions and each question's original paper reference; never join collections by year alone.
- [ ] Convert confirmed index pairs into answer-matcher configuration with selected source regions.
- [ ] Test one real complete public pair before scaling discovery and answer matching.

The index is a separate editable review artifact; it does not modify the master catalog.

Validation: 296 offline tests ran (295 passed, one Tesseract test skipped). The current catalog produced 87 draft paper entries, no key entries and zero pair suggestions. These are metadata candidates, not verified documents.

2026-10-12 marking discovery pilot: 543 unique candidates from one listing, including 212 marking-scheme candidates. An isolated index with the existing 87 paper entries still produced zero pair suggestions: 83 paper entries lack a subject and 72 lack an exam hint. Production catalog unchanged; no PDFs downloaded. Full suite: 301 tests, 300 passed and one skipped. See [MARKING_DISCOVERY_PILOT.md](MARKING_DISCOVERY_PILOT.md).


## Combined question/answer documents

- [x] Include marking schemes in a `combined_review.jsonl` inspection queue.
- [x] Accept a declared `combined` index role and unapproved same-document suggestions.
- [x] Support explicit combined matcher mode with identical source ID/hash and separate source ranges.
- [x] Match numbered keys or a single explicitly bound answer line; preserve evidence and review gates.
- [x] Block recognized answer lines inside question/choice regions and reject overlapping regions.
- [ ] Inspect the discovered marking schemes for complete embedded MCQs; record combined roles only from originals.
- [ ] Run one real combined-document pilot and one separate-paper pilot through reviewed MCQ export.
- [ ] Add source-tested support for solution prose, answer tables and compilation identities as needed.

See [MCQ_ANSWER_MATCHING_GUIDE.md](MCQ_ANSWER_MATCHING_GUIDE.md#combined-documents-questions-and-answers-in-one-source).

Combined-route validation: 310 offline tests ran (309 passed, one Tesseract-dependent skip). The isolated ALapi index now yields 212 combined-document review candidates, zero confirmed pairs; no production catalog or downloaded source was changed.

- [ ] Run bounded discovery pilots for configured e-Thaksalawa and NIE sources, inspecting redirects, resource hubs and document coverage before adding their candidates to a shared review index.
- [ ] Find the question-paper counterparts for the user-inspected ALapi 2026 Biology answer key and 2011 Chemistry explanatory marking scheme; confirm full stems/choices before treating either as combined.

## Evidence-backed paper metadata

- [x] Extract bounded identity hints from titles and URL filenames; ignore upload paths and explicitly labelled publication dates.
- [x] Accept verified first-page native/OCR processing bundles with source/page/line evidence.
- [x] Preserve conflicts, immutable input snapshots, hashes and unverified review status.
- [x] Trial the existing 299-record index (three conflicting fields; no pairs).
- [x] Find a cross-source 2011 Chemistry paper lead and produce one unapproved match to the ALapi key.
- [ ] Process/check both Chemistry headers and confirm part, medium and edition before matching answers.
- [ ] Extend source-tested identity patterns for Sinhala paper-part labels, schools, provinces, sessions and syllabus editions.

Validation: 319 offline tests ran, 318 passed and one Tesseract-dependent test skipped. The nine new metadata tests use invented fixtures; no benchmark test material was accessed.

- [x] Retain separate provisional question/answer candidates in the matching report when pairing review is the only unresolved check, while leaving training annotations unapproved and answers null.
- [ ] Obtain complete identity declarations and processed question/key regions for the Chemistry pilot before generating its real provisional MCQs.

## Real MCQ pilot execution

- [x] Download and inspect the 2011 Chemistry paper and key; identify the key as Paper II and avoid attaching it to Paper I MCQs.
- [x] Detect an alternate-host duplicate by raw SHA256.
- [x] Follow the user's choice to switch to a newer exam; download 2021 (2022) Chemistry paper/key and identify paper page 1 plus key page 3.
- [x] Prepare a two-page Surya Colab notebook with pinned PDF hashes, isolated Drive store and downloadable OCR handoff.
- [ ] Run that notebook on a working GPU; local NVIDIA driver is unavailable.
- [ ] Validate returned OCR and implement evidence-preserving table normalization for provisional MCQ matching; retain multi-answer/corrected entries as unresolved.

See [MCQ_PILOT_STATUS.md](MCQ_PILOT_STATUS.md) for precise state and next actions.
