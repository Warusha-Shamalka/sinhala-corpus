# PDF extraction validation — 11 October 2026

Branch: `feat/pdf-extraction`. Backend: local Poppler 26.08.0 (`pdfinfo` and `pdftotext`). These are corpus engineering observations, not SinhalaMMLU benchmark results.

## Real pilot

Seven PDFs were present in the production catalog at inspection time (the earlier six-document checkpoint had gained `LK-EDU-000015`). All seven raw SHA256/size values matched their catalog identities and download receipts. All PDFs opened with pdfinfo and reported no encryption.

The trial used a copied catalog at `corpus/logs/extraction/pilot_20261011/documents.csv`. It wrote actual bundles under `corpus/extracted/pages/` and its report to `corpus/logs/extraction/pilot_20261011/report.json`. **Production catalog bytes were unchanged**, and raw PDFs/receipts were not modified.

| Document | Pages inspected | Native non-whitespace characters | Pages flagged for OCR review | Result |
| --- | ---: | ---: | ---: | --- |
| LK-EDU-000009 | 41 | 0 | 41 | ocr_required |
| LK-EDU-000010 | 54 | 0 | 54 | ocr_required |
| LK-EDU-000011 | 6 | 0 | 6 | ocr_required |
| LK-EDU-000012 | 6 | 0 | 6 | ocr_required |
| LK-EDU-000013 | 8 | 0 | 8 | ocr_required |
| LK-EDU-000014 | 8 | 0 | 8 | ocr_required |
| LK-EDU-000015 | 9 | 0 | 9 | ocr_required |
| **Total** | **132** | **0** | **132** | **7 routed, 0 failed** |

The initial run completed in approximately 26 seconds on this machine. The first page of LK-EDU-000011 was rendered and visually inspected: handwritten Sinhala mathematical notes, formulas and a scanner watermark were visible. This supports OCR routing for that page; the remaining pages were assessed by native-text extraction rather than individual visual review. No OCR was run, and no recognition accuracy is claimed.

Empty native text is visible in the records and is not silently treated as clean educational text. All pilot rows remain `DOWNLOADED` with `ocr_required=true` in the copied catalog. A successful extraction run here means the page inspection/routing completed, not that training-ready text exists.

## Reproduction and next manual check

Install the tools and run the commands in [EXTRACTION_GUIDE.md](EXTRACTION_GUIDE.md). The outputs and trial logs are generated artifacts ignored by Git; they exist in the local workspace and are not part of a clone.

To update one production row after reviewing the trial:

```bash
python3 -B -m pipeline.extraction.extractor --doc-id LK-EDU-000011 --max-documents 1 --progress plain
```

With the same backend/configuration, this verifies and reuses its completed bundle, then checkpoints the production catalog. A different Poppler version gets a different fingerprint and runs a separate extraction. Read the final `bundle_path`, `ocr_pages` and `outcome`, then inspect the manifest/page records. Expected local pilot result: 6 pages flagged, `ocr_required`, zero native text; this is the honest OCR-needed result, not an extraction crash.

The next development step is selective OCR with reviewed Sinhala handwriting/equation examples and measured accuracy. Native PDF extraction tests use separate synthetic fixtures to validate successful text extraction because this downloaded pilot provides no native text pages.

## Offline checks

`python3 -B scripts/check_offline.py`: **141 tests passed**, including real Poppler native/blank fixtures and the existing discovery/downloader regressions. The CLI dry-run selected LK-EDU-000009 with no results or progress file. `git diff --check` passed. Tests use isolated temporary catalogs and raw fixtures.
