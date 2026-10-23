# OCR pipeline reliability changes — 23 October 2026

Branch: `fix/ocr-pipeline-reliability`.

For the Colab error `Catalog and raw artifact path disagree`, follow
[the recovery steps](COLAB_PATH_RECOVERY.md). For standalone image input, see
[the image OCR guide](IMAGE_OCR_GUIDE.md).

## Changes and reasons

| Problem | Implemented behavior |
| --- | --- |
| Download planning crashed on catalog pilots without a configured source. | Missing or unapproved sources produce an exclusion reason. |
| An approved direct CDN URL passed planning but failed the fetcher's original-domain check. | Resource fetching uses the explicit host allowlist consistently; unapproved hosts are rejected before a request. |
| A robots HTTP 403 could be treated as permission to crawl. | HTTP 401/403 deny access. HTTP 404/410 mean the robots file is absent. |
| GovDoc download links acquired invented History/grade-6/syllabus metadata. | Subject, grade and type come from title evidence. Unknown fields stay blank or `other`; medium hints do not become verified language labels. Download detection checks the exact host/path. |
| Abrupt termination left a directory lock that permanently blocked publication. | Publication uses a stable POSIX file lock released when the process exits. Hidden staging manifests are excluded from page/review discovery. Existing outputs still cannot be overwritten. |
| A failed OCR bundle became a successful cache hit on the next run. | Cached incomplete OCR reports `existing_incomplete` and a failing exit code. `process --retry-incomplete` creates a new immutable attempt and retains the old one. |
| Empty OCR text could be reported as a successful prediction. | It is recorded as `empty` and fails the processing run. |
| Retries produced multiple copies of the same source/config page in review preparation. | Review preparation selects the latest verified attempt for that exact identity. Different processing configurations still require an explicit selection. |
| Standalone PNG/JPEG files lacked a production acquisition path. | `workflow import-image` validates bytes/pixels/format, preserves original bytes and provenance, and registers a one-page document. Images use the same review/export path as PDF pages. |
| Preprocessing and column ordering were hard to compare reproducibly. | Explicit crop/rotation/grayscale/autocontrast options and optional Surya two-column ordering are recorded in processing identity. Defaults retain the original behavior. |
| Colab selected five IDs but configured a one-document limit. | The canonical notebook sets download and processing limits from `MAX_DOCUMENTS = len(DOC_IDS)`. |
| The VM importer kept an old path when an existing catalog row already had the same SHA256. | Matching rows update their local path. A separate verified repair step repairs relocated receipt paths too. |
| Colab displayed progress only after a command exited and could print a failed report twice. | A small dependency-free helper streams stderr immediately and prints stdout JSON once. |
| Copying source configuration could silently discard Drive edits. | Notebook copying is an explicit switch; destination source/subject files are backed up first. The Drive pipeline configuration is preserved and its deployment paths are repaired. |

The image dependency is optional for ordinary PDF/HTML processing:
`requirements-images.txt` pins Pillow for the supported Python 3.11–3.14 range.
The isolated Surya notebook retains its existing compatible Pillow/Surya pins;
do not combine the two environments by upgrading packages blindly. CI installs
the image dependency so image ingestion is exercised.

## Retry and publication contract

Each retry increments `attempt` and points to `previous_attempt_bundle`.
The initial directory stays `page_000001`; later attempts use siblings such as
`page_000001_attempt_000002`. All artifacts retain hashes. Corrupt historical
attempts remain errors, even when a newer attempt exists. Retry does not approve
a page for training or bypass human correction.

New processing code changes the configuration fingerprint, so old-version output
may be processed into a separate version. A review root containing different
processing configurations still needs `prepare-review --config-hash HASH`.

Stable `.NAME.publish.lock` files are normal and should remain in place. Their
existence does not mean a process owns the lock. Old `.NAME.publish-lock`
directories and hidden staging directories are preserved as recovery evidence;
the new publisher does not depend on them. POSIX locks are local process
coordination, not distributed locks across Drive clients. Continue using one
writer/runtime per store.

## Verification

Run from the repository root using its existing virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-images.txt
.venv/bin/python -B scripts/check_offline.py
.venv/bin/python -m pip check
git diff --check
```

Regression coverage includes the real stale-path exception, read-only repair
preview, backup/idempotence, refusal of corrupt raw data, execution of the VM
import cell with an existing stale catalog path, embedded notebook scripts and
five-document configuration, process death during publication, failed/empty OCR
and immutable retries, direct PNG/JPEG import, preprocessing and review packet
creation without PDF tools, CDN scoping and unknown sources.

The offline suite passed locally on Python 3.14.4: 277 tests ran, with one
Tesseract integration test skipped. `pip check` found no broken requirements.
Local tests use fake OCR predictions and synthetic source material. They verify
pipeline behavior; they do not establish Sinhala recognition accuracy. The
optional real Tesseract integration test is skipped when Tesseract is absent.
This environment has no Colab/Drive mount or usable GPU, so the corrected notebook
still needs a small real Colab run before scaling.

## OCR work that still requires data or runtime validation

The inspected reference packets contain **0/24 verified references**. The broad
packet has 14 matching images; the older ten-page pilot has seven missing images
and three image hash mismatches in this checkout. Those files and manifests have
not been silently regenerated or relabelled. Restore the exact original images
from trusted storage, or create a new reference packet with new provenance. Do
not change expected hashes merely to make verification pass.

Start with the intact broad packet, have two people independently transcribe and
verify references, and use the existing [accuracy workflow](OCR_ACCURACY_GUIDE.md)
to measure CER/WER. Keep document families in one calibration/holdout split.
Report printed, handwritten and equation-heavy pages separately. No accuracy
improvement or winning OCR model is claimed by this change.

Compare one preprocessing or rendering change at a time on calibration pages.
A 3000-pixel long-side cap can reduce effective A4 resolution below 300 DPI even
when `dpi: 300` is selected. Increasing it is an experiment with GPU memory and
latency costs. Two-column ordering is an explicit heuristic; it does not recover
table or diagram semantics. Equations still need source comparison.

Performance follow-ups remain: reuse a GPU model across separate batch child
processes, stage verified selected inputs on local Colab disk to reduce Drive I/O,
and avoid whole-document native extraction for very narrow PDF page selections.
A single `process` invocation already reuses its engine for its selected pages.
These optimizations require profiling and recovery tests before changing the
acquisition/OCR process boundary.

`notebooks/corpus_pipeline_colab.ipynb` is the maintained production notebook.
The existing `corpus_pipeline_colab_updatedVM.ipynb` is retained as a historical
variant; it does not include these reliability fixes. Removing or merging that
variant remains a maintainer decision.
