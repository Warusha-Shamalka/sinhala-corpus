# PDF extraction

Implemented: local Poppler PDF extraction with page/block/word provenance, OCR-needed routing, immutable bundles, verified restart recovery and catalog checkpoints. This stage reads verified downloaded PDFs; it makes no network requests and does not perform OCR or cleaning.

```bash
python3 -B -m pipeline.extraction.extractor --source alapiedu --max-documents 1 --dry-run
python3 -B -m pipeline.extraction.extractor --doc-id LK-EDU-000011 --max-documents 1 --progress plain
```

The second command writes outputs/logs and checkpoints the catalog. Install `poppler-utils` in addition to the Python requirements. See the [extraction guide](../../docs/EXTRACTION_GUIDE.md) for dependency setup, output paths, limits, schemas, statuses and recovery, and [pilot results](../../docs/EXTRACTION_VALIDATION_RESULTS.md) for the seven-document trial.

Outputs live under `corpus/extracted/pages/<doc_id>/<raw_sha256>/<config_hash>/` as `pages.jsonl`, `text.txt` and `manifest.json`. Raw data stays unchanged. Flagged documents remain `DOWNLOADED`; complete unflagged native extraction advances to `EXTRACTED`. The separate production processor provides Surya OCR and static HTML extraction via `html.py`; full PDF figure/table asset extraction remains planned. See [the production guide](../../docs/CORPUS_PRODUCTION_GUIDE.md). Generated artifacts are ignored by Git.
