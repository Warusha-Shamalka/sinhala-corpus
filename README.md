# Sinhala / Sri Lankan Educational Corpus

This repository is being built to support research and downstream machine-learning work on Sinhala and Sri Lankan educational content. The project focuses on discovering relevant educational materials, cataloging them, and eventually turning them into clean, validated datasets for training or evaluation.

## Project purpose

The project collects and organizes educational resources relevant to Sri Lanka, especially Sinhala-language materials used in school education. The emphasis is on disciplined pipeline work: discover candidates, record them in the catalog, download only approved content, extract and clean data, validate quality, and produce derived datasets.

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

These files are treated as authoritative project metadata. They should be preserved and updated intentionally.

## Current pipeline stages

Implemented:
- discovery crawler
- discovery dry-run support
- source/subject configuration
- document catalog metadata

Planned / not yet implemented:
- downloader
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

The main handoff and continuation guide is in:

- `docs/PIPELINE_GUIDE.md`

Use that file to understand the end-to-end pipeline and the intended next steps.

## Current status summary

Implemented:
- subject configuration
- source configuration
- discovery crawler
- dry-run discovery
- catalog metadata tracking

Planned / not yet implemented:
- downloader
- extraction
- OCR
- cleaning
- deduplication
- quality validation
- dataset generation

The repository is intentionally structured so that these later stages can be added without disrupting the configured discovery and catalog setup.
