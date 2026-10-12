# Purpose

`discovery_review.py` implements independent discovery-candidate sampling/reporting;
`ocr_benchmark.py` measures OCR against verified independent references. `text.py`
provides warning heuristics, and `corpus.py` reports production review coverage,
correction burden and export preflight without auto-approval. See
[CORPUS_QUALITY_GUIDE.md](../../docs/CORPUS_QUALITY_GUIDE.md) for production commands
and the distinction between correction burden and independent OCR accuracy.

This directory is reserved for quality-assessment workflows.

# Contents

- validation scripts
- content-quality checks
- scoring and issue classification logic

# Produced by

The quality stage should produce quality flags, rejection records, and final validated data.

# Consumed by

Dataset-generation and reporting workflows use the quality checks and scores.

# Git policy

Code belongs in source control. Quality outputs are generated artifacts and should generally remain local unless intentionally archived.
