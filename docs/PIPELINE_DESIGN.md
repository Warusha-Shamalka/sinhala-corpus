# Pipeline design and stage contracts

Status: proposed extensions to the current Python discovery pipeline. Preserve configuration-driven behavior, the existing CSV catalog and document lifecycle. Implement one validated stage at a time.

## Flow and responsibility

```text
approved sources + subject taxonomy
  -> discovery candidates / decision evidence
  -> approved download queue
  -> immutable raw corpus + content hashes
  -> page extraction -> selective OCR
  -> cleaned text + metadata evidence
  -> exact / near duplicate groups
  -> quality validation -> READY corpus
  -> derived pretraining / instruction / QA / evaluation datasets
```

The raw corpus is the authoritative content; the catalog is authoritative tracking metadata. Cleaning never replaces raw files. Candidate scores describe discovery evidence and are not content-quality probabilities.

| Stage | Input | Output and successful transition | Required checks |
| --- | --- | --- | --- |
| Discovery (implemented) | Enabled + crawl-approved sources, subjects | Catalog candidates `DISCOVERED`; proposed evidence sidecar | HTTP(S), domain, limits, robots, URL dedup, navigation/resource distinction |
| Download (planned) | Approved `DISCOVERED` rows with actual URLs | Immutable `corpus/raw/` file, hash and fetch metadata; `DOWNLOADED` | Status/MIME/magic bytes, redirects, byte limits, source approval, durable persistence |
| Extraction (planned) | Raw hash + extractor config | `corpus/extracted/pages/` blocks and `text/`; `EXTRACTED` after required OCR | Page count, layout/order, Unicode quality, completeness and assets |
| OCR (planned) | Pages needing OCR | Page text/boxes and OCR confidence, tool/config versions | Sinhala fidelity, missing math/figures, confidence and page coverage |
| Cleaning (planned) | Extracted pages + config | `corpus/clean/` text and transform evidence; `CLEANED` | Safe normalization, preserved options/negation/math, no raw mutation |
| Metadata (planned) | Source/candidate/page evidence | Enriched metadata plus evidence sidecar | Controlled labels, conflict tracking, no invented years/license/grades |
| Deduplication (planned) | Raw and clean hashes/text | Canonical document/group relationships; `DEDUPLICATED` or `DUPLICATE` | Exact bytes, normalized text, near duplicates and versions |
| Quality (planned) | Clean content and provenance | Decision/report; `VALIDATED`, then `READY` when release-eligible | Language, content integrity, rights decision, provenance, quality metrics |
| Dataset (planned) | Eligible READY documents, verified MCQs | Versioned datasets under `datasets/` + manifest | Label validity, answer evidence, source-grouped splits, contamination exclusions |

Metadata enrichment may run at several stages; it must preserve existing evidence and document conflicts rather than inventing a new linear catalog stage.

## Lifecycle and failure handling

Keep `DISCOVERED -> DOWNLOADED -> EXTRACTED -> CLEANED -> DEDUPLICATED -> VALIDATED -> READY`. Preserve the supplied failure states `EXTRACTION_FAILED`, `OCR_FAILED`, `QUALITY_FAILED`, and `DUPLICATE`; propose `DOWNLOAD_FAILED` for download errors. Do not add these values silently: document and migrate status validation first.

Each task records input hash, stage/config version, run ID, output hash, outcome, timestamps and structured error code. Store page/task outcomes separately from the document status; one failed OCR page must not hide the successful pages or make the document READY. Retry begins from the last successful immutable input, with an event describing the transition.

Write outputs to temporary files, validate and persist them, then update the catalog. Crashes between artifact persistence and catalog update are resolved by hash verification on resume. Idempotency is keyed by document/input hash plus stage/config version. Retrying the same successful version must not append another catalog row or silently change a raw artifact.

## Discovery improvements without redesign

Keep breadth-first traversal and separate crawl eligibility from candidate scoring. Catch malformed links per item; validate configuration before network work. Track scheduled URLs, retain final redirected page URLs, and support approved exact resource hosts separately from crawl hosts. Use bounded retries for transient failures and record successful-empty/partial/failed outcomes.

Capture resource-local anchor/heading/filename evidence, excluding scripts/styles. Use broad page title only as a lower-confidence fallback. Record transparent integer scores and named rules. Preserve original title and provenance even when inferred metadata is unknown. Benchmark alias matching against the actual configuration, not only abbreviated test taxonomies.

