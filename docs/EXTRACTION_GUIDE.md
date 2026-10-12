# PDF extraction guide

This guide covers the standalone native PDF extractor: page/block/word coordinates, provenance, OCR routing flags, immutable bundles, catalog checkpoints, retry recovery and progress. The separate production workflow now provides Surya OCR, static HTML extraction, conservative cleaning and reviewed dataset export; see [CORPUS_PRODUCTION_GUIDE.md](CORPUS_PRODUCTION_GUIDE.md). Full image/table asset extraction remains planned.

## Setup and first run

Use a POSIX environment with Python 3.11–3.14 and the existing pinned Python requirements. Install the system PDF tools too:

```bash
python3 -m pip install -r requirements.txt
sudo apt-get update
sudo apt-get install -y poppler-utils
pdfinfo -v
pdftotext -v
```

The apt commands apply to Debian/Ubuntu and Colab. On other Linux distributions use their package manager. `pdfinfo` and `pdftotext` must be on PATH. CI installs poppler-utils and exercises the real backend with synthetic native/blank PDFs. The system package is not pinned by requirements.txt: exact tool versions are recorded in every extraction configuration/manifest and affect the output fingerprint. For identical backend reproduction, preserve the OS/container and Poppler version alongside the manifest. The local pilot used Poppler **26.08.0**.

Preview without launching PDF tools, hashing raw files, creating locks, writing logs or changing the catalog:

```bash
python3 -B -m pipeline.extraction.extractor --source alapiedu --max-documents 1 --dry-run
```

Process one selected document:

```bash
python3 -B -m pipeline.extraction.extractor --doc-id LK-EDU-000011 --max-documents 1 --progress plain
```

The second command verifies raw data, creates or verifies an extraction bundle, logs its outcome and updates the production catalog. `--source` accepts a configured source ID (such as `alapiedu`) or source name. `--sources` selects an alternate source config. This stage makes no HTTP requests and does not require source crawl approval again: it operates on previously downloaded local artifacts. `--config` selects another pipeline YAML; relative configured paths are resolved from the repository root.

The final report is JSON on stdout. Progress uses stderr. `--progress auto|plain|off` and `--quiet` behave as described in [PROGRESS_GUIDE.md](PROGRESS_GUIDE.md). Check the actual `progress_path` returned in the report with `python3 -B -m pipeline.progress "actual/path.progress.json"`.

## Eligibility, limits and states

Rows in `DOWNLOADED`, `EXTRACTION_FAILED` or `EXTRACTED` with a raw PDF filename/hash are eligible. Later stages (`CLEANED` and beyond) are excluded so extraction cannot move them backwards. Already-extracted rows are verified and reused; already-downloaded rows awaiting OCR are also reused. Batch limits apply to selected jobs, including verification jobs. Use `--doc-id` to target new work. Other selection/exclusion reasons appear in the report.

Settings in `configs/pipeline.yaml` under `extraction`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_documents` | 5 | Maximum selected jobs per run |
| `max_pages` | 500 | Reject larger documents rather than truncate |
| `max_raw_bytes` | 52,428,800 | Maximum raw PDF size for extraction |
| `max_page_bytes` | 10,485,760 | Child command stdout/stderr file limit per page |
| `max_output_bytes` | 104,857,600 | Combined serialized page/text byte limit per document |
| `max_seconds` | 300 | Extraction budget from PDF inspection through page parsing; each command uses the remaining budget |
| `command_timeout_seconds` | 20 | Timeout per PDF inspection/page command |
| `min_text_chars` | 20 | Flag pages with fewer non-whitespace characters |
| `max_replacement_ratio` | 0.02 | Flag pages with a higher U+FFFD replacement-character fraction |

Backend version checks occur at startup. Raw verification, final hashing and disk checkpoints are outside the per-command time limit. Commands use bounded output files and POSIX file-size limits; these are processing limits rather than a complete sandbox for the PDF engine. Commands are passed as argument lists, with no shell. Encrypted PDFs are rejected. Parser failures, missing receipts, raw hash/size mismatches, timeouts and page/output limits are visible failures, not successful empty extractions.

| Result | Catalog behavior |
| --- | --- |
| `extracted` | All native pages processed; set `EXTRACTED`, method, page count and `ocr_required=false` |
| `ocr_required` | All native pages inspected; retain `DOWNLOADED`, set method, page count and `ocr_required=true` |
| `failed` | Set `EXTRACTION_FAILED` for previously downloaded/failed rows; preserve an existing `EXTRACTED` success while recording the new failure in the event log |
| `catalog_conflict` | Keep the concurrently changed row; retain completed bundle for recovery |

`EXTRACTED` means native extraction completed, not that the text passed academic/linguistic quality validation. `quality_score` is left unchanged. No partial page set is promoted or committed as a complete bundle. A process exit code of 0 means all selected jobs were processed successfully, including OCR routing; it does **not** mean OCR has run. Exit 1 signals job failure/conflict; 2 signals setup/catalog/backend errors; Ctrl+C exits 130.

OCR flags are conservative **review/routing heuristics**, not proof of scanning. Blank pages and short formula pages can be flagged too. Latin text encoded with a legacy Sinhala font may look like ordinary text to these heuristics: manual review remains necessary. The extractor does not normalize Unicode, translate text, invent missing equations or claim an OCR confidence score.

## Output paths and page contract

Raw PDFs and download receipts are never overwritten. Raw receipt identity, SHA256, size, requested URL and catalog path must agree before parsing. The raw hash is checked again before committing a newly extracted bundle.

```text
corpus/extracted/pages/<doc_id>/<raw_sha256>/<config_hash>/
  pages.jsonl
  text.txt
  manifest.json
