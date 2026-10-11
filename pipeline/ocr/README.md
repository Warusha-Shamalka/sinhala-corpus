# Selective OCR

Implemented: local Tesseract Sinhala/English OCR for native-extraction flagged pages, with saved page PNG, raw TSV, text, word boxes/confidence, provenance, immutable restart recovery and progress. Every result remains pending quality review. This baseline does not solve handwriting/equations or advance catalog states.

```bash
python3 -B -m pipeline.ocr.ocr --doc-id LK-EDU-000011 --page 1 --max-pages 1 --dry-run
python3 -B -m pipeline.ocr.ocr --doc-id LK-EDU-000011 --page 1 --max-pages 1 --progress plain
```

Install Tesseract, Sinhala/English language data and Poppler first. See the [OCR guide](../../docs/OCR_GUIDE.md) for setup on Arch/Ubuntu/Colab, limits, paths, page selection and review. The [pilot results](../../docs/OCR_VALIDATION_RESULTS.md) describe the poor recognition on two handwritten pages. Code/config/docs are tracked; generated OCR outputs are ignored by Git.

## Optional neural OCR experiment

`python3 -B -m pipeline.ocr.neural --help` exposes the local-snapshot image transcription runner. Gemma/DeepSeek dependencies are optional and installed in an isolated Colab environment, not in core requirements. See [Colab setup](../../docs/COLAB_OCR_GUIDE.md) and [reference/accuracy workflow](../../docs/OCR_ACCURACY_GUIDE.md). GPU adapter execution has not been validated here; outputs remain pending human review. DeepSeek completion verification is not implemented and its outputs are excluded from scored comparisons.
