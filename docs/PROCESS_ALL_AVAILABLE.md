# Process every available image and document page

The production notebook now defaults to every eligible downloaded or registered
document in the current store, using its actual page count. It runs until that
queue finishes, rather than stopping at the page/document batch caps.

"Available" means cataloged `DOWNLOADED`/`EXTRACTED` PDFs, HTML documents and
registered PNG/JPEG images with verified raw receipts. This does not start a web
crawl or scan arbitrary Drive folders. Register standalone images with
[`import-image`](IMAGE_OCR_GUIDE.md); acquire new sources separately.

## Existing Colab session

First update the repository checkout to include the new code. Publishing the
branch and updating the existing checkout is sufficient; there is no need to
reinitialize the Drive store, reinstall models or repeat discovery/downloads.
If the Colab kernel already imported `pipeline.colab`, reload it before using the
new helper signature:

```python
import importlib
from pipeline import colab
importlib.reload(colab)

processing_report = colab.execute(
    PYTHON, ROOT,
    'process', '--config', str(CONFIG),
    '--until-done', '--progress', 'plain',
    allow_partial=True
)
```

Omitting `--doc-id` selects every eligible document in this store. Omitting
`--page-number` uses each document's actual pages. To restrict the run to `DOC_IDS`,
insert `*selection_args()` in the command. The notebook's normal process cell
already uses these switches:

```python
PAGE_NUMBERS = None
PROCESS_ALL_AVAILABLE = True
RUN_UNTIL_DONE = True
```

`MAX_PAGES` and `MAX_DOCUMENTS` remain useful for a bounded pilot when
`RUN_UNTIL_DONE=False`. In until-done mode those two processing caps do not stop
the worker, and the native PDF page cap is raised to the actual document length
when necessary. Byte/pixel limits and command/document deadlines still apply.
The same OCR engine is reused throughout one process; the notebook does not
restart the model every 30 pages.

CLI equivalent:

```bash
python -B -m pipeline.workflow process \
  --config /path/to/store/configs/pipeline.yaml \
  --until-done --progress plain
```

## Mixed document lengths and incomplete pages

A requested range such as 1–6 is intersected with the available pages of each
document. A two-page PDF processes pages 1 and 2 and reports 3–6 in
`warnings[].skipped_page_numbers`. A selection with no available pages produces a
warning and no OCR calls for that document. Missing page numbers do not fail the
run. HTML and single-image documents each have only page 1.

A page rendering or OCR failure is recorded with document/page identity; later
pages continue. Raw verification or whole-document extraction failures are
recorded at document level and later documents continue. Successful outputs are
published page by page, so a runtime disconnect does not erase them. Restart the
same command to verify/reuse matching saved pages and attempt remaining work.

Existing incomplete OCR is reported as `existing_incomplete`; it is not retried
indefinitely. Add `--retry-incomplete` for an explicit new attempt. Actual failed
pages may still need source inspection, a controlled preprocessing experiment, or
manual transcription. The CLI keeps exit code 1 when any page/document failed.
The notebook opts into `allow_partial=True` only for valid page-processing reports,
so that this exit status does not cause `CalledProcessError`. Its errors and
warnings remain visible. Exit code 2 and malformed output still raise exceptions.

`stop_reason: queue_finished` means the eligible queue has been visited. Check
`errors`, `outcomes` and `quality_flags` to determine what needs attention; it does
not mean every OCR prediction was complete or accurate.

Updating processing code creates a new processing fingerprint. Previous artifacts
are retained, and some pages may be processed again into a new version. When
preparing review, select the current report's `processing_config_sha256`.

## Validation

Offline regression coverage exercises mixed-length PDFs, absent requested pages,
processing beyond document/page/native-extraction caps, one-engine reuse and
resume, continuation after truncated OCR/render failure, registered images,
whole-store notebook selection, and partial-report handling. Actual Colab GPU and
Drive behavior still needs runtime validation.

Local verification on Python 3.14.4: 287 tests ran successfully, with the optional
real Tesseract integration test skipped. The production notebook's 16 code cells
and embedded scripts parsed, the CLI full-queue dry run succeeded, and
`git diff --check` found no whitespace errors.
