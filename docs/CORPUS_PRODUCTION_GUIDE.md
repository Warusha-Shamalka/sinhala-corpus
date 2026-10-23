# Production corpus workflow

Updated 23 October 2026. See [the reliability change report](OCR_PIPELINE_FIXES.md)
for recent fixes and their verification limits. The implemented path is:

Discovery → bounded PDF/HTML download → verified native extraction/Surya OCR →
conservative cleaning and warnings → source review and corrections → deduplication
and split checks → derived training JSONL.

Surya **0.17.1** is the current OCR adapter. It is replaceable through configuration;
the pipeline and review/export contract do not depend on a Surya-specific output.
This workflow produces **text for pretraining**, not automatically generated MCQs
or instruction pairs. Model training remains in the separate training repository.

## Accuracy contract

OCR finishing, engine confidence, Sinhala character ratio and clean-looking text
do not establish transcription accuracy. The existing Surya trial had incomplete
regions and invented repeated text. All processed pages start with
`review_required=true`, `training_approved=false`.

The release path requires two different named people to compare the entire source,
correct the text and verify equations and reading order. Their declarations are
recorded; software cannot prove that a person actually performed the comparison.
Unreadable or incomplete source material should be rejected, not guessed. Failed
or truncated OCR can be recovered through a full human transcription of the source;
its original failure remains recorded in the exported provenance.

Only explicitly approved `train` pages become training-approved. Validation/test
pages stay held out. Hidden SinhalaMMLU test questions must never enter the corpus.
Code cannot identify a leaked benchmark question by itself.

Numerical OCR accuracy still needs independent human references in the separate
[OCR benchmark workflow](OCR_ACCURACY_GUIDE.md). A reviewed correction draft is
not an independent blind reference, and these releases claim no measured OCR CER/WER.

## Start in Colab

Use [notebooks/corpus_pipeline_colab.ipynb](../notebooks/corpus_pipeline_colab.ipynb)
after publishing the latest `fix/ocr-pipeline-reliability` branch changes. Upload
that notebook to Colab and select a **T4 GPU** runtime. It imports staged IDs
`LK-EDU-001501`–`LK-EDU-001505`, then defaults to every available registered
document/image in that store with `PAGE_NUMBERS=None`, `PROCESS_ALL_AVAILABLE=True`
and `RUN_UNTIL_DONE=True`. See [complete-store processing](PROCESS_ALL_AVAILABLE.md).
The historical `corpus_pipeline_colab_updatedVM.ipynb` variant is not maintained.

Automatic [resource discovery and proposed paper/scheme pairing](PAPER_DISCOVERY_AND_PAIRING.md)
are included in the notebook. `IMPORT_VM_PDFS=False` skips VM staging by default;
`DISCOVER_RESOURCES=True` searches configured category entry points. Collection
downloads a bounded batch of textbooks, papers and marking schemes, while the
processing stage can visit all verified available pages. Website access blocks
and incomplete pairing metadata remain visible in the reports.

The current [Sinhala/MCQ collection policy](SINHALA_MCQ_COLLECTION.md) expands the
study categories to notes, syllabuses and guides, filters the user's three source
websites, and selects one MCQ pair per exam identity before acquisition/OCR.

Run cells in order:

1. Mount Drive and clone the branch into temporary `/content/sinhala-corpus`.
2. Create isolated Python 3.12.12; install pinned Surya/PyTorch dependencies and Poppler.
3. Initialize a fresh persistent store at
   `/content/drive/MyDrive/sinhala-corpus/production_02` if it does not already exist.
4. Download/verify both Surya checkpoint components, freeze their hashes and save
   the dependency lock and repository commit to Drive.
5. Preview and execute the selected public-resource download.
6. Process all available pages/images and check the saved report for incomplete OCR or document errors.
7. Prepare a new source-review packet, without approving or exporting anything.

Model caches live in `/content` and may need downloading again after reconnection.
All corpus files, page bundles, review drafts and operational logs live in Drive.
No Hugging Face token is needed for this Surya setup. Model downloading happens
before OCR; the OCR worker blocks Python socket access during loading/inference.
Acquisition runs in a separate process where controlled web access is permitted.
This is a network guard, not a complete sandbox for arbitrary model code.

