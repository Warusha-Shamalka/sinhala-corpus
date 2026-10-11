# Gemma guarded pilot review — 11 October 2026

## Evidence and scope

The maintainer supplied ten page prediction artifacts in chat and an attached JSON, plus an intermediate run manifest. Run ID: `697ba9cf01eabf96b64433c736ac1679f3dd4d29a8dc100a4ba0a1be56914721`. Model revision: `3e22461f65e89153144f8adb70e3b8c2cc9845a7`. Runtime: Tesla T4, Python 3.13.15, Torch 2.11.0+cu130, Transformers 5.19.0, Accelerate 1.15.0, Pillow 11.3.0; float16, eager attention. Generation used an 8,192-token cap, an exact-token repetition guard and a 120-second soft generation deadline.

These are maintainer-supplied artifacts, not a local rerun. The supplied run manifest says `running`, `completed_pages: 9`, with the tenth page current; the tenth prediction is also supplied. This can be an earlier copied checkpoint. Obtain the final `finished` manifest before calling the run finalized. Keep the original run folder, package lock and repository commit as provenance. Do not replace the run manifest using this review.

## Page outcomes

| Sample | Tokens | Completion status | Page seconds |
| --- | ---: | --- | ---: |
| `LK-EDU-000009_p000001` | 192 | `repetition_loop` | 17.610 |
| `LK-EDU-000009_p000021` | 288 | `repetition_loop` | 22.834 |
| `LK-EDU-000010_p000001` | 284 | `complete` | 23.122 |
| `LK-EDU-000010_p000028` | 721 | `complete` | 58.250 |
| `LK-EDU-000011_p000001` | 544 | `repetition_loop` | 43.980 |
| `LK-EDU-000011_p000004` | 1199 | `complete` | 97.903 |
| `LK-EDU-000012_p000001` | 224 | `complete` | 18.936 |
| `LK-EDU-000013_p000001` | 322 | `complete` | 26.274 |
| `LK-EDU-000014_p000001` | 160 | `repetition_loop` | 13.383 |
| `LK-EDU-000015_p000001` | 342 | `complete` | 27.720 |

Ten page artifacts are available: six terminated normally and four were stopped with `repetition_loop` and `outcome: truncated`. Page durations sum to **350.012 seconds** (about 7.5 minutes). This is the sum of reported page times; it excludes model setup and is not a measured total batch wall time. No time-limit stop is shown in this sample.

The previously unguarded first page took 604.84 seconds and reached 8,192 tokens. The new first-page result stopped after 192 tokens in 17.61 seconds. This demonstrates early stopping on the observed loop, not improved transcription accuracy. A heuristic stop is not an independently verified content-quality label.

## Source-image spot checks

Inspected the local source images matching the packet for `LK-EDU-000012_p000001` and `LK-EDU-000010_p000028`, alongside the supplied outputs. These are engineering spot checks, not independent human reference annotations.

- **Page 12, first page:** the scan visibly defines the vector dot product as `a·b = |a||b| cos θ`. The model writes a fraction containing `1111`. The bottom source identities use squared magnitudes of `a+b` and `a−b`; the output changes them into expressions beginning with `1² ± b²`. Sinhala prose and some source material are also misread or omitted. This page is marked `complete` by generation but is materially inaccurate.
- **Page 10, page 28:** the source is a coordinate-geometry note with internal/external division of a line segment, distance, slope and line-equation sections. The output adds long chains of unrelated fractions and matrices while losing the visible source formulas. Generation ended normally; content does not faithfully match the scan.
- Four other artifacts are interrupted repetition tails. Those outputs are already excluded from scored accuracy by the evaluator. Remaining normally completed pages still require source comparison; this review does not approve them.

`complete` is a generation status, never an accuracy or training-acceptance decision. All ten artifacts correctly retain `review_required: true` and `training_approved: false`. Zero human reference transcripts have been verified, so CER/WER and a model accuracy percentage cannot be reported. Six normal completions out of ten must not be described as 60% accuracy.

## Decision and next work

Do not promote this Gemma full-page configuration to training extraction or run a large batch. Preserve the outputs as experiment evidence. Ask two Sinhala readers to transcribe and independently verify calibration references first, including equations. Use only calibration pages to investigate page-region crops, image presentation and prompt changes; keep the holdout for a later frozen configuration comparison. Include printed Sinhala pages in a separate evaluation packet to distinguish handwriting/layout problems from broader recognition limitations.

A specialist OCR alternative may be tested after reference preparation and compute compatibility checks. DeepSeek remains untested and its current adapter lacks completion evidence, so changing a backend name alone does not establish a usable training extractor. The immediate checkpoint is reference creation and source-fidelity evaluation, not choosing a winner from command completion.
