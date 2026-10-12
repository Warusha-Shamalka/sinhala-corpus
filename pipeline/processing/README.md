# Page processing

`pages.py` verifies local raw receipts, prepares complete native PDF bundles and
routes selected pages through native extraction or a configurable OCR backend.
Surya is the current default. Static HTML uses strict main-content extraction.

Per-page artifacts retain source content, raw predictions, configuration/model
identity and quality warnings. Restart verifies existing artifacts and continues
uncached pages within batch limits. It never approves training text.

Use `python3 -B -m pipeline.workflow process --help` and follow
[CORPUS_PRODUCTION_GUIDE.md](../../docs/CORPUS_PRODUCTION_GUIDE.md) for deployment,
corrections, approvals, dataset exports and supported formats.
