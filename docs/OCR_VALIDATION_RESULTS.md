# Selective OCR validation — 11 October 2026

Work remains on `feat/pdf-extraction`, as requested. This is a corpus engineering trial, not a SinhalaMMLU benchmark evaluation.

## Runtime and models

The local machine did not have Tesseract installed. Official Arch packages were downloaded and unpacked under `/tmp/sinhala-ocr-tools` for testing; no system installation or production catalog change was made. These temporary tools are not tracked or a permanent deployment. Use the installation commands in [OCR_GUIDE.md](OCR_GUIDE.md) for regular execution.

- Engine: Tesseract 5.5.3; Leptonica 1.87.0.
- Renderer: Poppler pdftoppm 26.08.0.
- Sinhala traineddata SHA256: `c4241607afe257b9cfdafa5a171287b7d0441ff541e3b214c0fa03558916ed24`.
- English traineddata SHA256: `daa0c97d651c19fba3b25e81317cd697e9908c8208090c94c3905381c23fc047`.
- Settings: `sin+eng`, OEM 1, PSM 3, 300 requested DPI and longest rendered side capped at 3000 pixels.

The exact model/version identity is also recorded in each page configuration. Models were read locally; no closed API was used.

## Real handwritten pilot

Document `LK-EDU-000011`, pages 1 and 2 only. The native extractor had flagged all six pages for OCR. The other four pages were outside this selection; the other downloaded PDFs were not OCR-processed.

| Page | OCR non-whitespace characters | Sinhala characters | Mean word confidence | Result |
| --- | ---: | ---: | ---: | --- |
| 1 | 289 | 100 | 48.05 | review_required; low_engine_confidence |
| 2 | 372 | 79 | 49.01 | review_required; low_engine_confidence |

The corrected two-page run took approximately 10 seconds. There were zero command/page failures, but the recognized Sinhala words and equations are poor. Page 1 was compared with the earlier rendered source preview: the title, explanatory handwriting and formulas were garbled or omitted. Both pages stay pending review; neither is approved as clean text. No character/word error rate is claimed because no independently reviewed reference transcript exists. Confidence values above are engine scores, not accuracy percentages.

The first run exposed a TSV quote-parsing bug: a literal quotation mark made the CSV reader merge following rows into word text. `ocr-0.2` treats quotes literally, adds a regression test and produces a distinct output version. The corrected outputs contain no embedded TSV row fragments. The initial unreviewed trial remains separate and must not be used as a dataset.

Current report: `corpus/logs/ocr/pilot_20261011.json`. Initial parser trial: `corpus/logs/ocr/pilot_20261011_initial_parser_trial.json`. These files, snapshots and outputs are generated local artifacts ignored by Git.

Corrected output bundles:

```text
corpus/extracted/ocr/LK-EDU-000011/
  9861a1d1382a9fe334483f12c41fbcffaf76c8c4649e8ef20a6d0b41f9630a3e/
    <ocr_config_hash>/page_000001/
    <ocr_config_hash>/page_000002/
```

Use the actual `bundle_path` from the corrected report to identify the version. Open `page.png` beside `text.txt`; inspect `page.json` and `raw.tsv` for provenance/confidence/word boxes. The original PDFs, download receipts and native bundles were preserved. Production catalog bytes matched before and after the pilot. No document advanced to `EXTRACTED` or `READY` through OCR.

## Checks

`python3 -B scripts/check_offline.py` with the temporary engine/data on PATH: **153 tests passed**, including real rendering/recognition of a synthetic printed PDF with Sinhala/English models loaded. The fixtures also cover selective mixed native/scanned pages, page caps, literal quotation marks, low/empty OCR, provenance, review gates, cache identities, no-write dry-runs, output/raw corruption, ambiguity, interruption and progress.

Without installed OCR tools, the real OCR integration test is skipped with a dependency message; other fixtures still run. CI now installs Poppler plus Tesseract Sinhala/English language packages, so its real backend test runs. This confirms the backend works on printed text, not that it can accurately transcribe handwritten Sinhala.

Next gate: independently transcribe representative Sinhala handwriting/equation pages, measure recognition errors, then compare stronger OCR/vision backends. Do not bulk-process or build training datasets from this poor baseline output merely because commands complete successfully.

## Accuracy workflow checkpoint

Prepared `reviews/ocr/pilot_20261011`: ten rendered pages across seven raw PDFs, seven calibration pages and three document-separated holdout pages. All ten references remain empty/pending; source-image hashes validate. These generated PNGs occupy about 30 MB and are excluded from Git; tracked manifests/empty reference files preserve the packet definition. Production catalog is unchanged.

Added the independent review/checksum/CER/WER tool, optional snapshot-based neural runner and Colab notebook. Offline checks now pass **166 tests**, including 13 new accuracy/orchestration tests, the real Tesseract integration test, and notebook code-cell syntax checks. CI validates OCR review metadata without requiring the generated images or heavyweight GPU dependencies. Neural fixtures are software tests, not model accuracy evidence.

**At the initial workflow checkpoint, no Gemma or DeepSeek GPU execution had occurred.** Hardware/library compatibility remains to be validated in Colab. DeepSeek upstream completion evidence is not available through its text-returning API; these results are explicitly incomplete and excluded from scored comparisons. No CER/WER, model winner, human-reviewed text or training acceptance is claimed.

## Subsequent maintainer-supplied Colab evidence

Gemma now has actual T4 execution evidence supplied by the maintainer: the first page spent 604.84 seconds reaching the 8,192-token cap in a repetition loop; the second completed in 21.899 seconds with 284 tokens. See [Colab trial details](COLAB_OCR_GUIDE.md#observed-gemma-t4-trial-and-loop-protection). This establishes execution, not transcription accuracy or completion of the ten-page comparison.

Added phase progress, a generated-token repetition guard and a soft generation deadline. Their interrupted outputs remain truncated and excluded from scoring. The safeguard behavior and progress snapshots have local fixture coverage; GPU execution of the updated guard remains pending.