The new deployment store is separate from the earlier OCR evaluation folders.
Initialization preserves the seed catalog verbatim, then sets its working records
to `DISCOVERED` with blank local artifact fields because laptop files have not been
copied into this new store. It never edits the repository catalog or copies old raw
files. Existing stores are refused by `init`; the notebook reuses an existing store.
Do not run initialization over the master store to resume work.

Use **one writer/runtime per persistent store**. Local POSIX locks and directory
renames are not distributed locks across Colab/Drive clients. Drive deployment
and remote flush/recovery must be checked with the initial small run before scaling.

## Local commands and paths

CPU setup uses `requirements.txt`; PDFs also need Poppler. Only the OCR worker
requires Surya and CUDA. Static HTML can be processed without a GPU/model snapshot.

Create a new local persistent store:

```bash
python3 -B -m pipeline.workflow init --store /tmp/sinhala-corpus-production
```

For permanent work choose persistent storage instead of `/tmp`. The example below
uses a shell variable containing a real path—do not type angle-bracket placeholders.

```bash
PIPELINE_CONFIG=/tmp/sinhala-corpus-production/configs/pipeline.yaml

# Bounded discovery into this deployment's catalog, not the repository catalog.
python3 -B -m pipeline.discovery.crawler \
  --sources /tmp/sinhala-corpus-production/configs/sources.yaml \
  --subjects /tmp/sinhala-corpus-production/configs/subjects.yaml \
  --catalog /tmp/sinhala-corpus-production/corpus/catalog/documents.csv \
  --log-root /tmp/sinhala-corpus-production/corpus/logs/discovery \
  --source alapiedu --max-pages 25 --max-depth 2 --dry-run

# Remove --dry-run to append discovered candidates after inspecting that preview.
python3 -B -m pipeline.workflow collect --config "$PIPELINE_CONFIG" \
  --doc-id LK-EDU-000264 --dry-run
python3 -B -m pipeline.workflow collect --config "$PIPELINE_CONFIG" \
  --doc-id LK-EDU-000264 --progress plain
```

Configure model settings below before running PDF OCR. Then:

```bash
python3 -B -m pipeline.workflow process --config "$PIPELINE_CONFIG" \
  --doc-id LK-EDU-000264 --page-number 12 --page-number 13 --progress plain
python3 -B -m pipeline.workflow status --config "$PIPELINE_CONFIG"

python3 -B -m pipeline.workflow prepare-review --config "$PIPELINE_CONFIG" \
  --output /tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001
```

`collect` uses existing catalog candidates. Discovery is an explicit earlier stage;
it is not rerun secretly by downloading. Discovery dry-run still performs a bounded
crawl and writes discovery logs; download/process dry-runs perform no network calls,
PDF commands, GPU loading or artifact writes. Process dry-run lists eligible documents;
uncached page counts are resolved during actual processing.

Persistent storage structure:

```text
production_v1/
  configs/{pipeline,sources,subjects}.yaml
  initialization.json
  model_manifests/                         # checkpoint hashes, environment/commit
  corpus/catalog/{documents,seed}.csv
  corpus/raw/{pdf,html}/<doc_id>/<sha256>.* # originals + receipts
  corpus/extracted/pages/...               # immutable native PDF bundles
  corpus/extracted/processed/<doc_id>/<raw_sha256>/<identity_hash>/page_000012/
    page.json                             # native/OCR text, raw output, warnings
    page.png                              # rendered source (PDF)
    text.txt
    manifest.json
  corpus/clean/reviews/<batch>/            # correction drafts and review evidence
  corpus/logs/{discovery,download,extraction,processing}/
  datasets/pretraining/<release>/          # train/validation/test JSONL + manifest
```

HTML bundles have `source.html` instead of `page.png`. Neither raw sources nor
completed bundles are overwritten. Existing artifacts are checksum-verified on
restart. Changing model revision, source extraction identity, processing code,
rendering or configuration creates another version. Batch-size changes do not
invalidate existing pages.

The download catalog tracks source acquisition. Partial page processing or a
partial training release does **not** move an entire document to `READY`. Page
artifacts and review decisions provide the processing/approval record. `status`
verifies stored page artifacts and reports versions, methods, flags and corruption;
it does not claim that those pages are approved. Keep the full master store and
complete review packets alongside releases for reproducibility.

