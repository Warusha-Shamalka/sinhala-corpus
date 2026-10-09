# Corpus discovery

This package discovers links to potentially relevant Sinhala/Sri Lankan educational resources and can append those candidates to `corpus/catalog/documents.csv`. It is intentionally limited to discovery; it does not retrieve resource files.

## Configuration and source eligibility

The crawler loads `configs/sources.yaml` and `configs/subjects.yaml` from the repository root. It uses configured subjects, domains, grade ranges, source names, languages, and base URLs rather than embedding project values in code. Only sources with both `enabled: true` and `verified: true` are crawled. Enabled but unverified entries are logged as `SKIPPED_UNVERIFIED_SOURCE`. The source list and configured limits are printed before a run.

## Crawling and classification

Each selected source is traversed breadth-first from its configured base URL. URLs are normalized, fragments are discarded, external hosts are rejected, revisits are prevented, and links are bounded by depth and per-source page count. The crawler consults `robots.txt`, sends a descriptive User-Agent, applies a request delay, and handles HTTP, timeout, and page-read failures without aborting other sources. Only HTML/XHTML responses are read (up to a bounded amount); likely resource files are never fetched. Redirects outside the configured source domain are rejected.

Page traversal is deliberately independent from catalog decisions: same-domain HTML navigation, category, and search pages remain crawlable, but obvious infrastructure/navigation/listing pages are normally excluded from the catalog. Candidate scoring uses weighted, explainable evidence from the resource URL, filename, anchor/title, local surrounding text, and configured subject list. A direct document link is strong evidence; category/navigation cues are negative evidence. Dry-run output prints scores, reasons, accepted examples, and rejected navigation/listing examples. Configured subject names support subject/domain matching; grade and education level are filled only for explicit Grade/Class numbers or O/L/A/L labels. Document types use the existing controlled values (`textbook`, `teacher_guide`, `syllabus`, `past_paper`, `marking_scheme`, `lesson`, `article`, `workbook`, `other`). Ambiguous metadata is left empty. A PDF link is recorded as a candidate, not downloaded or parsed.

## Catalog updates

URLs must be HTTP(S), without credentials or malformed hosts/ports. Spaces and Unicode URL paths are percent-encoded while existing escapes/query semantics are retained. Relative links resolve against the final redirected page URL. Script, style and template content cannot supply candidate evidence.

Subject `aliases` are optional lists in `configs/subjects.yaml`; specific contained names take precedence, while independent subject mentions remain ambiguous. Eight initial Sinhala aliases are configured without merging distinct taxonomy labels. `grade_markers.before_number` and `after_number` configure grade labels, and education-level `aliases` configure Sinhala/English level phrases. Explicit grade ranges are retained; incompatible grades/levels stay unknown. Source-wide language is exposed only as an internal `_language_hint`; the candidate's catalog `language` remains blank until document validation.

The existing CSV header is checked against the expected catalog columns before use. Existing normalized `source_url` values are excluded, IDs continue from the highest existing `LK-EDU-NNNNNN` number, and new rows are written with `status=DISCOVERED`. Unavailable metadata, hashes, years, licenses, and local-file fields remain empty. Normal-mode updates preserve existing rows and replace the catalog atomically after writing a complete CSV.

## Usage

From the repository root:

```text
python -m pipeline.discovery.crawler --source SOURCE_ID --dry-run
python -m pipeline.discovery.crawler --source SOURCE_ID --max-pages 50 --max-depth 2 --delay 1.5
```

Available options are `--source`, `--max-pages`, `--max-depth`, `--delay`, `--timeout`, and `--dry-run`. Dry-run crawls eligible configured sources and previews prospective IDs/rows without modifying the catalog. Logs are written under `corpus/logs/discovery/`.

## Limitations and deliberate omissions

- The crawler does not run unless a source has a configured URL and `verified: true`. Current unverified sources are skipped by design.
- Subject recognition matches configured names and aliases; Sinhala coverage is partial and needs reviewed extensions.
- Grade extraction requires explicit configured labels or level phrases. Generic links lacking local resource evidence may remain unclassified; broad page titles are not inherited automatically.
- Some websites omit or mislabel HTML content types; non-HTML/unknown content types are skipped rather than risk reading a document.
- Robots policy handling is conservative: only absent policies (404/410) allow crawling without a policy. Forbidden/unavailable/invalid policies block that origin for the run. HTML/robots truncation and decoding failures are explicit, with bounded retries for transient request failures.
- No PDFs or other files are downloaded; there is no OCR, extraction, deduplication by file hash, dataset building, RAG, or downloader implementation in this stage.

The discovery implementation and test/live-run results are recorded in [DISCOVERY_VALIDATION_RESULTS.md](../../docs/DISCOVERY_VALIDATION_RESULTS.md). Subsequent [catalog integrity work](../../docs/CATALOG_INTEGRITY_RESULTS.md) adds a cooperative local POSIX lock covering validation, deduplication, ID allocation and atomic replacement. Drive-mounted multi-writer semantics remain unsupported.

## Reliability and audit outputs

Each run writes a unique `*.decisions.jsonl` and `*.summary.json` alongside its log under `corpus/logs/discovery/`, including during dry runs. Decisions retain local evidence and scores/reasons; summaries record source outcomes and limits. Catalog contents remain unchanged during dry runs.

Additional options: `--max-queue` (1000), `--max-requests` (250), `--max-seconds` (300), `--max-retries` (2), and `--max-retry-wait` (30). Queue/request/time budgets apply per source, and requests count redirects and retries. Available robots crawl delays/request rates and Retry-After are respected. A server-requested wait exceeding the retry budget defers that request.

Exit codes: `0` for completed useful processing (including a genuinely empty source), `1` for partial processing, and `2` for failure or no processable selected sources. Hitting a page cap with pending pages returns `1`; inspect the summary's stop reason. Time budgets are checked between bounded operations and are not a hard external process deadline.

See [DISCOVERY_AUDIT_RESULTS.md](../../docs/DISCOVERY_AUDIT_RESULTS.md) for exact offline/live verification and interpretation.
