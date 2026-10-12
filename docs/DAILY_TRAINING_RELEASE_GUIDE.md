# Daily text releases and training handoff

This repository builds immutable text candidates for experimental daily training.
The separate training repository trains, evaluates and submits the model. These
releases support text/domain adaptation; they do not supply MCQ answer labels.

## Run in Colab

Push this branch and use the updated production notebook from that pushed branch.
After creating a provisional snapshot, set `BUILD_DAILY=True` in its final section.
Leave `LAST_CONSUMED_RELEASE=None` for the first release. Outputs live under:

```text
My Drive/sinhala-corpus/production_v1/datasets/pretraining/daily_<UTC timestamp>/
  train.jsonl
  validation.jsonl
  added_train.jsonl
  candidates.jsonl
  excluded.jsonl
  duplicates.jsonl
  changes.json
  handoff.json
  manifest.json
```

The CLI equivalent is `pipeline.workflow daily-release` with `--provisional` pointing
to the completed provisional snapshot and `--output` to a new folder. Both
`--provisional` and `--reviewed` are repeatable. Reviewed inputs must be verified
reviewed releases. Never supply SinhalaMMLU hidden test questions or answers.

## Filtering and status

The builder preserves source/model identities, normalizes NFC/line endings and
removes only exact terminal scanner watermark lines (`Scanned with CamScanner` or
`Scanned by CamScanner`). Transforms and input text hashes are recorded. It does not
repair spelling, infer equations, translate or invent answers. HTML boilerplate
removal happens upstream.

Default eligibility requires at least 80 non-whitespace characters, at least 80%
Sinhala letters among alphabetic characters, and no replacement/unreadable markers,
control characters, unexpected-script or repetition warnings. Provisional pages
must have no stored quality flags. Provisional OCR also needs a `predicted` outcome
and `complete` completion status. Verified corrections may resolve original OCR
warnings but still undergo basic filtering.

Rejected rows are listed in `excluded.jsonl`; source artifacts remain unchanged.
Short/bilingual passages and useful pages with unresolved warnings may be excluded.
Collect additional suitable material rather than silently declaring them accurate.

Eligible provisional train rows have `experimental_training_eligible=true`, but
retain `training_approved=false`, `review_required=true` and
`source_review_status=provisional`. Verified inputs are distinguished explicitly.
Eligibility is an engineering heuristic, not measured OCR accuracy or human review.
Missing subject/grade/language/license metadata is retained and counted; source-use
permission and reviewer authenticity are not invented by this builder.

## Splits and deduplication

All accepted predecessor/input pages are considered together. Shared document IDs,
raw hashes, source URLs and exact/near duplicate text connect source families before
split assignment. Exact matching folds whitespace after NFC; near matching uses
word 5-gram Jaccard at 0.9 for texts with at least 30 words. Not every paraphrase,
translation or short near duplicate is detected.

New families receive deterministic splits from `--split-seed` (default
`sinhala-corpus-v1`) and `--validation-percent` (default 10). This is a hash allocation
probability, not an exact page ratio; small corpora may land entirely in one split.
The initial Biology document `LK-EDU-000264` lands in train with the default policy.
Benchmark development evaluation remains separate.

Inherited/reviewed splits stay fixed. New links bridging prior train/validation/test
families block the release rather than silently moving data. Reviewed test pages
are reserved in the ledger and never exported into train/validation files.

Within duplicate groups, human-verified representatives are preferred, then prior
representatives. Alias pages remain in `candidates.jsonl` for future split grouping;
`duplicates.jsonl` records dropped representatives. Retain the master source store.

## Cumulative versus daily delta

For later releases, pass `--previous` or set `LAST_CONSUMED_RELEASE` to the release
actually consumed by the checkpoint you are continuing from. Do not automatically
choose the newest folder if its training job failed or never ran.

- Fresh base: use `train.jsonl`, the cumulative deduplicated corpus.
- Matching continual checkpoint: use `added_train.jsonl`, novel train text relative
  to that predecessor.
- Corpus validation: use `validation.jsonl`; never train on it.

Repeating the same pages produces a zero-record delta. New duplicates of already
trained text do not replay. Zero delta means no novel training text, not that another
training run is required. Deliberate replay belongs in the training configuration.

`changes.json` records additions, replacements, removed train IDs and predecessor
content hashes. Changed provisional text for an existing page requires
`--replace-existing`; supply only the intended newer snapshot when using it.
Verified corrections can upgrade provisional text, and provisional inputs cannot
downgrade verified text. Corrections cannot undo errors already learned by a model;
compare fresh training when substantial corrections matter.

Filtering/split policy changes require an explicit separate lineage. The operational
`--max-candidates` bound (default 5,000 candidates before filtering) may be increased
without changing splits. It limits deduplication population, not total wall-clock
time or arbitrary file sizes. Existing output folders are never overwritten.

## Training repository contract

`handoff.json` records task, release ID, file hashes, cumulative/delta filenames and
expected checkpoint predecessor. The training repository should:

1. Run `pipeline.workflow verify-daily-release --root` on the frozen release.
2. Verify the selected input hash and read each JSONL record's `text` field.
3. Record release/input hashes, base model ID/revision, loaded parameter count,
   configuration hash, parent checkpoint and output checkpoint hashes.
4. Preserve an evaluation-run identifier and compare with the previous best on a
   fixed development evaluation before choosing the daily submission.

Required training-run fields are listed in the handoff. This repository neither
trains nor submits, and does not certify model parameter declarations. The separate
training/submission system must enforce the competition inference parameter cap,
model release cutoff and offline/no-retrieval inference rules.

## Verification and deployment

Verification checks artifact hashes, source/text identities, ledger/split consistency,
duplicate leakage, delta contents and handoff checksums. These checks establish
artifact consistency, not linguistic correctness. Keep one writer and all input
snapshots/predecessor releases. No daily schedule is installed automatically: freeze
data after acquisition and let the training repository own checkpoint consumption.
A real Colab release and training-repository integration still need deployment tests.

Local verification on 12 October 2026: twelve new daily-release regression tests
pass, including zero replay, source-family splits, duplicate bridges, quarantine,
verified upgrades, explicit replacements and corruption checks. The complete offline
suite ran 264 tests (263 passed, one Tesseract test skipped). Thirteen notebook code
cells and embedded setup programs parse; no model training was executed locally.