## Limits and routing

| Control | Repository default | Behavior |
| --- | ---: | --- |
| Download documents | 5/run | Existing bounded downloader and source/robots/host checks |
| PDF raw download | 50 MiB | Reject oversized/incomplete files |
| HTML download/extraction | 2 MiB | Explicit HTML MIME and document signature; strict decoding |
| Download time | 300 seconds/source fetcher | Includes requests/retries; see download guide |
| Native extraction | 500 pages, 50 MiB PDF, 100 MiB combined output | Reject over-limit PDFs; whole native bundle must complete |
| New processed documents | 5/run | Applies to newly written page bundles; existing versions can be verified without consuming this cap |
| New processed pages | 10/run | Stop with a batch-limit reason; rerun to continue uncached pages |
| Rendering | 300 DPI, side ≤3000 pixels | 60 seconds/command; 50 MiB output limit |
| Surya OCR | 120-second soft page deadline | Checked between model steps; excludes loading, renderer and detection/in-flight steps |
| Surya region decoding | 256 tokens/region | Missing regional termination marks output incomplete; increasing budget is not an accuracy fix |

Whole-document native preparation and verification happen outside the new-page
cap. There is no hard wall-clock watchdog for the entire GPU batch. Failed pages
remain immutable evidence; ordinary resume verifies them rather than retrying them.
For an intentional retry, set a new `processing.output_root` or change a descriptive
`processing.run_variant` value. That creates a new version while retaining the
failed one. Review the desired version explicitly.

`ocr_mode: all` is the current default while native font mappings are unreliable.
`auto` keeps a native page only when its existing routing flags and conservative
text checks pass; this still requires source review. Low Sinhala fraction,
replacement/control characters, short text, unexpected script and repetition are
warning signals. They cannot detect every hallucination or omission.

Static HTML selects one `main` region, otherwise one `article`. For another layout,
configure `processing.html_main_ids` keyed by the configured source **name**:

```yaml
html_main_ids:
  AlApiEdu: lesson-content
```

Ambiguous/no main regions, decoding problems and JavaScript-only pages fail visibly.
Scripts, navigation, forms, headers/footers and hidden content are excluded. Text
order is a DOM estimate; CSS layout is not interpreted. Tables, MathML, superscripts,
subscripts and image references require source review. Linked images, video/audio,
dynamic browser content and standalone JPEG/PNG acquisition are not implemented.
Retained HTML is untrusted source material; inspect it as text or on the original
site rather than executing its downloaded scripts.

## Change OCR model later

In the persistent configuration, update:

```yaml
processing:
  ocr_mode: all
  ocr:
    backend: surya
    model_path: /content/surya-models
    revision: ''  # Fill with the real 64-character selection.json SHA256.
    max_page_seconds: 120
    max_new_tokens: 8192
```

Use the existing [Surya setup](SURYA_OCR_TRIAL.md) to obtain the selection manifest
and actual revision; the production notebook fills it automatically. Empty revision
is a setup state, not a usable OCR snapshot.

The factory also exposes the existing experimental `gemma`, `qwen` and `deepseek`
adapters. These require their own compatible dependencies/hardware and selected
Hugging Face model snapshot path/revision; changing the name alone does not install
or validate a model. Their local files are hashed. Past Qwen/Gemma trial failures
remain relevant; no alternative is declared accurate by this registry.

A future backend implements `recognize(image_path)` returning `text`, `outcome`,
`completion_status` and optional raw geometry/confidences, plus a reproducible
`identity`. Register its creation/selection validation in `pipeline/ocr/backends.py`.
Preserve raw outputs, immutable weights/code/config identities and truthful
completion checks. The cleaning, human review and export stages remain reusable.

## Review, correct and release

Open the packet's `index.html` locally for PDF image/initial text side by side.
Its links point to the editable `texts/*.txt` drafts. It is a static initial view;
it does not show subsequent text edits. One person corrects from the source, another
verifies the whole page. Preserve spelling, negation, numbers, units, answer options,
equations, table relationships and reading order. Neither reviewer should guess
illegible content. Reject such pages using `review.csv` (`decision=reject`, notes).

