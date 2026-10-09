# SinhalaMMLU system description template

Status: template only. Replace bracketed fields with measured facts before submission. Do not describe plans as implemented or include hidden-test questions/private answers.

## Team and task

[Team name, 1–4 eligible members, designated contact and single account information appropriate for submission. Official rulebook/version and input/output format.]

## Data and processing

[Actual independent sources, collection dates, approval/rights evidence, document counts, PDF/HTML extraction, OCR, cleaning, deduplication and quality audits.]

[MCQ segmentation, paper/answer-key pairing, verified/rejected counts, grouped splits, development policy, contamination controls and their limits. Distinguish real, synthetic and unlabeled products.]

[Synthetic generators, open/closed status, generation purpose/dates, prompt/config versions, counts, independent verification and closed-API disclosures. State no use only if confirmed.]

## Models and training

[Every inference model/component, open-weight license, pre-1 October 2026 release evidence, pinned revision/hash and exact parameter count. Adapter/merge/quantization handling and summed inference count. Completed manifest location.]

[Training hardware, seeds, dataset releases, optimizer/hyperparameters, context/token budget, checkpoint selection and cost. Training-only teachers listed separately.]

## Inference

[Actual prompt, available fields, scoring/decoding, automatic invalid-output handling, any same-model repeated passes and label mapping.]

[Evidence from a performed offline reproduction that inference has no internet, closed calls, retrieval, indexes, dictionaries or corpus lookups.]

## Results

| Run | Data/model/method | Accuracy | Subject/difficulty counts/results | Invalid rate | Runtime/memory |
| --- | --- | --- | --- | --- | --- |
| [Baseline] | [Configuration] | [Measured] | [Measured] | [Measured] | [Measured] |
| [Final] | [Configuration] | [Measured] | [Measured] | [Measured] | [Measured] |

[Development partition policy, ablations, uncertainty and errors. Official hidden-test score only if released and appropriate; no test content.]

## Reproduction and limitations

[Exact repository/environment revisions, artifact hashes, build/train/infer commands, schema and hardware. Actual reproduction results.]

[Rights/coverage limits, OCR/label errors, small validation slices, independently collected source-overlap uncertainty and compute limits.]

## Required reference

Ashmari Pramodya, Nirasha Nelki, Heshan Shalinda, Chamila Liyanage, Yusuke Sakai, Randil Pushpananda, Ruvan Weerasinghe, Hidetaka Kamigaito, and Taro Watanabe. 2025. [SinhalaMMLU: A Comprehensive Benchmark for Evaluating Multitask Language Understanding in Sinhala](https://aclanthology.org/2025.emnlp-main.1673/). In *Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing*, pages 32943–32961. Association for Computational Linguistics. DOI: 10.18653/v1/2025.emnlp-main.1673.

```bibtex
@inproceedings{pramodya-etal-2025-sinhalammlu,
  title = "{S}inhala{MMLU}: A Comprehensive Benchmark for Evaluating Multitask Language Understanding in {S}inhala",
  author = "Pramodya, Ashmari and Nelki, Nirasha and Shalinda, Heshan and Liyanage, Chamila and Sakai, Yusuke and Pushpananda, Randil and Weerasinghe, Ruvan and Kamigaito, Hidetaka and Watanabe, Taro",
  booktitle = "Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing",
  year = "2025",
  publisher = "Association for Computational Linguistics",
  pages = "32943--32961",
  url = "https://aclanthology.org/2025.emnlp-main.1673/",
  doi = "10.18653/v1/2025.emnlp-main.1673"
}
```
