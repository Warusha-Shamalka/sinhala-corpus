# Corpus discovery

This package discovers links to potentially relevant Sinhala/Sri Lankan educational resources and can append those candidates to `corpus/catalog/documents.csv`. It is intentionally limited to discovery; it does not retrieve resource files.

## Configuration and source eligibility

The crawler loads `configs/sources.yaml` and `configs/subjects.yaml` from the repository root. It uses configured subjects, domains, grade ranges, source names, languages, and base URLs rather than embedding project values in code. Only sources with both `enabled: true` and `verified: true` are crawled. Enabled but unverified entries are logged as `SKIPPED_UNVERIFIED_SOURCE`. The source list and configured limits are printed before a run.

## Crawling and classification

Each selected source is traversed breadth-first from its configured base URL. URLs are normalized, fragments are discarded, external hosts are rejected, revisits are prevented, and links are bounded by depth and per-source page count. The crawler consults `robots.txt`, sends a descriptive User-Agent, applies a request delay, and handles HTTP, timeout, and page-read failures without aborting other sources. Only HTML/XHTML responses are read (up to a bounded amount); likely resource files are never fetched. Redirects outside the configured source domain are rejected.

Page traversal is deliberately independent from catalog decisions: same-domain HTML navigation, category, and search pages remain crawlable, but obvious infrastructure/navigation/listing pages are normally excluded from the catalog. Candidate scoring uses weighted, explainable evidence from the resource URL, filename, anchor/title, local surrounding text, and configured subject list. A direct document link is strong evidence; category/navigation cues are negative evidence. Dry-run output prints scores, reasons, accepted examples, and rejected navigation/listing examples. Configured subject names support subject/domain matching; grade and education level are filled only for explicit Grade/Class numbers or O/L/A/L labels. Document types use the existing controlled values (`textbook`, `teacher_guide`, `syllabus`, `past_paper`, `marking_scheme`, `lesson`, `article`, `workbook`, `other`). Ambiguous metadata is left empty. A PDF link is recorded as a candidate, not downloaded or parsed.

## Catalog updates

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
- Subject recognition matches configured English subject names; Sinhala aliases must be explicitly added to configuration to be recognized.
- Grade extraction requires explicit “Grade N” or “Class N” text. Resource links without useful anchor/page metadata may remain unclassified or be missed.
- Some websites omit or mislabel HTML content types; non-HTML/unknown content types are skipped rather than risk reading a document.
- Robots retrieval failures are logged and treated as unavailable policy; verify the site's terms and robots guidance before enabling a source.
- No PDFs or other files are downloaded; there is no OCR, extraction, deduplication by file hash, dataset building, RAG, or downloader implementation in this stage.