Do not fetch document bodies during discovery. Opaque resource endpoints belong in a downloader queue once discovered; their actual content type is verified by download. HTML pages may be candidates, but listing pages must not be transformed into invented standalone documents.

## Download implementation

Stream with explicit size and timeout limits; validate MIME and signature rather than trusting `.pdf`. Reject HTML login/error pages disguised as PDFs. Enforce approved redirects, robots/access policy, rate limits and retry budgets. Preserve requested and final URLs, HTTP status, byte count, timestamps, optional ETag/Last-Modified, and SHA256.

Use stable ID/hash-based names and a source-URL-to-artifact relationship; do not trust remote path fragments as local filenames. Repeated identical content may share one immutable artifact while retaining every source alias. Changed content at one URL creates a recorded version. Include a dry run that lists eligible tasks and rejection reasons without downloading or updating the catalog.

## PDF/HTML extraction and OCR

Use born-digital PDF extraction first, preserving page number, blocks, reading order, question numbers, equations, tables and figure references. HTML extraction must retain meaningful headings/lists and suppress navigation. Validate each page independently: text density, Sinhala/Unicode quality, empty blocks, replacement characters and column order.

OCR only pages that fail extraction checks. Mixed PDFs require page-level decisions. Benchmark candidate OCR tools on reviewed Sinhala scans before selecting or pinning one; this plan makes no unverified claim that a particular OCR model supports Sinhala well. Track actual tool/model revisions and language packs.

Do not silently flatten visual questions or discard diagrams. Retain assets/references in the master corpus and quarantine MCQs whose answer needs unavailable visual input for a text-only dataset. The organiser input modality has not yet been verified.

## Cleaning and answer preservation

Apply reviewed Unicode NFC and whitespace normalization; keep original text and transform logs. Do not strip Sinhala combining characters, joiners, numbers, minus signs, option labels, “not”/negation, or units. Validate representative Sinhala strings and equations after transformations.

Dehyphenation, repeated-header removal, and column merging require page-aware evidence. A formatting repair that changes an option's meaning is a rejected example. Record both raw spans and cleaned spans so another researcher can trace every MCQ.

## Labeled MCQs and synthetic data

Extract stems and ordered options across pages, preserving original numbering/labels. Require one complete stem, distinct options, and exactly one supported answer. Pair papers with marking schemes using subject, medium, exam board, year/session, paper number and version. Never pair by filename or question number alone. Store the answer-key page/span and join evidence.

If no reliable answer key exists, keep questions as unlabeled material or route them to reviewed training-only annotation. Model-generated answers are synthetic labels, not authoritative keys. Reject ambiguous answers, mismatched variants, incomplete options and multi-answer questions from the single-answer training product.

Synthetic generation is a later dataset-stage experiment: derive questions from eligible curriculum passages, preserve parent documents/spans, record generator/prompt/config and answer rationale, then run independent verification and human spot checks. Label every synthetic item. Avoid self-verification as the sole correctness test. Do not generate synthetic variants from hidden test items. Closed generators, if used, remain training-only and fully disclosed.

## Quality and release gates

Use multiple metrics, not a single opaque score: language checks, extraction completeness, OCR error estimates, duplicate status, MCQ structure, answer evidence, rights/provenance and split integrity. Uncertain records go to `corpus/clean/rejected/` or a review queue with reasons; they remain traceable.

Proposed pilot gates: all released records have resolvable provenance and immutable hashes; all labeled MCQs pass structural checks; all exact/near-duplicate groups stay in one split; no visual-dependent incomplete questions; and reviewed answer accuracy meets a team-agreed target (initial proposal 98% on a stratified audit with sample size and uncertainty). Thresholds are project proposals, not challenge rules or measured achievements.

## Configuration and operations

Add `configs/pipeline.yaml` only when its first consuming stage exists. Keep paths configurable for local development and Drive/Colab use. Store supported extractor/OCR settings, size/rate/retry limits, normalization version and quality thresholds there; keep credentials out of YAML/Git.

Each stage should expose a small Python API and CLI with stage-specific scope, a safe dry run where relevant, deterministic ordering and a machine-readable run summary. Record catalog snapshots and completion markers in persistent storage. CI uses offline fixtures; intentional live checks are bounded and never run against hidden-test resources.
