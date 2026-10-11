# Proposed data contracts

Status: mixed implementation/design specification. Catalog validation and PDF download receipts/checkpoints are implemented; richer metadata, extraction and dataset contracts remain proposed. See [download validation](DOWNLOAD_VALIDATION_RESULTS.md). Preserve the existing 23-column CSV until a reviewed migration is needed; use versioned sidecars for richer provenance and stage outcomes.

## Catalog contract

Current columns:

```text
doc_id,title,subject,domain,grade,education_level,document_type,source,source_url,
publication_year,exam_year,language,license,status,local_filename,sha256,
extraction_method,ocr_required,page_count,quality_score,pipeline_version,
last_processed,error
```

| Field group | Proposed validation |
| --- | --- |
| Identity | Unique nonempty `LK-EDU-NNNNNN` ID; existing IDs never renumbered |
| Source | Real HTTP(S) URL and source name for actionable discovery/download rows; intentional pilot placeholders are annotated and ineligible for downloads |
| Taxonomy | Subject/domain/education level from config; empty when unknown; mapping evidence retained |
| Grade/year | Preserve ranges; separate exam/publication years; unknown is empty, not zero or guessed |
| Type | `textbook`, `teacher_guide`, `syllabus`, `past_paper`, `marking_scheme`, `lesson`, `article`, `workbook`, `other` |
| Language/license | Source language is a hint; document language and rights evidence must be checked before appropriate release |
| Artifacts | DOWNLOADED and later require verified persistent raw path and 64-character lowercase SHA256 |
| Processing | Known lifecycle/failure state, pipeline version, UTC ISO timestamp, structured failure detail when failed |
| Quality | Documented metric scale/version; empty when unmeasured; no default score masquerading as a measurement |

CSV row length/header validation, unique IDs, normalized URL duplicates, and state requirements must fail safely without rewriting invalid input. Validate the eight pilot rows as intentional incomplete entries, not actionable download jobs.

## Sidecar contracts

Use UTF-8 JSONL or another explicitly versioned format. Names below are proposed storage paths, not existing files.

| Sidecar | Required fields |
| --- | --- |
| `corpus/catalog/source_evidence.jsonl` | schema version, source ID, approved crawl flag/date/evidence, canonical base URL, exact crawl/resource hosts, robots observation/date, terms/license evidence and decision |
| `corpus/catalog/discovery_decisions.jsonl` | run ID, source ID, referring/final page URL, candidate URL, title/raw evidence, decision, integer score, rule reasons/version, timestamp |
| `corpus/catalog/document_evidence.jsonl` | doc ID, pilot marker if applicable, fetched/final URLs, fetch time/status/MIME/bytes, source aliases, raw artifact path/hash, language/metadata/rights evidence |
| `corpus/catalog/stage_events.jsonl` | run/task/doc IDs, stage, input hash, config/version, old/new status, outputs/hashes, start/end UTC, outcome/error, retry count |
| `corpus/catalog/duplicate_groups.jsonl` | doc/question IDs, canonical ID, group ID, exact/near method/version/threshold, evidence and review outcome |

Records reference stable IDs and hashes rather than trusting mutable file paths. Unknown, inferred, source-declared, machine-verified, and human-reviewed metadata need distinct evidence states.

## Extracted page record

Required: schema version, doc ID, raw SHA256, zero/one-based page convention (choose one and document it), page index, extraction method/version/config hash, text blocks with reading order and optional bounding boxes, figure/table asset references, OCR requirement/outcome/confidence, quality measurements and errors.

A document with partially successful extraction is not complete. OCR confidence is tool-specific and cannot replace reviewed error measurement. Preserve source text alongside normalized output.

## MCQ record

| Field | Contract |
| --- | --- |
| `schema_version`, `question_id` | Versioned schema; stable unique identifier |
| `stem`, `options` | Nonempty Sinhala/mixed educational text; ordered array of `{label,text}`; unique labels and nonempty options |
| `answer_index` | Integer index into options, zero-based; exactly one supported answer for labeled releases |
| `subject`, `domain`, `grade`, `education_level` | Controlled project metadata; benchmark mapping separately stored |
| `difficulty`, `difficulty_origin` | Easy/Medium/Hard only when explicitly established; otherwise null; origin organiser/human/synthetic/calibrated |
| `doc_ids`, `source_spans` | Parent paper/passage, page/block coordinates and original question number |
| `answer_origin`, `answer_evidence` | Authoritative marking scheme, reviewed annotation, or synthetic; key doc/span and paper pairing evidence |
| `synthetic`, `generation` | Boolean; if true, generator/prompt/config versions, parent passage hashes, generation run, verification result |
| `language`, `quality`, `review_state` | Observed language, independent quality checks, known acceptance/rejection reasons |
| `duplicate_group_id`, `split`, `release_id` | Split-integrity lineage; source-derived variants share groups |

Question content below is an invented formatting placeholder, not a benchmark example:

```json
{
  "schema_version": "mcq-1",
  "question_id": "example-only",
  "stem": "උදාහරණ ප්‍රශ්නය",
  "options": [{"label": "1", "text": "විකල්පය එක"}, {"label": "2", "text": "විකල්පය දෙක"}],
  "answer_index": 0,
  "difficulty": null,
  "answer_origin": "placeholder",
  "review_state": "EXAMPLE_ONLY"
}
```

This minimal example is intentionally incomplete and must not pass a training-release validator. The challenge's actual option count and answer-label format must be learned from authorised development/schema material; do not assume the example's two choices represent the competition format.

## Splits and dataset releases

Different outputs derive independently from the master corpus: `datasets/pretraining/`, `instruction/`, `qa/`, `evaluation/`, and optionally `rag/` for general research. A clean document can feed several outputs with lineage recorded.

Group by source document family, paper/year/version, duplicate cluster, parent passage and synthetic family before splitting. Do not randomly split sibling questions from the same source across train and validation. Exact normalized-text and near-duplicate checks apply at both document and question level. If near-duplicate detection joins groups across splits, resolve the grouping before release.

Store release ID, dataset role, source/record counts, accepted/rejected counts, file hashes, code/config versions, split assignments, random seed, grouping algorithm, contamination checks performed and their limits, rights decisions, generator disclosures and quality-audit results. Hash a canonical representation while preserving original content. Unknown rights or missing label evidence must be visible in release eligibility, not erased.

Authorised competition development data remains a separately identified dataset; hidden tests are never part of a corpus/dataset release or contamination-development process.
