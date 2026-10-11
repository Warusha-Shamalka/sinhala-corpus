# PDF resource downloader

Implemented: bounded, resumable PDF acquisition from the CSV catalog. Discovery remains a separate stage and does not call the downloader automatically.

## Preview and run

From the repository root:

```bash
python3 -B -m pipeline.download.downloader --dry-run
python3 -B -m pipeline.download.downloader --source alapiedu --max-documents 1 --dry-run
python3 -B -m pipeline.download.downloader --doc-id LK-EDU-000009 --max-documents 1
```

The last ID is an example; it must exist in your catalog with a real URL. The eight initial pilots still have blank URLs and are excluded. Dry-run makes no requests, creates no output folders or locks, and does not change the catalog.

Settings are in [configs/pipeline.yaml](../../configs/pipeline.yaml). Use `--config` to select another configuration, `--sources` for another source registry, `--source` to select a source ID and repeat `--doc-id` for explicit documents. Paths are repository-relative or absolute, so persistent storage can be selected without editing code.

## Production save locations

With the current configuration, production output is saved under the repository root:

```text
corpus/raw/pdf/<doc_id>/<sha256>.pdf       # Original downloaded PDF
corpus/raw/pdf/<doc_id>/<sha256>.json      # Provenance receipt
corpus/catalog/documents.csv              # Document status, artifact path and hash
corpus/logs/download/download_*.jsonl      # Per-document run events
```

The CLI prints a structured report to the terminal; a summary JSON file is not automatically saved. Redirect stdout to a file if you want to retain that report. Raw PDFs, receipts and transient logs are ignored by Git. Catalog metadata remains trackable.

The existing live smoke-test PDF is under `corpus/logs/download/smoke_20261009/raw/`, which is an isolated test store. It is not a production download. The production catalog currently contains eight URL-less pilots, so its download preview selects zero jobs.

## Default production limits

| YAML key | Default | Applies to |
|---|---:|---|
| `max_documents` | 5 | Jobs selected per invocation, including integrity-verification jobs |
| `max_bytes` | 52428800 (50 MiB) | Each newly transferred PDF |
| `max_seconds` | 300 seconds | Each source fetcher, shared across its jobs in the run |
| `timeout_seconds` | 20 seconds | Blocking socket operations |
| `request_delay_seconds` | 1 second | Minimum request spacing; robots rules can increase it |
| `max_requests` | 50 | Per source, including robots, redirects and retries |
| `max_retries` | 2 | Extra attempts for a transient request-opening failure |
| `max_retry_wait` | 30 seconds | Largest acceptable retry wait; longer server waits are deferred |

Edit the `download` section of `configs/pipeline.yaml` to change these values. `--max-documents` overrides only the batch size for one run. The defaults are guardrails, not estimates of file quality or website capacity. Time budgets are checked between operations; they are not hard process deadlines.

Only PDFs are currently supported. HTML pages, scans in image formats and office documents need later format-specific handling. Initial/redirected resource hosts must match the configured base host exactly; external CDNs and source subdomains are excluded.

Eligible states are `DISCOVERED`, `DOWNLOAD_FAILED`, and `DOWNLOADED` for integrity verification. Fresh jobs are considered before downloaded ones. Only sources with enabled/verified flags and matching catalog source names qualify. Initial and redirected resource hosts must exactly match the configured base host; external CDNs and subdomains are currently excluded. Robots policies are checked before the original resource request and redirect target GETs. Source approval is crawl/collection configuration, not proof of document language or redistribution rights.

## Artifacts and state

Successful downloads are stored as:

```text
<raw_root>/pdf/<doc_id>/<sha256>.pdf
<raw_root>/pdf/<doc_id>/<sha256>.json
```

The JSON receipt records requested/final URLs, source ID, HTTP status, MIME, bytes, SHA256, artifact path, UTC timestamps, ETag/Last-Modified when supplied, pipeline version and robots outcomes. Remote filenames and Content-Disposition never control local paths. Raw PDFs are not overwritten. A repeated hash reuses its artifact; a changed hash creates a separate version.

Only HTTP 200 responses with PDF/octet-stream MIME, `%PDF-` at the beginning and `%%EOF` near the end qualify. HTML/login/error bodies, compressed transport, bad signatures, partial responses, Content-Length mismatch and excessive sizes fail. These are basic transfer checks, not complete PDF structural validation or educational-content verification; extraction must validate actual readability later.

After the file and receipt are persisted, a locked compare-and-set updates the original catalog row to `DOWNLOADED`, with artifact path/hash, processing version/time and empty error. Unrelated rows, extension columns and metadata are preserved. Failed new downloads become `DOWNLOAD_FAILED` with an error and may be retried on the next invocation. A failed refresh keeps the previous successful catalog state/artifact.

If execution stops after receipt persistence but before the catalog update, restart verifies the receipt/file and completes the checkpoint without another request. A raw file without a receipt may require a fresh transfer; its existing bytes are verified before reuse. Corrupted existing artifacts are reported and never overwritten. `--refresh` intentionally fetches again while retaining earlier raw versions. It is normally used with explicit document IDs.

Events are written to `<log_root>/download_*.jsonl`; the CLI also prints its structured run report. Exit codes: 0 for successful/empty/dry runs, 1 for per-document failures or catalog conflicts, 2 for invalid configuration/catalog or worker-lock failures. Zero eligible jobs means no documents downloaded.

## Operating limits

Use one downloader and one catalog on a local POSIX filesystem. A separate worker lock serializes download runs; the existing CSV lock protects each catalog checkpoint while allowing discovery to operate between checkpoints. Raw/catalog files and receipt files are fsynced, with directory syncing for replacements. Google Drive/Colab deployment and filesystem durability semantics have not yet been demonstrated; do not claim cloud multi-writer support.

Request retries cover transient opening/HTTP failures. Interrupted response bodies are cleaned up and retried from the beginning on a later run; HTTP Range/partial-byte resume is not implemented. Time budgets are checked between operations and reads, so a blocking socket read can overrun by its timeout. Other resource formats, authenticated downloads, external resource hosts, extraction and OCR remain planned.

Run all offline tests with `python3 -B scripts/check_offline.py`. See [download validation](../../docs/DOWNLOAD_VALIDATION_RESULTS.md) for verification and the isolated live smoke test. Raw files and logs remain ignored by Git; keep catalog/config/code/docs and move accepted corpus data to persistent storage under the project's storage policy.
