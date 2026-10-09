# PDF download stage: implementation and validation

Implemented on `feat/pilot-downloader` from `dev` commit `d4e113c`. The branch has no inherited upstream to `dev`; publish it explicitly as its own branch before opening a PR. Benchmark taxonomy/model work was deferred to the separate training repository, as requested by the maintainer.

## Implemented

- Configured PDF queue with explicit source/document selection and five-job default.
- Real URLs and enabled/verified sources required; incomplete pilots excluded.
- Exact base-host restriction, including redirect checks before target GETs.
- Shared transport preserves discovery defaults while adding a resource API and download User-Agent; robots policies and transient request retries are reused.
- Bounded streaming, MIME/signature/end-marker checks, size/deadline checks and temporary-file cleanup.
- SHA256-named immutable raw PDFs and versioned fetch receipts; remote filenames do not determine local paths.
- Separate single-download-worker lock; locked compare-and-set catalog checkpoints preserve other rows/extension columns.
- Restart recovery from persisted receipts; local integrity checks avoid repeated downloads.
- Explicit refresh retains previous raw versions; failed refresh keeps the successful catalog entry.
- Per-document events and structured CLI reports; dry-run has no network or filesystem writes.

Usage, limits and operating assumptions are documented in [the downloader guide](../pipeline/download/README.md). `configs/pipeline.yaml` is consumed by this stage; other stages remain planned.

## Offline tests

```bash
python3 -B scripts/check_offline.py
```

Result: **109 tests passed**, including **20 new download tests**. Coverage includes dry-run safety, incomplete/disabled/external candidates, successful transfers, catalog extension preservation, verified reruns, changed/identical versions, failed refresh, checkpoint interruption/recovery, corrupted stored files, HTML/error bodies, signature/end-marker/length failures, byte limits without Content-Length, interrupted reads, external final URLs, compare-and-set conflicts, job limits, worker exclusion, malformed receipts and redirect robots enforcement. The PDF test bytes are synthetic transport fixtures, not fully parseable educational documents.

## Production-catalog preview

```bash
python3 -B -m pipeline.download.downloader --dry-run
```

Result: zero eligible jobs; all eight original pilots excluded with `missing_source_url`. No primary catalog/configuration/taxonomy/review-label changes. This successful dry-run does not imply that the master corpus already has downloaded documents.

## Isolated live smoke test

Used an ignored test catalog/configuration under `corpus/logs/download/smoke_20261009/`, preserving the real catalog. It copied the eight existing placeholders and added temporary IDs 9 and 10 from the existing review sample. Those IDs belong to this isolated catalog only. `document_type=other` and blank subject/grade/language avoid treating unreviewed crawler predictions as verified metadata.

Bounds: one selected job, 10 MiB, 60 seconds per source, 10 requests, one transient retry. The source was the existing approved AlApiEdu host. No hidden benchmark dataset was accessed.

1. The “Pure Maths Full Short Note New Syllabus” candidate was rejected because its declared size exceeded the test limit. No PDF artifact was saved; the isolated row became `DOWNLOAD_FAILED`.
2. The saved 2020 Combined Maths Part I candidate downloaded successfully:

| Field | Observed value |
|---|---|
| HTTP status / MIME | `200` / `application/pdf` |
| Bytes | `2106892` |
| SHA256 | `fdb72cbc663ddb8edc67d420b25c6c33ed149945408709ec2fbe09639441b338` |
| Catalog outcome | `DOWNLOADED` |
| Robots outcome | `absent` after HTTP 404 |
| Repeated run | `verified_existing`, same hash, no network transfer |

The filename/title describe the discovery candidate, not independently reviewed subject, grade, answer correctness or redistribution permission. Only transfer checks and stored integrity were verified.

Commands for the existing local smoke setup:

```bash
python3 -B -m pipeline.download.downloader --config corpus/logs/download/smoke_20261009/pipeline.yaml --doc-id LK-EDU-000010
```

Smoke setup/data are local ignored artifacts, not required by CI or distributed as repository test data. Events and a receipt remain beside the isolated raw file. Keep these separate from the master corpus; configure accepted production data on persistent storage before broader collection.

## Scope and next steps

The maintainer authorised proceeding with candidate suitability as a provisional assumption. Independent human review remains pending and no precision/accuracy claim is made.

Next: select real resource URLs for the production catalog, preserving any existing pilot IDs, run a one-document production preview, then acquire a bounded batch. Demonstrate persistent-store backup/recovery before scaling. PDFs are the only implemented download format. HTML/scans/office formats, external CDNs, authentication and byte-range resume need separate design/testing. Basic PDF signatures do not replace PDF parsing, extraction quality checks or reviewed educational-content metadata.

A future metadata fix should distinguish “Sinhala medium” from the subject Sinhala, and “new syllabus” describing a paper/notes version from a syllabus document. These issues were visible in sample titles; this download change leaves the original predictions and review sample intact.
