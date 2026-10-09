# Pipeline Guide

## 1. Project overview

This repository supports the creation of a Sinhala / Sri Lankan educational corpus and the downstream processing needed to turn discovered educational materials into usable datasets. The broad goal is to gather material relevant to Sri Lankan education, especially Sinhala-language resources, while keeping the pipeline explicit, auditable, and configurable.

The project is intentionally staged. At the current point, discovery is implemented and operational. Downloading, extraction, OCR, cleaning, quality validation, deduplication, and dataset generation remain planned stages unless they are added later.

## 2. Architecture

The repository is organized around four core layers:

- `configs/` — controlled project configuration such as subjects and accepted sources.
- `corpus/` — source data, extracted data, cleaned data, logs, and metadata catalog.
- `datasets/` — derived datasets produced from the corpus.
- `pipeline/` — the operational code for each stage.
- `docs/` — project-level handoff and architecture documentation.

### Key directories

- `configs/subjects.yaml` defines the subject taxonomy and grade ranges.
- `configs/sources.yaml` defines the enabled and verified source list.
- `corpus/catalog/documents.csv` tracks discovered catalog entries and metadata.
- `pipeline/discovery/` contains the current implementation for source crawling and candidate filtering.
- `corpus/logs/` contains operational logs for discovery and future stages.

## 3. Data flow

The intended project flow is:

```text
configs/sources.yaml
    ↓
discovery
    ↓
corpus/catalog/documents.csv
    ↓
download
    ↓
corpus/raw/
    ↓
extraction / OCR
    ↓
corpus/extracted/
    ↓
cleaning
    ↓
corpus/clean/
    ↓
deduplication
    ↓
quality validation
    ↓
datasets/
```

### Current implementation status

Implemented:
- source and subject config
- discovery crawler
- dry-run discovery
- candidate filtering / catalog preview
- document catalog metadata

Planned / not yet implemented:
- downloader
- extraction
- OCR
- cleaning
- deduplication
- quality validation
- dataset generation

## 4. Configuration

### `configs/subjects.yaml`

This file holds the subject taxonomy and grade information used by discovery and later pipeline stages. It should not be duplicated in Python code. The subject list is a controlled vocabulary that downstream processes can use for subject tagging and candidate classification.

### `configs/sources.yaml`

This file defines what the crawler is allowed to traverse. A source is considered eligible only when it is both enabled and verified. Disabled or unverified entries should be skipped and logged as appropriate.

This file is the project-level source inventory and should be treated as authoritative configuration.

## 5. Document catalog

`corpus/catalog/documents.csv` is the canonical metadata catalog. It stores information about discovered and tracked educational resources.

Required and expected columns include:

- `doc_id`
- `title`
- `subject`
- `domain`
- `grade`
- `education_level`
- `document_type`
- `source`
- `source_url`
- `publication_year`
- `exam_year`
- `language`
- `license`
- `status`
- `local_filename`
- `sha256`
- `extraction_method`
- `ocr_required`
- `page_count`
- `quality_score`
- `pipeline_version`
- `last_processed`
- `error`

### Intended state progression

```text
DISCOVERED
→ DOWNLOADED
→ EXTRACTED
→ CLEANED
→ DEDUPLICATED
→ VALIDATED
→ READY
```

For discovery, only fields that can be established confidently should be populated. Leave uncertain values blank instead of inventing them.

## 6. Discovery crawler

The discovery crawler is responsible for exploring configured educational sites without downloading or extracting document contents.

Key considerations:

- it reads `configs/sources.yaml` and `configs/subjects.yaml`
- it only crawls sources with `enabled: true`
- it only crawls sources with `verified: true`
- it respects the configured source domain
- it avoids following external domains
- it normalizes URLs and prevents revisits
- it respects crawl depth and per-source page limits
- it uses a request delay to be polite
- it logs failures without stopping other work
- it identifies candidates without downloading files
- it supports `--dry-run` mode

### Example command

```bash
python3 -m pipeline.discovery.crawler --source alapiedu --dry-run
```

This preview mode is the safest way to test a discovered source before normal catalog updates are applied.

## 7. Adding a new source

1. Open `configs/sources.yaml`.
2. Add a new source entry with a stable lowercase snake_case `id`.
3. Confirm the official URL from a trustworthy source.
4. Set `enabled` to `true` only when the source is approved for crawling.
5. Set `verified` to `true` only after an explicit verification step.
6. Run a dry-run discovery against that source.
7. Inspect candidate classification and logs.
8. Only then proceed with normal-mode catalog updates.

