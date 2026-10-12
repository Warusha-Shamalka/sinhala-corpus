# Separate theory and MCQ datasets

The final corpus products are **theory text** for text adaptation and **MCQs with
source-supported answers** for supervised training. A daily `train.jsonl` is an
intermediate general text release. It can contain front matter, teacher guidance,
exercises and answer keys; its name does not establish that every page is theory.

This stage selects passages from public-source daily releases. It does not read
competition datasets, generate questions, solve questions or invent labels. Never
provide hidden test material to discovery, extraction, annotation, prompts,
generation or training. Tests use invented fixtures only. Public development
evaluation is managed separately in the model repository.

## Prepare a task packet

After the daily release in the production Colab notebook, enable `PREPARE_TASKS`.
Alternatively:

```bash
python3 -B -m pipeline.workflow prepare-tasks \
  --release /path/to/daily_release --output /path/to/new_task_packet
```

The packet contains immutable `sources.jsonl` and readable `pages.txt`, plus
editable `annotations.jsonl`. Each page starts with an empty `segments` list;
unclassified text is never silently treated as theory. Read `pages.txt` beside the
original PDF/image. Its numeric prefixes identify lines, not training text.

Line ranges are one-based and inclusive: `[2, 4]` selects lines 2, 3 and 4. The
original text and hashes stay unchanged. Do not modify the packet source files.
Fix OCR mistakes through the source review workflow, produce a new daily release,
and prepare a new packet; old annotations cannot approve changed page text.

## Annotate passages without retyping Sinhala

For a theory passage, insert a segment such as:

```json
{"kind": "theory", "lines": [1, 2]}
```

For front matter, indexes, answer keys or other material to exclude:

```json
{"kind": "exclude", "lines": [6, 6], "reason": "answer key"}
```

For an MCQ, select its question and choices individually. This is a structural
example only; replace every range with the actual public source line numbers.
It contains no benchmark question:

```json
{
  "kind": "mcq",
  "lines": [3, 5],
  "question_lines": [3, 3],
  "choice_lines": [[4, 4], [5, 5]],
  "answer": null,
  "question_choices_verified": false,
  "answer_verified": false,
  "reviewer": "",
  "answer_evidence": null
}
```

The exporter supports 2–10 distinct choices, preserving their selected order and
source text (including printed option labels). Each question must fit on one
page in this version. Select disjoint question/choice ranges inside the MCQ
segment. Different segments cannot overlap. Unselected lines remain unresolved.

After checking the source question and choices, set `question_choices_verified=true`.
Set `answer` to a **one-based** choice number only when an answer key or explicit
source explanation supports it. Record the reviewer's name and set
`answer_verified=true` after checking evidence against the original. Evidence:

```json
{
  "record_id": "COPY_THE_EVIDENCE_PAGE_RECORD_ID",
  "text_sha256": "COPY_THAT_PAGE_TEXT_SHA256",
  "lines": [6, 6]
}
```

Evidence can be on another included page in the same data split. An answer page
must exist in the daily release or be imported through the
[verified key-bundle route](MCQ_ANSWER_MATCHING_GUIDE.md) as evidence only. Do not
paste external untracked text into the packet. Correct faulty OCR through source
review before relying on it.
The source check confirms the evidence supports the selected answer, including
mapping printed labels to the selected choice order. A hash or nonempty quotation
cannot establish correctness. Do not approve a guessed answer. Selecting ranges
does not require typing an entire Sinhala page.

## Export and verify

```bash
python3 -B -m pipeline.workflow export-tasks \
  --packet /path/to/task_packet --output /path/to/new_task_release
python3 -B -m pipeline.workflow verify-task-release --root /path/to/task_release
```

The production notebook also provides an optional `EXPORT_TASKS` cell.

```text
task_release/
  theory/train.jsonl
  theory/validation.jsonl
  mcq/train.jsonl
  mcq/validation.jsonl
  mcq_candidates.jsonl
  unresolved.jsonl
  excluded.jsonl
  duplicates.jsonl
  evidence/
  manifest.json
```

Theory rows contain `text`, metadata, provenance and inherited review status.
Provisional theory stays unreviewed; classification does not correct OCR.
The model loader consumes `text`, retaining provenance for audits.

MCQ rows contain `q_no`, `question`, ordered `choices`, `answer`, `subject`,
`category`, `metadata`, and provenance. `q_no` is a release-local sequence number;
`record_id` identifies the source segment. Categories use lowercase underscore
versions of corpus domain hints. Grade is an integer when known. Difficulty and
original subject labels stay null without evidence. No benchmark taxonomy or
difficulty label is inferred from question content.

Only source-checked questions, choices and answers enter `mcq/`. Missing answers,
evidence or checks produce `mcq_candidates.jsonl` rows with `answer=null`, a separate
proposed answer (if supplied), reasons and `training_approved=false`. Never feed
candidate rows into supervised training. Empty MCQ output is normal for theory-only
sources. Selected original text may retain OCR math/HTML formatting tags.

Splits are inherited from the daily release. Answer evidence cannot cross splits.
Whitespace-normalized exact duplicate theory passages and MCQs are removed;
reordered MCQ choices are recognized and conflicting answer keys block publication.
Duplicate content crossing splits also blocks publication. Near-duplicate
segmentation, paraphrases and cross-task semantic overlap still need further work;
upstream page-level near-duplicate checks are not complete decontamination.

Every output is hashed; the frozen source packet and annotations allow verification
to reproduce exported records. This establishes consistency, not reviewer identity
or measured linguistic accuracy. A new output directory is required.

## Training handoff and remaining work

For numbered public papers with published keys, the
[answer matching stage](MCQ_ANSWER_MATCHING_GUIDE.md) can create draft MCQ ranges and
propose answers before source review. Numeric key pages can be imported as
evidence-only bundles without relaxing prose filters.

Use theory `text` for text adaptation and MCQ question/choices/answer for supervised
examples. Never train on validation files. The manifest records the originating
daily release and task hashes; record these alongside the model checkpoint. These
are cumulative task exports, not task-level daily deltas. The earlier daily
`added_train.jsonl` is a general text delta and must not be mistaken for an MCQ delta.

Manual line annotations and source answer checks remain supported. The matcher now
handles simple numbered line layouts on explicitly identified paper/key pairs.
Richer layout detection, cross-page assembly, synthetic generation
from public theory, task deltas, richer verified metadata
and the training-repo loader remain future work. Synthetic examples, if added later,
need generator provenance and separate factual validation. Closed-API training-data
generation must be disclosed under the supplied challenge rules. No corpus or
retrieval is used by competition inference.