corpus/logs/extraction/
  extraction_<timestamp>_<suffix>.jsonl
  extraction_<timestamp>_<suffix>.progress.json
```

These paths are configurable. The text file lives **inside the same bundle** as its page records, so one directory rename commits all three artifacts together. It is not written into `corpus/extracted/text/` by this first implementation. That directory remains available for future text-only exports. Outputs/logs are ignored by Git; code/config/docs remain tracked.

Each `pdf-pages-1` record uses **one-based `page_number`** and zero-based `block_index`. It contains raw hash, document ID, method/version/backend/config identity, page dimensions in PDF points, blocks/lines/words with coordinates, extracted text, OCR reason flags, character measurements, pending quality review and errors. The text is reconstructed from Poppler-emitted word/line/block order, preserving emitted Unicode tokens; spacing and reading order are backend estimates, not guaranteed original layout. UTF-8 `text.txt` separates pages with form-feed/newline. No cleaned or normalized version is produced yet.

`assets=[]` and `assets_status=not_extracted` explicitly indicate that figures/table assets have not been exported. Original PDFs remain the source for all visual material. OCR is `not_run` with null confidence. Backend warnings are retained in page records and metadata warnings in the manifest. Neither word boxes nor reconstructed strings fully preserve equation meaning or table relationships.

The `pdf-extraction-1` manifest records document/raw/config identity, complete page count, OCR count, outcome, pending review and hashes for pages/text. The config fingerprint includes extraction version, backend versions, thresholds and processing limits, excluding storage paths and batch size. Changing these settings produces a separate bundle. Existing bundles are verified, including page identity/counts and output hashes, and reused without rewriting them. Corrupt bundles fail rather than being overwritten. Do not manually edit generated bundles.

One extraction-worker lock protects a run. Catalog updates use the existing compare-and-set CSV checkpoint lock, coordinating with discovery/downloading. Finished bundles can survive a catalog conflict or crash; rerunning verifies/reuses them and retries the checkpoint. Ctrl+C cleans this worker's incomplete bundle and records interruption. A hard kill can leave a `.extract-*` temporary directory: those directories are never treated as completed outputs. Remove an abandoned directory only after confirming no worker is using it. Completed raw data is unaffected.

Progress shows documents completed and the **current document's** pages completed/total and OCR page count. Unlike discovery, PDF page totals are known after inspection. An OCR-routed document counts as a completed extraction job, with its separate `ocr_required` result count. No OCR completion percentage is implied.

## Validation and next stage

```bash
python3 -B scripts/check_offline.py
```

Tests cover native Sinhala layout fixtures, real native/blank PDFs, mixed-page routing, malformed/encrypted PDFs, replacement characters, raw corruption, output corruption, page/output/command limits, idempotent reuse, config changes, interruptions, catalog conflicts and dry-run safety. See [EXTRACTION_VALIDATION_RESULTS.md](EXTRACTION_VALIDATION_RESULTS.md) for the real pilot.

Next: run the two-page production Colab trial and review its source images against the transcription. The pilot includes handwriting and equations, so successful printed-text OCR alone will not establish quality on these documents. Production output is separately versioned and requires source-checked human corrections before dataset export.
