# Later evaluation and experiment plan

Future work only: the immediate priority is reliable corpus discovery and processing. No development-set evaluation, model selection, fine-tuning or submission currently exists.

## Required inputs

Obtain the organiser-authorised development set, schema/label definitions, official runtime/hardware limits and GPU/storage budget. Verify whether subject/difficulty metadata and visual assets are available at test inference. Do not assume development-only fields can guide inference.

Choose candidates with open weights, verified releases strictly before 1 October 2026 and exact deployed parameter totals below 8B, allowing for adapters and other components. No specific checkpoint is selected here without current primary documentation and measured Sinhala performance. Larger training-only teachers do not automatically qualify for inference.

## Baseline and development policy

Start with one checkpoint, one versioned prompt and deterministic decoding. Adapt the actual organiser schema without changing option order or question IDs. Return one valid label automatically; measure invalid outputs and document fallback behavior. Compare constrained label generation and answer likelihood scoring only as controlled experiments, accounting for multi-token labels.

Record model/tokenizer revision, prompt/config hashes, seeds, parameter manifest, dependencies, hardware, memory and runtime. Check Sinhala tokenization and truncation on authorised development examples.

Fix a grouped tuning/holdout policy or grouped cross-validation before repeated tuning. If training on authorised development examples, disclose it and retain an untouched partition; trained-example accuracy is not model-selection evidence. Prefer independent training material with development reserved for selection. Never use the public full benchmark as a substitute development set.

Report overall accuracy, macro subject accuracy, subject/difficulty accuracy with counts, invalid-output rate, latency, memory and paired changes from baseline. Unknown difficulty stays unknown. Do not assume macro accuracy is the official ranking metric. Show uncertainty for small slices and classify development errors into knowledge, Sinhala comprehension, reasoning, extraction/label quality, option parsing and format errors.

## Controlled experiments

| Experiment | Question | Controls |
| --- | --- | --- |
| Prompt/scoring variants | Does answer handling improve? | Same checkpoint, partition and compute budget |
| Curriculum adaptation | Does clean educational text improve knowledge? | Same MCQ data and evaluation prompt |
| Verified MCQ supervision | Do answer-key examples improve accuracy? | Same base, holdout and training budget |
| Combined adaptation + MCQs | Is there added value? | Comparable token/update budget and seeds |
| Verified synthetic MCQs | Does additional coverage help? | Real-data baseline, quality gate, total training budget |
| Subject sampling | Does balancing help weak subjects? | Same data quality and updates |
| Same-model option permutations | Is accuracy sensitive to option positions? | Same checkpoint, correct label remapping, runtime budget |

Keep simpler methods unless measured gains justify additional cost. All ensemble/router/translation components count toward the inference cap. Corpus search may assist training preparation, but no retrieval can assist competition inference.

## Run records and submission freeze

Record run ID, code/config/data hashes, model/adapter revisions, trainable/deployed parameter counts, hyperparameters, seeds, token budgets, validation policy and metrics. Keep development error examples private where required.

Freeze datasets, weights, prompt, schema adapter and automatic fallback before hidden-test execution. Reproduce on development data in a network-disabled environment without corpus/index mounts. Validate one answer per original input ID and package only inference dependencies. No prompt/training changes may be based on hidden-test questions.
