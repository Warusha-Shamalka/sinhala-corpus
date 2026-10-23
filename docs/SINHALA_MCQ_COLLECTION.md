# Sinhala study corpus and unique MCQ paper/answer pairs

The user's selected websites are configured in `sources.yaml`. The active scope
is `collection.yaml`: Sinhala textbooks, study notes (`lesson`), syllabuses and
teacher guides across subjects, plus explicit MCQ papers and matching answer keys.
GovDoc's `/syllabus` section remains distinct from its `/text-books` section.
Past Papers Wiki includes the supplied A/L, O/L and Sinhala Biology entry points;
AlApiEdu includes papers, markings and notes.

## Language and exam scope

An explicit Sinhala-medium title/URL or reviewed metadata is required. A website's
default language does not establish a file's medium. Explicit English/Tamil
resources are excluded during discovery/selection. Mixed-medium category pages
remain traversable, and unknown-medium resources go to deferred review.

The MCQ restriction applies to exam material, not ordinary study chapters.
MCQ/multiple-choice/බහුවරණ must be explicit. `Paper I` alone is insufficient:
question formats differ by subject. Essay files are excluded. Full/mixed PDFs and
unknown formats are deferred instead of silently including essay pages. They need
a separate MCQ-only file or a future reviewed page-selection/splitting workflow.

## Exactly one active pair

National exam identity includes exam, subject, exam year, medium, kind, session
and syllabus version. A/L grade labels do not create additional copies of the
same national paper. Model/term-test identities also need grade, term/session and
issuer. Different schools/provinces are different papers; unknown school identity
is deferred. Conflicting years such as `2023 (2024)` are not resolved by guessing.

The planner chooses one compatible pair per identity, preferring already collected
complete pairs and then the configured source order. Deterministic URL/ID ties
make reruns stable. Known medium/part/version conflicts cannot form pairs. Missing
counterparts and unresolved identifiers remain pending, without invented answers.

Alternate mirror URLs stay in the exclusion audit, but are not selected again.
After a download's complete SHA256 is known, verified existing raw artifacts are
checked. A second identical file is not published: its catalog row becomes
`DUPLICATE` and identifies the original. Generic titles such as “Physics notes”
are not enough to merge different chapters. Existing user files are preserved;
older duplicates can remain as history outside the active selected collection.

Policy filtering applies to collection, processing, optional batch runs and review
preparation. An empty selection never falls back to processing the whole catalog.

## Running the policy

Update the checkout and run the notebook's configuration-update cell. It installs
the policy if missing and preserves existing reviewed overrides. Source/subject
updates keep their backups; keep the Drive-specific pipeline configuration.

The processing configuration cell also saves `collection_policy` in the Drive
pipeline configuration, so subsequent collection, processing, batch and review
commands inherit the same policy even if the flag is omitted. The explicit CLI
flag overrides that configured path.

The notebook now searches `govdoc`, `pastpapers_wiki` and `alapiedu`. Collection and
processing pass the policy automatically. Download `--until-done` attempts every
selected resource once, within source request/time budgets. Discovery is still
bounded and cannot promise exhaustive website coverage.

Broad notebook discovery defaults are 1,000 HTML pages, depth 5, 2,500 requests,
3,600 seconds and a 10,000-URL queue per website. Set smaller values for a pilot.
Inspect each source's stop reason; reaching a page/request/time limit does not
mean the entire website has been covered. The workflow CLI exposes these limits.

```bash
python -B -m pipeline.workflow plan-collection \
  --config /path/to/store/configs/pipeline.yaml \
  --output /path/to/store/corpus/clean/collection_plans/run_001

python -B -m pipeline.workflow collect \
  --config /path/to/store/configs/pipeline.yaml \
  --collection-policy /path/to/store/configs/collection.yaml --until-done

python -B -m pipeline.workflow process \
  --config /path/to/store/configs/pipeline.yaml \
  --collection-policy /path/to/store/configs/collection.yaml --until-done

python -B -m pipeline.workflow extract-mcq \
  --config /path/to/store/configs/pipeline.yaml \
  --collection-policy /path/to/store/configs/collection.yaml \
  --output /path/to/store/datasets/mcq/provisional/run_001
```

Choose fresh snapshot directories. Add `--config-hash HASH` to MCQ extraction when
multiple processing versions exist. Plans contain selected documents/pairs,
excluded mirrors, deferred records, a review CSV and input/code hashes. Discovery
does not silently rewrite older catalog labels.

## Reviewed metadata

Corrections to unknown identifiers can be recorded in the Drive policy:

```yaml
overrides:
  LK-EDU-001600:
    medium: si
    question_format: mcq
    paper_kind: past
    reviewer: 'Named reviewer'
    source_evidence: 'Compared the complete PDF: Sinhala MCQ-only paper'
```

Every override requires a reviewer and evidence. It does not approve training
text. Mixed/essay labels cannot be turned into whole-file MCQ scope through an
override. Use a separately identified MCQ file or a reviewed page-scope extension.

## Provisional structured MCQs

The parser reads verified selected page bundles and matching raw receipts.
Questions need explicit numbered stems and consecutive option labels. Answers
come from explicit answer-key rows; joins use question number within the selected
pair and require the answer to match an available option.

Outputs are `questions.jsonl`, `answers.jsonl`, `linked_mcqs.jsonl`, `issues.jsonl`,
the selection and a hash manifest. Provenance includes URLs, raw/page identities,
text hashes and character spans. Incomplete OCR, missing options, conflicting keys,
essay headings and unknown layouts are reported instead of reconstructed.
Identical question/options with the same answer yield one linked MCQ with multiple
source occurrences. Conflicting answers remove that question from linked output.

All records remain `review_required=true`, `training_approved=false`. Split-page
questions, inline/column options, diagrams and non-row answer tables may need
manual transcription or a later layout-aware parser.

## Current verification limits

The repository catalog preview selected 17 study records and no complete MCQ
pairs. It deferred 462 records: 457 missing medium, two unknown exam formats and
three conflicting metadata records. These are metadata limits, not completed
downloads or measured OCR accuracy. New discovery and reviewed metadata are needed.

GovDoc's observed file-host robots HTTP 403 remains enforced. Existing imported
PDFs stay usable. The policy does not bypass access restrictions or control Colab
runtime disconnects; inspect the saved processing and acquisition reports.

Local verification on Python 3.14.4 ran 323 tests successfully, with one optional
Tesseract integration test skipped. Tests cover mirror selection, strict medium
and format filtering, institution distinctions, physical content deduplication,
policy-scoped processing and source-linked MCQ/answer extraction. The notebook's
30 cells and embedded scripts parsed, and `pip check` found no broken dependencies.