After actual review, approve one page through the explicit CLI. Copy its real ID
from `review.csv`; the following Python invocation prompts for human details rather
than containing placeholder strings that could be mistaken for real approvals:

```python
from pathlib import Path
from pipeline.dataset.reviewed import seal
packet = Path('/tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001')
seal(packet, input('Record ID: '), input('Transcriber: '), input('Verifier: '),
     input('Source-use rights evidence: '), input('Full source/equation/layout check notes: '),
     input('Split (train/validation/test): '))
```

The shell equivalent is `python3 -B -m pipeline.dataset.reviewed approve`; run
`approve --help` to see its required fields and explicit check declaration.
Record real source-use evidence, not just a statement that a URL is public.
Review drafts are editable; the source record/images are immutable. Approval seals
the corrected-text hash. Later edits invalidate export until the page is rechecked
and approved again. Reviewer names are declarations, not authenticated identities.

```bash
python3 -B -m pipeline.dataset.reviewed status \
  --packet /tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001
python3 -B -m pipeline.workflow export \
  --packet /tmp/sinhala-corpus-production/corpus/clean/reviews/batch_001 \
  --output /tmp/sinhala-corpus-production/datasets/pretraining/release_001
python3 -B -m pipeline.workflow verify-release \
  --root /tmp/sinhala-corpus-production/datasets/pretraining/release_001
```

Export refuses zero approvals, missing evidence, invalidated hashes, source-document
versions crossing splits and exact/near-duplicate leakage. Same raw hash, document
ID or source URL stays within one split. Exact grouping folds whitespace after NFC;
near grouping uses word 5-gram Jaccard ≥0.9 for texts ≥30 words. Similarity groups are
transitive. Within-split duplicates are retained as audit decisions with one exported
representative. This does not detect all paraphrases, translations or short duplicates.

Releases include split JSONL, source/processing/model identities, original warnings,
correction provenance, frozen approved review evidence and artifact hashes. Only
`train.jsonl` should be passed to the training loader. Rejected/pending content is
excluded from release review evidence. Retain the complete source store separately.
For a cumulative corpus, prepare/export one cumulative reviewed release; do not
blindly concatenate successive releases containing the same pages.

If changing backends produced multiple versions of a page, `prepare-review` refuses
to choose silently. Pass `--config-hash` with the exact hash reported by the desired
processing run, or prepare from its exact bundle directory. The notebook does this.

## Validation and remaining evidence

Acquisition can continue while manual corrections are deferred. The optional
`pipeline.workflow run` command performs bounded download/process cycles and
`pipeline.workflow provisional` saves explicitly unreviewed text snapshots. These
commands do not approve pages or export a verified training release. See
[BATCH_COLLECTION_GUIDE.md](BATCH_COLLECTION_GUIDE.md) for limits, storage and resume.

Before export, use the new `pipeline.workflow quality --packet` command to inspect
review coverage, OCR failures, edited approvals and split/duplicate blockers. It
loads no model and changes no review decisions. Optional saved JSON/Markdown reports
are immutable snapshots outside the packet. See [CORPUS_QUALITY_GUIDE.md](CORPUS_QUALITY_GUIDE.md)
for commands, computation limits and correction-burden interpretation. Correction
distances are not independently measured OCR accuracy.

Run `python3 -B scripts/check_offline.py`. Tests cover both PDF and HTML paths,
raw/extracted/processed corruption, resumable batches, selected pages, changed model
versions, review corrections/approval invalidation, source-version split checks,
duplicates, script/repetition warnings and immutable deployment initialization.
The Colab notebook and embedded setup code are syntax-checked locally.

Local verification on 12 October 2026: `scripts/check_offline.py` ran 214 tests,
with 213 passing and one skipped because Tesseract was unavailable. The new PDF
integration exercised real Poppler extraction/rendering and a fixture OCR backend;
these checks do not measure Surya transcription accuracy or execute its GPU model.

Production Surya GPU execution in this new runner is still pending the two-page
Colab trial. The previous Surya comparison demonstrates that the adapter executes
on T4; it does not validate this full production deployment or its accuracy.
Real corpus approvals and a training-ready release also remain pending human work.

After merging the tested branch, set the notebook's `BRANCH` to `dev` (or use the
saved tested repository commit) before deleting the feature branch.
