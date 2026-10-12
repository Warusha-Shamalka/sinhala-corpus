# Selective OCR guide

Implemented on the existing extraction branch: a local Tesseract Sinhala/English baseline for flagged pages, separate immutable page outputs, raw TSV/word boxes/confidence, saved page images, restart recovery, limits and shared progress. This stage **does not approve OCR text or advance catalog states**. Every page remains pending review. Handwriting/equation quality is not solved by this first backend.

## Dependencies

The stage uses existing Python requirements and system `pdftoppm`, `tesseract`, `sin.traineddata` and `eng.traineddata`.

Arch Linux:

```bash
sudo pacman -S --needed poppler tesseract tesseract-data-sin tesseract-data-eng
```

Debian/Ubuntu/Colab:

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-sin tesseract-ocr-eng
```

Check installation:

```bash
tesseract --version
tesseract --list-langs
pdftoppm -v
```

The language list must include `sin` and `eng`. The project uses the LSTM engine (`--oem 1`). Sinhala data and engine compatibility are described in the [official language-model documentation](https://tesseract-ocr.github.io/tessdoc/Data-Files.html). Tesseract's [manual](https://tesseract-ocr.github.io/tessdoc/) describes a printed-text OCR engine; these handwritten pilot notes require independent validation.

Set `ocr.tesseract_command` or `ocr.tessdata_dir` in a local pipeline config if the executable/model files are elsewhere. Language data is loaded locally; the stage never fetches models or calls an API. Exact engine/renderer versions and traineddata SHA256 values are recorded in the output configuration. Preserve those dependencies to reproduce a run; changing model files changes the output fingerprint. No system package version is silently presented as pinned by requirements.txt.

## Preview and run a small sample

Native extraction must already have produced a verified bundle for the document. You do not need to copy the pilot catalog back into production: eligibility comes from the raw catalog identity and verified native bundle, rather than requiring production `ocr_required` to have been checkpointed yet.

```bash
python3 -B -m pipeline.ocr.ocr --doc-id LK-EDU-000011 --page 1 --page 2 --max-pages 2 --dry-run
python3 -B -m pipeline.ocr.ocr --doc-id LK-EDU-000011 --page 1 --page 2 --max-pages 2 --progress plain
```

The preview reads/verifies extraction files, but does not load an OCR backend, create locks/outputs/logs or change the catalog. A real run verifies the raw receipt/hash/size, renders the selected PDF pages, runs OCR and saves results. PDF parsing/rendering and OCR make no network calls. Raw PDFs/receipts, native extraction bundles and catalog bytes are left unchanged.

Default: at most **three pages from one document**. Only native `ocr_required=true` pages are eligible. `--page` can be repeated to choose exact one-based PDF page numbers; duplicates, unflagged pages and out-of-range pages fail. `--max-pages` caps the selected pages in source order. Omitting `--page` starts at the first flagged pages, including previously processed pages; rerunning verifies/reuses them. To move on, select later pages explicitly or increase the cap. `unselected_flagged_pages` reports flagged pages outside this selection, not errors. Successfully processing a sample does not complete the full document.

If several native configuration versions exist, use `--bundle "actual/native/bundle/path"`. The runner deliberately refuses to pick an arbitrary version. The selected bundle must be under the configured extraction root for the same document/raw hash. Native manifest, output hashes and page identities are checked before using it.

`--config` selects a pipeline YAML. Relative storage/model-directory paths are resolved from the repository root. Final JSON uses stdout; progress uses stderr. `--progress auto|plain|off`, `--quiet`, and `python3 -B -m pipeline.progress "actual/progress/path.json"` work as in [PROGRESS_GUIDE.md](PROGRESS_GUIDE.md).

## Configured limits

| OCR setting | Default | Meaning |
| --- | --- | --- |
| `languages` | sin+eng | Sinhala plus English local language models |
| `dpi` | 300 | Requested rasterization resolution |
| `max_image_side` | 3000 pixels | Longest rendered side; large pages can be scaled below requested DPI |
| `psm` | 3 | Automatic page segmentation; supported alternatives are 6 and 11 |
| `max_pages` | 3 | Selected page count per command |
| `max_seconds` | 300 | Run budget after backend/raw setup, checked at each selected page |
| `command_timeout_seconds` | 60 | Combined render/recognition timeout allowance per page |
| `max_command_bytes` | 52,428,800 | Bounded child output files and maximum PNG/TSV payloads |
| `min_text_chars` | 20 | Below this non-whitespace count, flag low text |
| `min_mean_confidence` | 60 | Below this mean word confidence, flag low confidence |

Confidence is an engine score on a 0–100 scale, **not a measured accuracy percentage**. The threshold is a project routing default, not a validated Sinhala handwriting threshold. No text and null mean confidence are recorded honestly; they are not treated as accepted empty documents. All pages require review even if they exceed these thresholds. Rendering is the only image preparation implemented; no deskewing, enhancement or equation recognition is claimed.

## Outputs, provenance and recovery

```text
corpus/extracted/ocr/<doc_id>/<raw_sha256>/<ocr_config_hash>/page_<number>/
  page.png
  raw.tsv
  text.txt
  page.json
