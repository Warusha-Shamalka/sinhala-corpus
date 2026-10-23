# OCR for standalone PNG/JPEG images

Use an existing configured persistent store and a source whose `enabled` and
`verified` settings are true. One imported image becomes one document with page 1.
Keep an actual source URL and descriptive title; a local filename is insufficient
provenance. The importer accepts only single-frame PNG/JPEG content, regardless
of the local filename extension, and preserves the exact original bytes.

Install the optional image dependency in a local CPU environment:

```bash
python -m pip install -r requirements.txt -r requirements-images.txt
```

The pinned production Colab environment already has Pillow. Do not replace its
isolated Surya package pins with the local image requirements.

```bash
python -B -m pipeline.workflow import-image \
  --config /path/to/store/configs/pipeline.yaml \
  --image /path/to/source-page.png --source govdoc \
  --source-url https://govdoc.lk/actual-source-page \
  --title 'Actual source title, scanned page 1' --dry-run
```

Replace the paths and source URL with real values. Remove `--dry-run` to register
the image. The command returns its allocated `doc_id`; the same source URL and
bytes can be reimported without duplication. A changed image under the same URL
is rejected, as are conflicting source/title metadata. Multiple images sharing
one webpage URL need an explicit future grouping/provenance design; do not invent
URLs to bypass this one-image-per-source-identity rule.

Configure the existing local OCR snapshot/revision, then process the returned ID:

```bash
python -B -m pipeline.workflow process \
  --config /path/to/store/configs/pipeline.yaml \
  --doc-id LK-EDU-000123 --page-number 1 --progress plain
```

Images do not require Poppler. The configured OCR backend still needs its own
runtime and weights. Raw images live at
`corpus/raw/{png,jpg}/<doc_id>/<sha256>.*` beside matching receipts. EXIF orientation
and transparency are normalized in the rendered `page.png`; raw bytes stay intact.
Byte and input-pixel limits apply before OCR. No upscaling is done automatically.

## Controlled preprocessing

Defaults in the store's `pipeline.yaml`:

```yaml
processing:
  max_input_pixels: 40000000
  preprocessing: {}
  ocr:
    columns: 1
```

For an experiment, `preprocessing` can contain:

```yaml
preprocessing:
  crop: [0.02, 0.03, 0.98, 0.97] # normalized left/top/right/bottom
  rotate_degrees: -1.5           # manual correction, -15 to +15
  grayscale: true
  autocontrast: true
```

These options work for rendered PDF pages too. Crop precedes rotation, followed
by grayscale/autocontrast and final downscaling. A transformed `ocr_input.png` is
saved separately, with its hash, dimensions and transformation record. OCR boxes
refer to OCR-input pixels and are not silently mapped onto the original page.
Keep `{}` as the baseline and compare one change at a time; preprocessing can
remove useful information or make recognition worse.

`ocr.columns: 2` is an optional Surya-only experiment. It orders left then right
within bands separated by lines crossing the page midpoint. Original raw lines
and boxes are retained. Full-width equations, tables and unusual layouts can
defeat this heuristic; compare against the source.

To retry an incomplete prediction with the same configuration:

```bash
python -B -m pipeline.workflow process \
  --config /path/to/store/configs/pipeline.yaml \
  --doc-id LK-EDU-000123 --retry-incomplete --progress plain
```

Use the existing [review and release workflow](CORPUS_PRODUCTION_GUIDE.md) for
correction and approval. An OCR prediction never approves itself for training.
