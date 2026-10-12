# Match public papers to answer keys

This stage validates explicitly declared paper/marking-scheme pairs, detects simple
numbered MCQs, and proposes matches by **pair + section + question number**.
It does not search for a missing marking scheme, infer identity from filenames,
solve questions, or mark OCR text as correct automatically. Use public training
sources only; never supply hidden competition/evaluation material.

## First pilot

1. Choose one public paper and its matching published key. Check exam, subject,
   year, paper number, language and variant (main/resit/term/region as applicable).
2. Discover/download both through the normal corpus stages. Extract their pages,
   preserving raw hashes and processing receipts. Process one small pair first.
3. Build a daily release containing the usable question pages and prepare a task
   packet with `prepare-tasks`. Source IDs and inclusive line numbers are shown in
   `pages.txt`; raw hashes also appear in `sources.jsonl`.
4. Copy `configs/paper_pairs.example.yaml` to a local `paper_pairs.yaml`. Fill both
   identities from the originals. The example's blanks deliberately prevent it
   from being run as a real verified pair. Extra differences such as school, term,
   province or resit belong in the variant identifier. Do not merge distinct exams
   under a generic year/subject label.
5. Select question and key line regions. Assign the same explicit section to
   corresponding regions; use separate sections when numbering restarts. Select
   complete question/choice blocks, excluding page headers/footers. Declare the
   printed choice labels in their actual order. Check the pair against both
   originals, then set `pairing_verified: true` and `pairing_reviewer`.
6. Run matching into a **new** task packet. Inspect `matching_report.json`, then
   compare every proposed stem/choice/answer against the original pages before
   setting the per-item source checks in `annotations.jsonl`.

```bash
python3 -B -m pipeline.workflow match-paper-answers \
  --packet /path/to/task_packet \
  --pairs /path/to/paper_pairs.yaml \
  --output /path/to/new_matched_packet
```

The input packet and catalog are not changed. Existing annotations are retained;
an overlapping question proposal is reported instead of overwriting the annotation.
Configured regions cannot overlap each other. Start from an unmatched packet for
reruns, not a packet already carrying an earlier matching report.

## Numeric answer keys excluded by prose filtering

Many key pages contain almost no Sinhala letters, so they may be absent from a
daily text release. **Do not lower corpus-wide quality thresholds to admit them.**
Pass their processed page bundles as evidence instead:

```bash
python3 -B -m pipeline.workflow match-paper-answers \
  --packet /path/to/task_packet --pairs /path/to/paper_pairs.yaml \
  --release /path/to/originating_daily_release \
  --key-bundle /path/to/processed/key/page_000001 \
  --output /path/to/new_matched_packet
```

Repeat `--key-bundle` for additional key pages. Bundle means the processing folder
containing `manifest.json`, `page.json`, `text.txt` and the source image/HTML, not a
loose OCR text file. Its page identity determines the source record ID in the same
`DOC_ID_RAW_SHA256_p000001` format as ordinary task pages. Its `text.txt` supplies
the line numbers before import; the new packet also displays them in `pages.txt`.
Each key bundle must match a declared key document ID and raw SHA256.

Artifact hashes and source records are checked before and after matching. Imported
pages are marked `evidence_only` and cannot be exported as theory or MCQ examples.
Their split follows the associated paper. The originating daily release is
required to reject conflicts with known document IDs, raw hashes and source URLs,
including reserved evaluation pages and duplicate aliases. Already-present key
pages must not also be imported as external bundles. Incomplete key OCR blocks
proposals for the section. Short-text/low-Sinhala warnings are expected for numeric
keys; other unresolved quality warnings block proposals.

Keep `pairing.json` and `source_bundles.jsonl` with future training data. Any future
release that uses these key documents must preserve this family assignment; the
matcher checks the supplied release, not every historical release in Drive. It
does not rewrite the daily ledger or automatically solve global split planning.
Do not move an existing validation/test key into training to make a pair match.

