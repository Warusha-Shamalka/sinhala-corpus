# Purpose

`native.py` prepares verified native PDF extraction pages for human review and
exports only explicitly approved text into derived JSONL releases. OCR predictions
remain separate. Other dataset formats are planned.
See [the native dataset guide](../../docs/NATIVE_TEXT_DATASET_GUIDE.md).

`reviewed.py` adds source-image/static-HTML review, human corrections, two-reviewer
approval and split-safe deduplicated export for production OCR/native pages.
See [the production guide](../../docs/CORPUS_PRODUCTION_GUIDE.md).

`provisional.py` snapshots unreviewed page text. `daily.py` filters provisional or
verified input releases into cumulative/delta text candidates, retaining review
status, deduplicating source families and writing a training handoff. See
[the daily release guide](../../docs/DAILY_TRAINING_RELEASE_GUIDE.md).

# Contents

- dataset creation scripts
- conversion logic to produce final benchmark or training-ready datasets
- metadata and split configuration

# Produced by

The dataset stage produces files under `datasets/`.

# Consumed by

Researchers, evaluators, or training pipelines consume the packaged datasets from the top-level `datasets/` area.

# Git policy

Implementation code belongs in Git. Generated dataset artifacts are usually local unless intentionally preserved in a curated shareable form.
