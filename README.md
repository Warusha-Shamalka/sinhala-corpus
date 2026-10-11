# Sinhala / Sri Lankan Educational Corpus

This repository is being built to support research and downstream machine-learning work on Sinhala and Sri Lankan educational content. The project focuses on discovering relevant educational materials, cataloging them, and eventually turning them into clean, validated datasets for training or evaluation.

## Project purpose

The project collects and organizes educational resources relevant to Sri Lanka, especially Sinhala-language materials used in school education. The emphasis is on disciplined pipeline work: discover candidates, record them in the catalog, download only approved content, extract and clean data, validate quality, and produce derived datasets.

SinhalaMMLU is a key use case. Corpus preparation is separate from challenge inference, which must use model weights and a prompt within the supplied 8B cap, without internet or retrieval. General corpus products may support other research. Google Drive is the intended persistent store and Colab is temporary compute; this deployment is planned, not configured here.

See the [detailed architecture diagrams](docs/PIPELINE_ARCHITECTURE.md) for stage-by-stage behavior, persistence and planned processing.

## High-level architecture

- `configs/` stores controlled source and subject configurations.
- `corpus/` stores raw, extracted, cleaned, and catalog data.
- `datasets/` stores derived datasets, not original source documents.
- `pipeline/` contains the stages used to process the corpus.
- `docs/` contains handoff and project guidance.

## Repository structure

```text
configs/
corpus/
datasets/
pipeline/
docs/
README.md
```

## Corpus vs. datasets

The `corpus/` area represents the source-oriented data pipeline: raw downloads, extracted pages, cleaned data, and metadata. The `datasets/` area is used for products derived from the corpus, such as evaluation sets or instruction data. Raw sources and derived datasets are distinct concepts and should not be conflated.

## Configuration files

The project uses configuration-driven discovery rather than hard-coded site or subject lists.

- `configs/sources.yaml` defines which sources are valid and enabled.
- `configs/subjects.yaml` defines the subject taxonomy and grade ranges.
- `configs/pipeline.yaml` defines download storage paths and batch/transfer limits.

These files are treated as authoritative project metadata. They should be preserved and updated intentionally.

## Current pipeline stages

Implemented:
- discovery crawler
- discovery dry-run support
- bounded PDF downloader with immutable raw files, receipts and catalog checkpoints
- source/subject configuration
- document catalog metadata
- offline discovery review sampling and reporting
- pinned dependencies and automated regression/review checks

Planned / not yet implemented:
- extraction
- OCR
- cleaning
- deduplication
- quality validation
- dataset generation

## Development environment

Use a Python virtual environment for local development.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install only the dependencies that a concrete stage requires. This repository does not assume a large general-purpose dependency set until a later stage genuinely needs it.

The implemented stages use PyYAML, pinned in `requirements.txt`. Target runtime: Python 3.11–3.14 on Linux/POSIX (catalog locking uses `fcntl`). CI checks this version range; local verification so far uses Python 3.14.7.

```bash
python -m pip install -r requirements.txt
python -B scripts/check_offline.py
```

The check command runs the regression suite and validates all tracked review CSV/manifest bundles. Unfinished reviews are allowed; malformed labels or altered candidate evidence fail validation. It blocks network connections and DNS lookups in the main check process. GitHub Actions runs it for PRs targeting `dev` or `main` and pushes to those branches. Dependency installation requires network access; the tests do not crawl websites.

See [the development checks guide](docs/DEVELOPMENT_CHECKS.md) for setup, CI behavior and troubleshooting.

## How to run discovery

From the repository root:

```bash
python3 -m pipeline.discovery.crawler --source alapiedu --dry-run
```

Normal dry-run behavior:
- loads configured sources and subjects
- filters to enabled + verified sources
- crawls within the configured domain
- logs candidate decisions
- previews additions without modifying `corpus/catalog/documents.csv`

## How documents.csv works

`corpus/catalog/documents.csv` is the catalog of discovered and tracked corpus entries. It is the source-of-truth metadata record for candidate resources, and it must be preserved carefully. New discovery records should append only when the source URL is new and the evidence is strong enough for the discovery stage.

Important rules:
- do not fabricate metadata
- do not overwrite existing catalog rows without deliberate process control
- do not add raw documents or generated datasets into the catalog area
- keep status values consistent with the pipeline stage model

## Where raw, extracted, and clean data belongs

- `corpus/raw/` holds downloaded or retained source files before processing
- `corpus/extracted/` holds text, page-level output, or extracted data
- `corpus/clean/` holds cleaned and validated corpus artifacts
- `corpus/catalog/` stores the metadata table for discovered corpus items
- `corpus/logs/` stores discovery, extraction, and other operational logs

## Where logs belong

Operational logs should be written under `corpus/logs/` or a stage-specific subdirectory. Logs are useful for troubleshooting and auditability but should not replace authoritative metadata and configuration files.

## How contributors add sources

1. Update `configs/sources.yaml`.
2. Use a stable, machine-readable `id`.
3. Set `enabled: true` only when the source is approved for crawling.
4. Set `verified: true` only after the official URL has been checked.
5. Run a dry-run before any normal discovery.
6. Review candidate classification and logs.

## Git workflow

Use a focused workflow that keeps repository changes reviewable:

```bash
git checkout -b feature/your-change
git status
git add <files>
git commit -m "feat: update discovery documentation"
git push
```

Keep configuration, code, and documentation changes explicit. Avoid large accidental commits of generated data or downloaded content.

## Additional documentation

See [the project TODO list](docs/TODO.md) for completed milestones and remaining work.

The main handoff and continuation guide is in:

- `docs/PIPELINE_GUIDE.md`

The competition review, confirmed bugs, source plan, data contracts, implementation backlog, and report/manifest templates are indexed in [docs/README.md](docs/README.md). The current catalog contains eight intended pilots without source URLs. Finish discovery validation before bulk downloading.

In this project, `verified` is explicit source approval for crawling. It does not verify all hosted documents, their language, answer correctness, or redistribution rights. Preserve separate evidence for those checks.

Use that file to understand the end-to-end pipeline and the intended next steps.

## Current status summary

Implemented:
- subject configuration
- source configuration
- discovery crawler
- bounded PDF downloader
- dry-run discovery
- catalog metadata tracking

Planned / not yet implemented:
- extraction
- OCR
- cleaning
- deduplication
- quality validation
- dataset generation

The repository is intentionally structured so that these later stages can be added without disrupting the configured discovery and catalog setup.

## Downloading resources

Preview the download queue with `python3 -B -m pipeline.download.downloader --dry-run`. The initial pilots have no URLs, so they do not qualify yet. See the [downloader guide](pipeline/download/README.md) before selecting a small batch. It supports PDFs; extraction, OCR and other resource formats remain planned. Candidate suitability is currently a provisional project assumption while independent review is pending.

Production PDFs and receipts save to `corpus/raw/pdf/<doc_id>/<sha256>.pdf` and `.json`. After validation and persistence, the downloader checkpoints the catalog to `DOWNLOADED`; events go to `corpus/logs/download/`. Earlier raw versions are retained.

Defaults are five jobs per run, 50 MiB per PDF, 300 seconds and 50 requests per source, a 20-second socket timeout, at least one second between requests, two transient request retries and a 30-second maximum retry wait. Edit [configs/pipeline.yaml](configs/pipeline.yaml) to change paths or limits. See [production save locations and limits](pipeline/download/README.md#production-save-locations) for exact scope and restrictions. The isolated smoke-test download is under `corpus/logs/download/smoke_20261009/raw/`; the production catalog currently has zero eligible jobs.