## Supported layouts and uncertainty

The first parser supports:

- Stems starting `1. ...`, `1) ...`, or `Q1. ...` on a new line.
- Choices starting `(1) ...`, `(A) ...`, `A. ...` or `A) ...` on separate lines.
- Continuation lines inside stems/choices, with complete questions on one page.
- One answer entry per line, such as `1 - B`, `01: (2)` or `1. 3`.

These are structural syntax examples, not benchmark content. No option-label
guessing, fuzzy number matching, OCR digit repair, or semantic answer generation is
performed. The printed choice order must match `choice_labels`; numeric output
answers use one-based positions in that order. Printed labels remain in source
choice text as in the existing exporter.

Side-by-side tables, bare number grids, Sinhala option letters, diagrams, subparts,
multiple questions on one line, questions crossing pages and text explanations as
keys require manual annotation or future layout parsers. An unparsed nonblank key
line blocks proposals for that section, so partially parsed tables cannot silently
create an apparently complete key. Select regions precisely to exclude headings.

Missing choices, missing key entries, repeated question numbers within a section,
duplicate/conflicting answer entries, and unverified pairs are unresolved. Extra
key entries without questions are listed. Wrong identities or cross-split pairs
fail without publishing. All text comes from the source; no new answers are made up.

## Review and export

`matching_report.json` records pair identities, source/evidence line ranges, parsed
key entries, proposed matches and uncertainty reasons. The new `annotations.jsonl`
contains detected MCQ ranges and, for unique matches on a checked pair, a proposed
`answer` and `answer_evidence`. It deliberately leaves:

```json
{"question_choices_verified": false, "answer_verified": false, "reviewer": ""}
```

Check the original stem, choices, all symbols/diagrams, key entry and label mapping.
Set both checks true and record the reviewer only after that comparison. Pair
verification establishes document identity; it is not per-question verification.
Fix unresolved layouts/ranges explicitly and record the reason in the annotation
if useful. Source OCR corrections require a new source release/packet, as before.

```bash
python3 -B -m pipeline.workflow export-tasks \
  --packet /path/to/new_matched_packet --output /path/to/new_task_release
python3 -B -m pipeline.workflow verify-task-release --root /path/to/new_task_release
```

Unchecked matches stay in `mcq_candidates.jsonl`, even when their keys matched.
Source-checked items enter the separate `mcq/train.jsonl` or validation file. The
export retains original paper question number, section, printed labels, pair ID,
key evidence and frozen matching report/configuration. `q_no` remains a release-local
row number; use `provenance.source_question_number` for the printed number.
Theory selection continues independently on the same task packet.

## Colab

The production notebook has an optional **Match a public paper with its answer key**
cell between task preparation and export. Set `PAIR_CONFIG` to the filled YAML,
`KEY_BUNDLES` to any required processed key folders, and `MATCH_ANSWERS=True`.
It creates a new packet and updates `TASK_PACKET` to that result. Review its
annotations before enabling `EXPORT_TASKS`. Select the pushed feature branch in
the notebook setup until these changes reach `dev`.

## Validation status

Offline fixtures are invented and cover ordinary/numeric labels, section restarts,
duplicate/missing keys, mismatched identity, split conflicts, unsupported tables,
incomplete OCR, corruption and the review/export boundary. They demonstrate program
behavior, not Sinhala OCR accuracy. A real public paper/key trial remains pending;
the existing Biology guide cannot establish matching accuracy. The current local
catalog has no records labeled `marking_scheme`. Collect and check one pair before
expanding sources or making accuracy claims.

## Start when there is no paper/key index yet

Prepare an editable index from the existing discovery catalog:

```bash
python3 -B -m pipeline.workflow prepare-pair-index --catalog corpus/catalog/documents.csv --output /tmp/paper-index
python3 -B -m pipeline.workflow suggest-paper-pairs --index /tmp/paper-index/documents.csv --output /tmp/paper-suggestions
```

