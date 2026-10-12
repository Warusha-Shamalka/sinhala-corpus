# Pipeline progress and background status

Implemented for discovery, PDF downloading and native PDF extraction. Selective OCR progress is implemented; cleaning adapters remain planned. Progress observes work; it does not change download limits, source approval, raw storage or catalog states.

## Run with visible progress

```bash
python3 -B -m pipeline.discovery.crawler --source alapiedu --dry-run --progress plain --json
python3 -B -m pipeline.download.downloader --source alapiedu --max-documents 5 --progress plain
```

The download command performs real downloads/checkpoints. Discovery dry-run still fetches HTML and writes audit logs, but does not modify the catalog or download resources. Downloader dry-run performs no network requests and writes no snapshots or other files:

```bash
python3 -B -m pipeline.download.downloader --source alapiedu --max-documents 5 --dry-run
```

`--progress auto` is the default: a terminal updates one line, while redirected output uses separate lines. `--progress plain` uses separate lines everywhere, including Colab. `--progress off` suppresses progress output while still saving snapshots for active runs. `--quiet` also suppresses discovery console logging; downloader request warnings may still appear. Final reports remain visible. Updates for transfer chunks and repeated crawl observations are throttled to one second; phase changes and final totals are emitted immediately.

Progress uses **stderr**. Download JSON remains on **stdout**. Discovery retains its existing human-readable stdout by default; add `--json` for a single JSON report. For a background download:

```bash
python3 -B -m pipeline.download.downloader --source alapiedu --max-documents 5 --progress plain > download-report.json 2> download-progress.log &
```

Run this from the repository root using the project's installed dependencies. Do not launch a second downloader against the same catalog: the worker lock prevents concurrent download workers.

## What the numbers mean

Discovery shows the current source/page, pages visited, queued URLs, unique accepted candidates, unique rejected URLs, requests, retries, elapsed time and source stop reason. These counts describe the **current source**, resetting at each source boundary. Accepted candidates can already exist in the catalog; the final `candidates_to_add` count accounts for catalog and cross-source duplicates. Rejected URL counts and accepted URL counts can overlap if different observations produce different decisions. The crawl total is unknown, so no website completion percentage is shown. Page/depth/request/time caps still apply.

Downloads show selected jobs completed out of the selected total, current document, and separate downloaded/verified-existing/recovered/failed/catalog-conflict counts. A job becomes completed after its result has been checkpointed and recorded, including failed jobs. `deferred` counts catalog rows excluded by `batch_limit`: these are outside this batch, not errors. Other exclusions remain in the final JSON report.

During transfer, progress shows received MiB, known total size, percent, average transfer speed and approximate ETA when enough information exists. Without Content-Length, only received bytes and speed are shown. ETA describes the transfer, not later disk writes, verification or the entire batch. Download completion is recorded only after transport checks, raw persistence and the catalog checkpoint.

Phases include robots lookup, connection, rate/retry wait, transfer, stored-file verification, raw persistence and catalog checkpoint. Missing robots.txt (404/410) appears as `robots=absent`; its HTTP status is retained in the snapshot. Other policy failures remain conservative. Snapshot request/retry counters describe the current source fetcher; final discovery audit statistics remain authoritative.

## Inspect a background run

Each CLI discovery run saves a snapshot alongside its audit files:

```text
corpus/logs/discovery/<run-stem>.progress.json
```

Active CLI download runs save:

```text
corpus/logs/download/download_<timestamp>_<suffix>.progress.json
```

Downloader uses the configured `download.log_root`; discovery uses its existing log directory. The final JSON report contains `progress_path`. Downloader dry-runs and batches with no eligible jobs do not create a snapshot. Python callers can opt in with `run(..., progress_mode="plain")`; existing downloader Python calls remain silent by default.

Find snapshots and inspect the exact run you want:

```bash
rg --files --hidden --no-ignore corpus/logs -g '*.progress.json'
python3 -B -m pipeline.progress corpus/logs/download/<run-stem>.progress.json
python3 -B -m pipeline.progress corpus/logs/download/<run-stem>.progress.json --json --stale-after 120
```

Replace `<run-stem>` with an actual filename. The checker is read-only and uses no network. It reads a single snapshot; rerun it to refresh the display. It does not monitor processes, pause/resume a run, or modify the catalog.

Snapshots record schema version, run ID, PID, stage, source/item, phase, counters, transfer information and UTC timestamps. They are replaced atomically so readers see a complete old or new snapshot. Terminal/snapshot write failures disable the affected progress channel without changing pipeline processing outcomes. Snapshots/logs are generated data and are ignored by Git.

Recorded statuses are `running`, `completed`, `partial`, `failed`, `skipped` and `interrupted`. Ctrl+C records `interrupted` and the CLI exits 130; already completed artifacts/checkpoints remain. Abrupt termination or machine failure may leave `running`. The checker labels an old running snapshot `possibly_stale` without changing its recorded status. Slow blocking reads, hashing or long waits can also produce stale snapshots: there is no separate heartbeat thread, and staleness does not prove failure. Inspect the event/audit logs before restarting. Existing receipt recovery remains the mechanism for recovering completed downloads.

## Verify changes

```bash
python3 -B scripts/check_offline.py
```

Offline tests cover known/unknown transfer sizes, rate/ETA, throttling, stderr/stdout separation, quiet output, snapshot failure handling, read-only/stale checks, robots absence/retry phases, interruptions, final discovery/download counters, verification of existing artifacts and downloader dry-run write safety. Tests use temporary catalogs and synthetic HTTP fixtures; they do not download educational content or modify the production catalog.

## Extraction progress

See [EXTRACTION_GUIDE.md](EXTRACTION_GUIDE.md). Extraction saves snapshots under configured `extraction.log_root`, normally `corpus/logs/extraction/`. Counters show jobs plus the current PDF's pages completed/total and OCR-flagged pages. `ocr_required` counts successfully routed documents, not OCR work completed. Extraction dry-runs and empty job sets create no snapshots.

## OCR progress

The [OCR stage](OCR_GUIDE.md) saves snapshots under `ocr.log_root` (normally `corpus/logs/ocr/`). It reports selected pages attempted/completed and failures, with the current document/page. `completed` means the selected OCR sample finished; every saved page still needs review, and unselected document pages are not complete. Dry-runs create no snapshots.
