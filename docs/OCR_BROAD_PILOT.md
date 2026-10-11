# Broader subject and model OCR pilot

This is a small diagnostic experiment for extracting training material accurately. It does not train a model or approve generated text. The original maths pilot remains available. Human references can be prepared while models run; numerical accuracy comparison must wait for independently verified references.

## Prepared sample

`reviews/ocr/broad_20261011` contains **14 rendered page images from eight public PDFs**, a frozen manifest, empty reference files, pending review rows and download receipts. The generated images exist locally but are ignored by Git. Subject/style hints below come from engineering inspection of the page images on 11 October 2026; the transcriber/verifier still needs to confirm the content style.

| Subject group | Printed pages | Handwritten pages | Source PDF IDs/pages |
| --- | ---: | ---: | --- |
| Sinhala Language | 1 | 0 | 000490: 1 |
| History | 2 | 0 | 000491: 2, 3 |
| Business and Accounting | 2 | 0 | 000492: 2, 10 |
| Biology | 2 | 2 | 000264: 12, 13; 000231: 1, 2 |
| Physics | 0 | 2 | 000104: 1, 2 |
| Maths | 2 | 1 | 000285: 2, 3; 000012: 1 |

The sample covers prose, worksheets, equations, diagrams, colored backgrounds, columns and an accounting table. Printed maths pages are structured exam questions, not MCQs. PDF page numbers count from the first PDF page and can differ from numbers printed on the paper. Native-text PDFs are included: several visibly Sinhala documents expose legacy font encoding as Latin characters to native extractors.

Missing: handwritten Language/History/Business, printed Physics, Economics, MCQs and wider grades/sources. Two pages from one PDF are correlated observations. This packet cannot establish general curriculum accuracy or separate all subject effects from layout/style effects. Whole PDFs remain within one calibration/holdout split; the old vector-maths calibration page keeps its prior split. Do not tune prompts on holdout pages.

## Storage and provenance

Raw PDFs and receipts are in `corpus/experiments/ocr_broad_20261011/raw/pdf/<doc_id>/<sha256>.pdf` and `.json`. The experiment has a separate `documents.csv`; the production catalog has not changed. IDs 000490–000492 are scoped to this experiment catalog and must not be joined to future production rows by ID alone. Use the catalog namespace, URL and raw SHA256 together. `source_receipts.json` in the packet preserves all eight source hashes and download provenance. The copied old vector-maths receipt records its original location.

Raw downloads and experiment logs are ignored by Git. Keep the entire experiment folder on persistent storage for recovery. The source seed CSV and selection/configuration YAMLs are tracked. Public availability does not establish a training reuse license; confirm permissions before dataset exports. This packet is reserved for OCR evaluation, including its reference text, and must be excluded from training exports.

## Recreate the acquisition and page images

From the repository root, with core dependencies installed:

```sh
python3 -B scripts/prepare_ocr_broad_sources.py
python3 -B scripts/prepare_ocr_broad_sources.py --download
python3 -B -m pipeline.quality.ocr_benchmark prepare --config configs/ocr_broad_pipeline.yaml --selection configs/ocr_broad_pilot.yaml --output reviews/ocr/broad_recreated
```

The first command initializes an isolated catalog if missing and prints a download plan. It does not fetch resources. The second uses the existing downloader and its configured limits: eight documents, 50 MiB per file, 240 seconds, 45 requests, one-second delay, 20-second request timeout and at most two retries. These are batch caps; if exhausted, rerun after inspecting the report to resume remaining jobs. Approved-source/domain/robots restrictions still apply. Existing artifacts are validated and retained. Identity disagreement with the frozen seed is rejected. No production catalog writes occur.

`pdftoppm` from Poppler is required for rendering. Explicit selection includes downloaded native-text PDFs and does not require extraction bundles or an OCR-required flag. Duplicate raw pages and PDFs crossing splits are rejected. Preparation refuses to overwrite an existing packet. Recreated images or metadata may differ with source/renderer changes: compare raw/image hashes and use one frozen packet for both models, rather than mixing runs from different packets.

## Colab comparison

1. Commit/push the reviewed code changes so Colab can clone them. Upload the updated `notebooks/ocr_accuracy_colab.ipynb` and the **complete** `reviews/ocr/broad_20261011` folder, including ignored images, to Drive at `My Drive/sinhala-corpus/reviews/ocr/broad_20261011`.
2. Choose a **T4 GPU** runtime. The notebook defaults to `BACKEND = 'qwen'`, `PACKET_NAME = 'broad_20261011'`, `MAX_PAGES = 1`. Run cells in order and inspect the first page JSON beside its source PNG. This tests compatibility and obvious transcription failures; it does not measure accuracy.
3. If the trial loads successfully, create a new `RUN` folder by rerunning the model-selection/download cell, then set `MAX_PAGES = 14` and run transcription. Never reuse an existing predictions folder. Keep the model revision, weight hashes, dependency lock and repository commit with outputs.
4. Use a fresh GPU runtime, change `BACKEND = 'gemma'`, and repeat on the **same packet**. The prior maths-only Gemma run cannot substitute for this paired broader run. Run one model at a time.
5. Prepare independent references following `docs/OCR_ACCURACY_GUIDE.md`. Evaluate both prediction directories together after verification. Reports show all-page outcomes even before references exist; CER/WER stay null for unverified pages. After verification, subject/style breakdowns include only scored pages; inspect missing/truncated counts and split coverage before drawing conclusions.

Qwen2.5-VL-3B-Instruct is an additional candidate based on its documented image/document capabilities, not demonstrated Sinhala accuracy. Its adapter uses local weights, float16/eager attention and bounded image pixels; actual T4 compatibility and accuracy are **pending**. Both Gemma and Qwen preserve stopped outputs and use repetition/soft time guards. DeepSeek remains optional on BF16-capable hardware; its current completion-unverified outputs cannot complete an accuracy comparison.

Model source: [official Qwen2.5-VL-3B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct). Public resource URLs are recorded per sample in the manifest and per download in receipts.