Use fresh output directories for reruns. `documents.csv` retains source IDs, URLs,
titles and raw hashes. Its role/exam/year/paper hints are unverified; check and edit
these against the public originals. Fill unknown fields, particularly language and
variant. Set metadata_status to verified and supply reviewer only after that check.
Do not change stable document IDs or provenance fields to make a match appear.

Suggestions require matching exam/subject/year for ordinary papers, reject known
identity conflicts, list missing fields and flag multiple candidate partners.
Unknown fields remain unknown; match_count is an evidence count, not a probability.
Nothing is automatically approved or inserted into the answer matcher. Confirmed
pairs still need the pairing YAML and source line regions described above.

Compilation hints get collection_id=UNRESOLVED. Fill an actual collection/edition ID
on both documents before suggesting a compilation pair. This stage never matches a
compilation to an ordinary exam solely by year. Compilation question-origin mapping
remains future work. Discovery of new sites and header extraction are not performed
by these offline commands. Zero suggestions means more metadata or key documents
are needed, not that the catalog should be guessed.

Title-based subject and medium hints now supplement the pairing index. Conflicts with catalog values leave the field blank with a review note. Roman paper numbers I/II/III normalize to 1/2/3; none of these hints approve an identity. See [the marking discovery pilot](MARKING_DISCOVERY_PILOT.md) for current coverage and remaining gaps.


## Combined documents: questions and answers in one source

A marking scheme can contain complete MCQs as well as answers. It does not require
an external paper. The index accepts `role=combined` after inspecting the source;
this does not approve its metadata or answers. Every `key` and `combined` row also
appears in `combined_review.jsonl` when running `suggest-paper-pairs`, so key-only
documents can be checked for embedded questions instead of being overlooked.
A declared combined row gets a self-suggestion with `mode=combined`, still unapproved.
Titles alone never automatically establish that questions are present.

1. Inspect the public original for full question stems, all choices and explicit
   answers. A solution explanation without complete choices is insufficient.
2. Process the document normally and prepare a task packet. Pages supplying
   questions must be regular packet pages; evidence-only imports cannot supply them.
3. Copy `configs/combined_answers.example.yaml` into a local configuration.
   Use the same document ID/hash for both roles (`mode: combined`). Enter actual
   identity metadata; do not invent an exam/year for a compilation.
4. In `pages.txt`, select non-overlapping question and answer ranges and explicit
   section labels. A same-page answer must be outside the question/choices range.
5. For numbered keys (`1 - B`, `2: (A)`), omit `question_number`. For a single
   explicit `Answer: B`, `Correct answer: (B)` or `පිළිතුර: B` line, set
   `question_number: 1` to the original question number. This binding is declared
   from the source, never inferred from proximity. Only one nonblank answer line
   is allowed in such a region. Other explanation/table formats stay unresolved.
6. Check question-to-answer association, then record `pairing_verified` and its
   reviewer. Run the existing command with a fresh output folder:

   ```bash
   python3 -B -m pipeline.workflow match-paper-answers \
     --packet /path/to/task_packet --pairs /path/to/combined_answers.yaml \
     --output /path/to/combined_matched_packet
   ```

Review proposed question/choice text and answer evidence before approving MCQ export,
just as for separate documents. A checked association does not approve OCR text.
The frozen matching report records the route, document identities and source ranges.
Answer regions are excluded from training text; recognized inline answer lines
inside a question region block that question instead of becoming part of a choice.
Repeated numbering must use separate sections. Missing, ambiguous or unsupported
answers stay unresolved; the matcher does not solve questions.

Scope: separate-paper matching remains unchanged. This feature does not automatically
read PDFs to classify combined documents, parse solution prose, reconstruct omitted
choices, handle all table layouts or resolve compilation identities. A real public
combined-document pilot remains required before scaling.