corpus/logs/ocr/
  ocr_<run_id>.jsonl
  ocr_<run_id>.progress.json
```

Storage roots are configured under `ocr` in `configs/pipeline.yaml`. Generated files/logs are ignored by Git. `page.json` uses `ocr-page-1` with one-based source PDF page numbers, original raw hash, native-bundle identity/hash, untouched native text/reasons, backend/model identity, raster dimensions, words and boxes, confidence, quality flags and pending review. Word boxes use **rendered image pixels**, not native PDF points. Text lines follow emitted TSV block/paragraph/line order; exact typography, equation meaning, table layout and academic correctness are not guaranteed.

`raw.tsv` preserves engine output for inspection, including word-level confidence. Its parser treats quote characters literally: TSV words containing quotation marks must never swallow following rows. The pilot found this issue; it is fixed and covered by a regression test in `ocr-0.2`.

The config fingerprint includes OCR/parser version, traineddata hashes, engine/renderer versions, rendering/segmentation settings, thresholds and the native manifest hash. Page PNG/TSV/text hashes are recorded in `page.json`. Each page bundle is committed by an atomic directory rename, verified on reuse and never overwritten when corrupt. Distinct backend/settings produce separate versions. Raw SHA256 is checked again before committing newly recognized pages.

One OCR-worker lock prevents overlapping workers for a catalog. Each page has a result in the durable event log. A failed page does not erase previous successful pages. Ctrl+C records interruption and cleans incomplete page writes; rerunning reuses finished pages. A hard kill can leave `.ocr-*` temporary directories, which are never accepted as completed outputs. Check that no worker is active before removing abandoned temporary directories. Snapshot staleness is not proof of a stopped process.

## Result and quality gate

The JSON lists `review_required` results and `failed` results, plus selected/unselected page counts. Exit 0 means selected pages were processed and saved, **not accepted for training**. Exit 1 signals selected-page failure; 2 signals input/setup errors; Ctrl+C exits 130. `catalog_updated=false` is intentional: the current CSV cannot express the OCR review state without losing native-stage meaning. OCR evidence lives in versioned page records/event logs until a reviewed quality-stage transition is implemented.

For review, open each saved `page.png` beside `text.txt`, check Sinhala words, reading order, equations, omissions and the scanner watermark. Transcribe representative lines/pages independently, keep them linked to document/page hashes, then measure recognition error against those references. Do not substitute confidence for that measurement. Keep native and OCR text separate and avoid using this unreviewed output as a clean dataset.

See [OCR_VALIDATION_RESULTS.md](OCR_VALIDATION_RESULTS.md). The actual handwritten sample is poorly recognized, so bulk OCR on all 132 pages is deferred. A stronger handwriting/vision backend, equation handling and a human reference/evaluation workflow remain next tasks. The adapter boundary is `identity` plus `recognize(pdf, page_number, timeout) -> (png_bytes, tsv_bytes)`; another backend should use a separate versioned output schema if it cannot provide TSV word boxes/confidence rather than inventing them.

## Tests

```bash
python3 -B scripts/check_offline.py
```

CI installs Tesseract/Sinhala/English models and runs a real printed-PDF render/OCR test. Offline fixtures cover selective routing, page caps, quotes, review gates, immutable provenance, cache identity changes, corruption, no-write dry-runs, failures, interruption and progress. Printed fixture success does not establish handwritten Sinhala accuracy.

## Accuracy-first next step

The local handwritten-page trial does not support using Tesseract output as training text. Use the [human reference and acceptance workflow](OCR_ACCURACY_GUIDE.md) and the [Colab notebook setup](COLAB_OCR_GUIDE.md) to investigate stronger open-weight transcribers. Neural adapters are experimental and have not been GPU-tested in this project. Model output is never treated as an authoritative reference.
