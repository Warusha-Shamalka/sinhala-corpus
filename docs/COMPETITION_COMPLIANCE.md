# Competition boundaries and reproducibility

Authority: the rules pasted by the user on 8 October 2026. This document interprets those rules for engineering; it is not an independently verified organiser rulebook. Preserve the official rule version when available. The general corpus may support broader research, including RAG datasets; the challenge inference package has stricter boundaries.

## Rules and consequences

| Supplied rule | Engineering consequence | Evidence to retain |
| --- | --- | --- |
| Team has 1–4 people; one team per person; one contact-owned Codabench account | Keep a team/contact record; do not create extra accounts | Team declaration kept privately |
| People with prior access to the full dataset cannot participate or advise | Do not acquire or inspect the full benchmark as a training source | Source exclusions and access declarations |
| Total inference models ≤8,000,000,000 parameters | Count every base, adapter, router, classifier, translator, and other inference model; count total MoE parameters and all ensemble members | Exact model configs, parameter counts and accounting method |
| Only open-weight models released before 1 October 2026 | Require release evidence and pinned revisions for every inference model | Model card, original release date, license, revision, hashes |
| Quantization does not reduce parameter count | Use quantization only for memory/speed planning | Full parameter count plus quantization configuration |
| No closed APIs during inference | No remote model calls or API-dependent prediction steps | Offline dependency/runtime checks |
| Public training data and open-model synthetic data allowed | Build auditable training releases from independently sourced material | Origin, rights, transforms and generator manifests |
| Closed APIs only for disclosed training-data generation | Log provider/model/date, generation purpose, prompts/config versions, and generated record IDs if used | Explicit disclosure in report; never send hidden-test questions |
| No test questions used for training, tuning, or prompt design | Freeze data, prompt, model and inference configuration before the hidden-test run | Release checksums, freeze record, run configuration |
| No internet or retrieval during inference | Prediction code reads questions, permitted prompt/config, tokenizer and model weights; no corpus, dictionaries, indexes, or external lookups | Self-contained artifact and offline reproduction run |
| Fully automatic predictions; no manual answers | Validate input/output mechanically; do not hand-correct hidden-test predictions | Automated inference logs and output validation |
| Finalists share code/scripts/model manifest and system report | Package exact dependencies and reproducible commands | Manifest, scripts, hashes, environment and report |
| No publishing/redistributing test questions | Keep test inputs and outputs out of Git, public logs, examples, and corpus stores | Private submission storage and access policy |

The user supplies “before 1 October 2026”; treat this as a strict cutoff, not inclusive of 1 October. Do not assume a public model named “8B” fits the exact cap: base plus adapters may exceed it. Inference-time option permutations using the same model do not introduce new parameters, but must fit the runtime budget. Sequentially loading distinct ensemble models does not avoid their summed count.

## Data separation

Maintain three explicitly identified roles:

1. Independent public corpus and its derived training releases.
2. Organiser-authorised development questions with answers, used according to competition permission and the team's declared evaluation policy.
3. Hidden test questions, isolated from collection, generation, curation, prompt development, and training.

Do not download the published full SinhalaMMLU benchmark or its train/dev/test mirrors as a shortcut to training data. The competition development set is a separately authorised input; do not assume public benchmark splits match it. Consult paper metadata without fetching benchmark question files. Block known benchmark mirrors, contest test endpoints, and explicit answer dumps by source metadata. Remove exact and near duplicates of the authorised development examples from external training releases when maintaining an honest development holdout. These comparisons must not load hidden test questions.

Public curriculum material can independently overlap the benchmark's source documents. Hidden-test overlap cannot be proven absent without prohibited test access. Record independently selected source provenance and ask organisers for a written interpretation if their official rules leave public-source overlap unclear; do not inspect test items to resolve it. Continue engineering on independent materials while this interpretation is pending.

## Training versus inference boundary

Network collection, OCR, corpus search for curation, document pairing and synthetic-data generation belong in preparation/training. They are not shipped into prediction code. Training-only teacher models need their own disclosure, but are not counted as inference models unless loaded by the submitted inference system. This is an interpretation of the supplied inference cap and must yield to official clarifications.

Keep `datasets/rag/` for general research separate from the challenge artifact. Do not implement RAG as an accuracy enhancement for this competition. Corpus facts must reach the prediction system through model training, rather than hidden lookup tables or dynamic prompt stuffing.

## Freeze and reproduction checklist

- Record the exact repository revision, Python/runtime dependencies, training seed/config, dataset release/hash, prompt version and checkpoint hashes.
- Populate the model manifest for every inference component; validate nonnegative integer counts, open weights, strict release cutoff, and a summed total within the cap.
- Record adapter handling: separate adapters add parameters; a merged checkpoint must be counted from the actual deployed tensors, without disguising an ensemble or omitting components.
- Match the actual organiser input/output schema; keep one valid answer and original question ID per input, with no missing, extra, reordered, or duplicate rows.
- Run the frozen artifact on the authorised development set in a network-disabled environment with no corpus/index mounts. Record hardware, memory, runtime and output hash.
- Complete the report and cite [Pramodya et al., EMNLP 2025](https://aclanthology.org/2025.emnlp-main.1673/).

Still needed from the official competition materials: rulebook/version, development schema, output-label format, runtime/hardware limits, available question fields, deadlines, and any additional training-data/model-release clarification. These are recorded gaps, not reasons to stop current discovery work.
