# Paper identity enrichment

`paper_identity.py` enriches an editable paper/key index using existing index hints,
titles, URL filenames and optional verified first-page processing bundles. It does
not download documents, invoke OCR, update the master catalog or approve pairs.

```bash
python3 -B -m pipeline.workflow enrich-pair-index \
  --index /tmp/paper-index/documents.csv --output /tmp/paper-metadata
python3 -B -m pipeline.workflow suggest-paper-pairs \
  --index /tmp/paper-metadata/documents.csv --output /tmp/paper-matches
```

Choose fresh output folders. To include first-page evidence, repeat
`--page-bundle /path/to/processed/page_bundle` on enrichment. Use the existing page
processor to extract native PDF text or run the configured OCR backend (Surya by
current project choice); the bundle must contain manifest.json, page.json and its
hashed text/image artifacts. No separate model is introduced here.

Outputs:

- `documents.csv`: enriched, editable index; metadata always starts unverified.
- `input_documents.csv`: unchanged input snapshot.
- `metadata_evidence.jsonl`: per-field values, missing/conflict status, source text,
  origin and header page/line/raw/text hashes where available.
- `header_receipts.jsonl`: processing manifest hashes, identities, methods and warnings.
- `manifest.json`: input/config/code hashes, settings and output hashes.

First-page bundles must match the document ID, raw hash (if already known) and URL.
Corrupt, repeated, wrong-page and incomplete OCR inputs are rejected. Default header
window is 40 lines; `--header-lines` accepts 1–100. These are bounded header hints,
not a general document-understanding system. OCR completion does not establish accuracy.

The extractor uses configured subject aliases and medium phrases, recognizes basic
AL/OL labels and paper/part I–III or numeric labels, and keeps conflicting values
blank. URL query strings and upload directories are ignored. Lines mentioning
publication/upload/copyright/printing do not supply year hints. Multiple years
remain unresolved, and collection IDs prevent assignment of a single exam year.
Existing index hints participate in conflicts; this stage cannot retroactively prove
that an earlier index value was extracted correctly.

Variant detection only recognizes explicit model, term, resit and official wording.
“Official” is a source claim, not an authenticity check. School, province, session,
old/new syllabus and edition details still require source review. Never fill a missing
variant with “main” merely to produce a match. Ambiguous subject wording within one
line may produce no hint. Paper I/II combined documents may require separate region
configurations after review.

Use evidence to resolve conflicts in the editable index, record a reviewer after
checking the originals, then rerun suggestions. Suggestions still do not approve
answers. See [the matching guide](../../docs/MCQ_ANSWER_MATCHING_GUIDE.md).
