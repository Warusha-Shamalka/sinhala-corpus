# Native text while OCR is being evaluated

We can collect and prepare usable native PDF text without waiting for an OCR
winner. HTML extraction is still planned. This route produces page-level text
for continued pretraining; it does not invent QA pairs or answers, and it does
not approve neural OCR predictions.

## Implemented flow

Verified raw PDF → existing native extraction → conservative cleaning → review
packet → explicit page approval → dataset JSONL.

`pipeline.cleaning.native` normalizes Unicode to NFC and line endings and trims
outer whitespace. It preserves joiners, punctuation, equations, units and internal
spacing. It does not correct spelling, decode legacy Sinhala fonts, remove headers
or repair reading order. Raw files, extraction bundles and catalogs are unchanged.

`pipeline.dataset.native` verifies extraction bundle hashes and page identities.
Each candidate retains source URL, raw PDF SHA256, page number, extraction config
and manifest hashes, original/cleaned text hashes and cleaning version. Catalog
subject/grade/language/license values remain **metadata hints**, not verified facts.

Default filters reject OCR-flagged/error pages, text shorter than 80 non-whitespace
characters, replacement characters, unexpected control characters, and pages with
less than 80% Sinhala letters among Unicode letters. This is deliberately strict:
mixed English/Sinhala and formula-heavy pages may be rejected. It is a routing
heuristic, not an accuracy score. A high Sinhala fraction cannot detect wrong
Unicode mappings, omitted text or incorrect equations.

## First local pilot, 11 October 2026

Four already-downloaded public PDFs were extracted offline, without catalog
updates:

| Document | Pages | Extractor OCR flags |
| --- | ---: | ---: |
| Biology teacher guide, LK-EDU-000264 | 76 | 2 |
| Sinhala worksheet, LK-EDU-000490 | 1 | 0 |
| History handout, LK-EDU-000491 | 8 | 0 |
| Business/Accounting handout, LK-EDU-000492 | 10 | 0 |

Of **95 pages**, the final default filter leaves **2 review candidates** and
quarantines **93 pages**. Rejection reason counts overlap: 93 little-Sinhala/legacy
font, 2 extraction flags, 2 short pages and 1 unexpected control character.
The candidates are the Sinhala worksheet and the History title page.
The worksheet has visible character-mapping errors (for example native text
`පොඩම` where the source shows `පාඩම`); the title page provides little educational
content. **Neither page has been approved. No training dataset was exported.**

An earlier exploratory 20% Sinhala threshold produced 3 candidates, including
a History page with mostly legacy-encoded body text. It remains a separate local
packet at `corpus/clean/native_pilot_20261011`; use the stricter
`corpus/clean/native_pilot_20261011_v2` packet instead.

The original seven production PDFs yielded 132 native-extraction pages, with
zero unflagged pages containing Sinhala Unicode. Their scans still need OCR.
These findings mean that changing the extraction method alone will not give us
a large accurate dataset from the current pilot.

## Reproduce and prepare a packet

Requires the existing Python dependencies and Poppler tools; no GPU or network
is needed when the broad-pilot raw PDFs and receipts are already present.

```bash
# Read-only plan, then extract the four printed PDFs into the isolated experiment.
python3 -B scripts/extract_native_pilot.py
python3 -B scripts/extract_native_pilot.py --execute

# Preview counts without writing a packet.
python3 -B -m pipeline.dataset.native prepare \
  --extraction-root corpus/experiments/ocr_broad_20261011/extracted/pages \
  --catalog configs/ocr_broad_sources.csv \
  --output corpus/clean/native_review_next \
  --dry-run

# Repeat without --dry-run to create that new packet.
```

For production native extraction, supply `corpus/extracted/pages` and
`corpus/catalog/documents.csv` instead. Start with bounded extraction runs as
documented in [EXTRACTION_GUIDE.md](EXTRACTION_GUIDE.md). If a page has multiple
extraction versions, prepare from a root containing just the chosen version;
the dataset stage refuses to choose one silently.

Packet contents:

- `candidates.jsonl`: pending native text and provenance.
- `rejected.jsonl`: quarantined pages with explicit reasons.
- `review.csv`: editable decisions tied to record IDs/text hashes.
- `manifest.json`: settings, source extraction hashes, catalog snapshot hash and
  candidate/rejected file hashes.

## Review and export

Open each candidate's original PDF page beside its `text`. Check **all** text,
reading order, Sinhala spelling, negation, numbers, equations, tables and missing
material. Reject title-only or unsuitable pages. A native text layer can be wrong
even when the PDF looks correct. Do not approve because the tool finished.

Edit only these `review.csv` columns:

| Column | Entry |
| --- | --- |
| `decision` | `pending`, `reject` or `approve` |
| `reviewer` | Person who actually checked the page |
| `review_notes` | What was checked; record defects when rejecting |
| `rights_evidence` | Evidence for using this source in the intended dataset |
| `split` | For approved pages: `train`, `validation` or `test` |

Keep record IDs/text hashes unchanged. Public availability is not itself a
recorded license. Leave approval pending when accuracy or source-use evidence
is unresolved. Corrections are not supported by this first exporter: fix an
extraction problem in a new versioned upstream artifact and prepare another
packet rather than editing hashed candidates.

```bash
python3 -B -m pipeline.dataset.native export \
  --packet corpus/clean/native_review_next \
  --output datasets/pretraining/native_release_001
```

Export requires approval, reviewer, comparison notes, rights evidence and an
explicit split. No approved pages means an error and no output directory.
Only `train.jsonl` is training-approved; validation/test remain held out. Pages
from the same raw PDF cannot cross splits. Identical cleaned text is deduplicated
within a split and rejected across splits. Near-duplicates, revised PDFs and
semantically equivalent text are **not** detected yet.

Release files include split JSONL, a hash manifest and frozen review evidence.
The schema has a `text` field for the training repository plus provenance fields;
it is not an instruction/MCQ dataset. Changing review decisions requires a new
release. Existing packets/releases are never overwritten. Publication uses a
temporary directory and per-output lock; a hard kill may leave a `.publish-lock`
directory. Remove it only after confirming its writer is stopped.

Generated data under `corpus/clean`, `corpus/experiments` and `datasets` is ignored
by Git. Copy complete artifacts and their manifests to persistent Drive storage;
do not rely on Colab `/content` for permanent storage. Run one writer per output
and verify hashes after copying. No automatic Drive upload is implemented.

## Next acquisition priority

1. Inspect new public sources for correct copyable Sinhala prose before bulk
   downloading; prefer clean Unicode/native text over scanned handwriting.
2. Implement HTML main-content extraction with provenance and navigation removal.
3. Diagnose legacy PDF font mappings using font information and source comparisons.
   Do not use a language model to guess replacement text.
4. Review usable text, record source-use evidence, deduplicate and build the first
   small pretraining release; keep model evaluation sources out of training.
5. Continue OCR benchmarking separately for scanned/handwritten material.

Hidden SinhalaMMLU test questions must never enter this acquisition/review/export
flow. This module cannot identify a hidden benchmark question by itself.

## Validation

Run `python3 -B scripts/check_offline.py`. New tests cover native pages from mixed
PDFs, dry-run safety, pending approvals, corruption detection, review completeness,
release evidence, exact duplicates, PDF split boundaries and conservative Sinhala
normalization. Fixture approvals are test data, not real corpus approvals.

Local verification: **192 tests run, 191 passed, 1 skipped** (Tesseract is absent
for the real OCR backend test). The native extraction/export tests passed. A real
export attempt on the unreviewed pilot correctly refused to write a release.
