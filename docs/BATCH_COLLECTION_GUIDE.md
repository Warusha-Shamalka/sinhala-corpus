# Continue collecting without retyping every page

The bounded batch runner collects and processes public resources while source review
is deferred. It preserves provisional OCR text, warnings and provenance. It does not
approve text, change review decisions or claim an accuracy percentage. “About 90%”
on some inspected pages is a useful observation, not a measured corpus-wide result.

## Setup

Use the existing production Colab environment and frozen Surya checkpoints. Keep one
writer per persistent store. The selected configuration must point every stage to the
same catalog/raw root, and its OCR revision/model path must already be configured.
See [CORPUS_PRODUCTION_GUIDE.md](CORPUS_PRODUCTION_GUIDE.md). The notebook now has an
optional batch section after the two-page pilot and quality report.

Start with a dry run against the actual persistent configuration:

```bash
python3 -B -m pipeline.workflow run \
  --config /tmp/sinhala-corpus-production/configs/pipeline.yaml \
  --doc-id LK-EDU-000264 \
  --max-batches 5 --max-download-jobs 1 --max-new-pages 10 --dry-run
```

Replace the `/tmp/...` path with your actual store configuration for deployment.
In Colab, use `str(CONFIG)` in the notebook's `execute()` helper. Dry-run shows current
eligible downloads and existing raw documents; it does not predict which future
downloads will succeed. It performs no requests, GPU loading, locks or writes.

Remove `--dry-run` to execute the bounded queue. `--doc-id` is repeatable;
`--source alapiedu` scopes both collection and processing to that configured source.
With neither selector, the runner considers the configured catalog. It does not crawl
websites or discover fresh URLs automatically: discovery remains a separate stage.

## Batch behavior and limits

Each cycle selects fresh eligible downloads, then processes the eligible downloaded
PDF/HTML documents within scope. Completed page bundles are verified and reused.
Per-stage limits and raw/image/time bounds still apply.

| Setting | Default | Meaning |
| --- | ---: | --- |
| `--max-batches` | 3 | Maximum collect/process cycles in one invocation |
| `--max-download-jobs` | 5 | Maximum download jobs reserved across cycles, including failures |
| `--max-new-pages` | 20 | Maximum newly saved page bundles across cycles, including truncated/failed predictions |

The runner also retains `download.max_documents` and `processing.max_pages` from
the configuration. A pilot configured for two new pages per stage can therefore
produce at most ten new pages over five cycles. Existing verification does not consume
the new-page budget. Full native PDF inspection, hashing and model loading are outside
that budget. Limits are not a hard overall wall-clock deadline.

Failed download jobs are not selected again within the same invocation. A later
invocation may retry them with the ordinary bounded transport retries. Document-level
processing failures are excluded from later cycles in the current invocation; saved
failed OCR pages remain immutable and are verified on resume. Use a new processing
variant/output root for an intentional OCR retry, as in the production guide.

Collection and OCR execute in separate Python child processes. This keeps the OCR
socket block from disabling later downloads. Model weights may reload for each
processing cycle; this implementation favors isolation over a long-lived GPU service.
Interrupting the runner terminates the active stage process and saves its journal;
already checkpointed raw/page artifacts remain available for verification on restart.

Stop reasons distinguish page/job/cycle limits, exhausted selected work, no progress,
interruption and stage setup failure. Reaching a limit is a normal bounded stop, not
proof that every source document has been processed. Job errors remain visible and
make the workflow command exit nonzero. Setup errors exit 2; interruption exits 130.

## Storage and restart

The runner writes under the parent of `processing.log_root`:

```text
corpus/logs/batch/batch_<UTC timestamp>_<suffix>/
  run.json
  sources.yaml
  config_001.yaml
  config_002.yaml
  ...
```

`sources.yaml` freezes the source approval configuration used by the child stages.
Its hash is recorded in the journal. `run.json` records selected jobs, stage results, errors, current phase, caps, newly
saved pages and processed bundle paths. Each cycle's config snapshot preserves the
caps actually passed to its child processes. Stage-specific progress/receipts/logs
continue in their existing directories. `run.json` is a batch journal, not a shared
`pipeline.progress` snapshot; inspect its `active_phase` and child report progress paths.
Rerun the same bounded command to verify previous outputs and continue the queue.
No catalog state is promoted to training-ready by the runner.

## Provisional text snapshot

Use the actual `report_path` printed by the completed batch run:

```bash
python3 -B -m pipeline.workflow provisional \
  --run-report /actual/store/corpus/logs/batch/batch_run/run.json \
  --output /actual/store/corpus/clean/provisional/batch_001
```

This creates an immutable snapshot containing:

- `provisional_text.jsonl`: nonempty page text, source/model identities, warnings,
  completion outcome, `review_required=true`, and **`training_approved=false`**.
- `source_bundles.jsonl`: source bundle paths and manifest hashes for every selected
  page, including empty exclusions.
- `excluded.jsonl`: empty pages excluded from the text file with their warning flags.
- `manifest.json`: output hashes, page/method/warning counts and the batch report hash.

Truncated pages with nonempty text are preserved with their explicit outcome/warnings.
These are inspection/provisional corpus artifacts, **not reviewed training releases**.
There is no certified split, deduplication, label correctness or accuracy percentage.
Retain the master source store; the snapshot references its images/HTML and does not
copy all source material. Corrupt sources, running reports, ambiguous page versions,
all-empty text and existing output folders are rejected.

Later, select useful pages for correction/review and export via the reviewed pathway.
This allows acquisition to continue while the team evaluates OCR and reduces review
to the material it actually wants to include in a verified release.

## Validation still needed

Local tests exercise bounded orchestration, caps, resume, failures, dry-run safety,
an actual isolated CPU HTML process, and provisional export integrity. This does not
validate a new multi-cycle Surya GPU run or certify Sinhala transcription accuracy.
Run a small Colab batch before increasing limits.

Local verification on 12 October 2026: fourteen new tests pass; the complete offline
suite ran 251 tests (250 passed, one Tesseract test skipped). All twelve production
notebook code cells and embedded setup programs parse without saved outputs. The
real child-process integration used static HTML on CPU; Surya multi-cycle GPU/Drive
execution remains to be checked in Colab.
