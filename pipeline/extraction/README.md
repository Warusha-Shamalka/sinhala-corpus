# PDF extraction

Implemented: local Poppler PDF extraction with page/block/word provenance, OCR-needed routing, immutable bundles, verified restart recovery and catalog checkpoints. This stage reads verified downloaded PDFs; it makes no network requests and does not perform OCR or cleaning.

```bash
python3 -B -m pipeline.extraction.extractor --source alapiedu --max-documents 1 --dry-run
python3 -B -m pipeline.extraction.extractor --doc-id LK-EDU-000011 --max-documents 1 --progress plain
```

The second command writes outputs/logs and checkpoints the catalog. Install `poppler-utils` in addition to the Python requirements. See the [extraction guide](../../docs/EXTRACTION_GUIDE.md) for dependency setup, output paths, limits, schemas, statuses and recovery, and [pilot results](../../docs/EXTRACTION_VALIDATION_RESULTS.md) for the seven-document trial.

Outputs live under `corpus/extracted/pages/<doc_id>/<raw_sha256>/<config_hash>/` as `pages.jsonl`, `text.txt` and `manifest.json`. Raw data stays unchanged. Pages with insufficient or damaged native text are flagged for visual review/OCR; those documents remain `DOWNLOADED`, with `ocr_required=true`. Only complete native extraction without flagged pages advances to `EXTRACTED`. OCR/HTML extraction/asset exports remain planned. Generated outputs/logs are ignored by Git; code and configuration are tracked.