A source should not be enabled unless it is relevant to the Sri Lankan educational corpus and the project has a legitimate reason to crawl it.

## 8. Adding subjects

Subjects are controlled by `configs/subjects.yaml`. This allows the project to evolve the taxonomy without hard-coding academic domains in Python files.

Add or update subject labels carefully and keep them aligned with the actual educational content used by the corpus. Do not invent subject names without justification.

## 9. Development workflow

Use a disciplined flow while working in the repository:

1. Create or switch to a feature branch.
2. Make a focused, reviewable change.
3. Run targeted tests or validation commands.
4. Run dry-run checks when relevant.
5. Inspect the git diff.
6. Commit with a clear conventional message.
7. Push and open a review if needed.

### Conventional commit examples

- `chore: add educational source configuration`
- `feat: implement document downloader`
- `fix: prevent duplicate catalog entries`
- `docs: update pipeline guide`

## 10. Testing

Testing should remain small and focused. Tests should validate:

- URL normalization
- duplicate detection
- domain restriction
- subject matching
- grade extraction
- document-type detection
- dry-run safety
- candidate filtering
- source verification logic

The repository currently demonstrates discovery-focused tests for candidate logic and source behavior.

## 11. Data safety

The project should preserve provenance and avoid accidental damage to source material:

- do not overwrite raw source documents without a clear workflow
- do not manually edit generated corpus data unless the process is documented
- do not fabricate metadata in the catalog
- do not commit secrets or local environment files
- do not version large local model files unless there is a deliberate policy for them
- keep catalog metadata and source configuration in Git while excluding generated local artifacts

## 12. Recovery / troubleshooting

Common issues and where to look:

- Source skipped because `verified: false` — check `configs/sources.yaml`.
- `robots.txt` unavailable — inspect discovery logs; this is not always a fatal condition.
- Too many candidates — review candidate filtering logic and subject/title matching.
- Duplicate candidates — inspect normalization and duplicate handling in the crawler.
- HTTP errors and timeouts — check discovery logs and network conditions.
- Malformed YAML — validate source and subject configuration files.
- Invalid catalog rows — review `corpus/catalog/documents.csv` and the expected schema.

Logs are stored under the relevant `corpus/logs/` subdirectories.

## 13. Current status

### Implemented

- `configs/subjects.yaml`
- `configs/sources.yaml`
- `corpus/catalog/documents.csv`
- discovery crawler
- dry-run mode
- candidate filtering

### Planned / not yet implemented

- downloader
- extraction
- OCR
- cleaning
- deduplication
- quality validation
- dataset generation

Only mark a stage as implemented if it exists in the repository and is actively maintained.

## 14. How to continue

The recommended next step is to proceed to the downloader stage only after the discovery stage is stable and the source list is verified. Do not begin extraction or dataset generation until the discovery and catalog stages are validated and the source configuration is intentional.

This keeps the pipeline predictable and helps preserve data provenance as the project grows.

## 15. Review and immediate continuation

The [8 October 2026 review index](README.md) incorporates the supplied project handover and links to confirmed defects, the source plan, stage/data contracts, and backlog. The crawler already separates crawlability from candidate suitability and has integer scores/reasons and navigation/listing tests. Remaining work is to fix edge cases and measure discovery precision/recall before downloading at scale.

The eight catalog entries are intended pilots with stable IDs and missing URLs. Preserve them, fill provenance from evidence, and do not queue incomplete rows for download. Source `verified` means approval to crawl, not document quality. Grade ranges are collection targets unless supported independently.

## 16. Adding a stage safely

Keep each stage in `pipeline/<stage>/`, with a small API/CLI and only necessary dependencies. Define input/output/state contracts first. Use offline fixtures for success, failure and interrupted/resumed processing. Persist outputs and verify hashes before updating catalog states. Preserve immutable raw files and previous successful outputs.

Add `configs/pipeline.yaml` when a consuming stage exists, with paths configurable for local and Drive/Colab runs. Colab scratch is not permanent storage. Use one catalog writer, checkpoint manifests and snapshots to persistent storage, and demonstrate recovery on the pilot.

Use [PIPELINE_DESIGN.md](PIPELINE_DESIGN.md), [DATA_CONTRACTS.md](DATA_CONTRACTS.md), and [IMPLEMENTATION_BACKLOG.md](IMPLEMENTATION_BACKLOG.md) for planned behavior and acceptance criteria. These specifications do not claim later stages are implemented.
