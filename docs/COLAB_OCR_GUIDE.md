# Run OCR on Google Colab

This notebook guide covers the frozen OCR comparison packet. For collecting and processing corpus documents with Surya, use [CORPUS_PRODUCTION_GUIDE.md](CORPUS_PRODUCTION_GUIDE.md) and [corpus_pipeline_colab.ipynb](../notebooks/corpus_pipeline_colab.ipynb).

Colab runs Python on a remote machine. Your laptop needs a browser and an internet connection; it does not need to load the model. Google Drive holds persistent inputs and results. `/content` is temporary compute storage and may disappear when the runtime ends.

## Current trial: Surya

1. Commit/push the changed modules and notebook on the branch cloned by the notebook (`feat/pdf-extraction` currently).
2. Keep the complete `reviews/ocr/broad_20261011` folder in Drive at `My Drive/sinhala-corpus/reviews/ocr/broad_20261011`. Include the ignored `images` folder; uploading code to GitHub does not upload page images.
3. Upload the updated local `notebooks/ocr_accuracy_colab.ipynb` into Colab. Select **Runtime → Change runtime type → T4 GPU** and start a fresh runtime.
4. Leave `BACKEND = 'surya'`, `PACKET_NAME = 'broad_20261011'` and `MAX_PAGES = 1`. Run code cells from top to bottom. No Hugging Face token is needed for the Surya checkpoints.
5. Wait for the isolated Python environment, packages and recognition/detection weights to finish downloading. The inference cell reports model loading and `[1/1]` page processing and saves JSON to Drive.
6. Inspect the first source PNG and prediction JSON side by side. If compatible and useful, rerun the model-selection cell to create a new run folder, change `MAX_PAGES = 14`, then run transcription. Existing predictions are preserved.
7. Keep all output/provenance files in `My Drive/sinhala-corpus/ocr-comparison/surya_<timestamp>/`. Disconnect and delete the runtime when finished; Drive results persist.

See [SURYA_OCR_TRIAL.md](SURYA_OCR_TRIAL.md) for dependencies, completion checks and limitations. **184 offline tests passed**, including fixture coverage of the Surya adapter; actual Surya GPU execution and verified-reference Sinhala accuracy remain pending. The supplied Gemma runs and Qwen handwriting failure are earlier execution evidence, not Surya validation.

## What the notebook does

It mounts Drive, clones this branch, creates an isolated Python environment, validates the source-image packet, downloads and fingerprints both local Surya checkpoints (or resolves a full Hugging Face model commit for another backend), and runs transcription using local GPU weights. Model inference is configured with Hugging Face/Transformers offline flags after downloading. This is corpus processing, not the final benchmark inference system.

The runner records model weight hashes, runtime versions, fixed prompt, page/image identities, token limit, timings and failures. It never opens the reference text or review labels during transcription. Predictions remain `review_required: true` and `training_approved: false`. It does not update the production catalog or create a training dataset.

## DeepSeek comparison

Use a separate fresh runtime, change `BACKEND` to `deepseek`, and select a BF16-capable GPU, such as L4/A100. The upstream DeepSeek-OCR-2 implementation uses BF16 and Flash Attention. This adapter rejects a T4 rather than silently changing upstream behavior. Its package setup follows upstream Torch 2.6.0 and Transformers 4.46.3; Flash Attention installation can require a compiler and may fail on a runtime with incompatible Python/CUDA packages. Do not assume it shares Gemma's dependency environment.

The upstream `infer` API returns text but hides generated token counts. DeepSeek results currently carry `completion_unverified` and are excluded from scored accuracy. Completion verification must be implemented and tested before treating its numerical comparison as complete. You can still inspect its transcription against the image.

## Human references and accuracy

A successful run means the model produced output; it does not mean the text is correct. Follow [OCR_ACCURACY_GUIDE.md](OCR_ACCURACY_GUIDE.md) to create independent reference transcriptions. Until references are verified, the report says `pending_references` and accuracy fields are null. An engine confidence score is not measured transcription accuracy.

Do not spend GPU time typing reference transcriptions: human review can happen on your laptop. Never upload hidden benchmark questions. These public source-page references are reserved for OCR evaluation and must remain out of training exports.

## Common problems

| Observation | Action |
| --- | --- |
| Missing manifest/image | Upload the entire review folder, including ignored `images`, to the exact Drive path. |
| `nvidia-smi` missing or CUDA unavailable | Select Runtime → Change runtime type → T4 GPU, save, reconnect and rerun from the Drive-mount cell. A CPU/TPU runtime cannot run the current CUDA notebook. If Colab cannot allocate a GPU, wait for availability; installing the utility alone will not allocate one. |
| Environment creation fails | The setup cell prints the original venv error and tries virtualenv using the same runtime Python. Use the updated cell; if fallback fails too, share its full preceding output. This commonly indicates missing venv/ensurepip support, but the error output is needed to confirm. |
| Download command reports an unterminated string | Update the download cell: `selection_code` must use a raw triple-quoted string (`r"""`). Retry the subprocess block using the existing `RUN` folder so earlier setup and artifacts are preserved. |
| Model access denied | Check model-page access conditions and the read token in Secrets. |
| Out of memory | Preserve the failure log. Start with one page to diagnose; page count does not reduce model weight memory. Smaller image settings or another GPU require a separate documented experiment. |
| DeepSeek BF16 error | Use a suitable GPU or continue the Gemma pilot; do not buy compute until the requirement is understood. |
| Flash Attention installation fails | Save the installation error and runtime versions; this upstream environment has not been GPU validated here. |
| Existing repository/run directory | Inspect existing results. Use a fresh runtime/new output folder; the runner refuses overwrites. |
| Long silence during transcription | Older notebook checkouts print only after a page finishes. Inspect `predictions/run.json` in Drive: `loading` means model setup; `running` means the page-processing loop started. Updated code records `current_sample` and `completed_pages` and prints phase starts. These snapshots are checkpoints, not liveness heartbeats. |
| Runtime disconnects | Completed page JSONs already saved on Drive remain. A later run uses a new folder; partial runs are not reported as complete comparisons. |

Sources: [Colab FAQ](https://research.google.com/colaboratory/faq.html), [Gemma E2B model instructions](https://huggingface.co/google/gemma-4-E2B-it), [DeepSeek-OCR-2 upstream setup](https://github.com/deepseek-ai/DeepSeek-OCR-2). Hardware choices are engineering trial targets, not verified Sinhala accuracy findings.

## Observed Gemma T4 trial and loop protection

The maintainer supplied Colab artifacts on 11 October 2026: Gemma E2B revision `3e22461f65e89153144f8adb70e3b8c2cc9845a7`, Tesla T4, Python 3.13.15, Torch 2.11.0+cu130, Transformers 5.19.0, Accelerate 1.15.0, Pillow 11.3.0, float16/eager attention. The supplied first-page artifact (`LK-EDU-000009_p000001`) generated 8,192 tokens, repeated `[සම්බන්ධ]` 1,358 times, took 604.84 seconds and was correctly marked truncated. The second supplied artifact (`LK-EDU-000010_p000001`) generated 284 tokens in 21.899 seconds and ended normally. These are user-reported GPU execution results; no independent reference accuracy has been measured. They supersede the earlier pending-execution checkpoint for this Gemma configuration only. DeepSeek GPU execution remains pending.

Updated Gemma generation stops on a long, exactly repeated token tail or a default 120-second soft deadline. Raw/partial text is preserved with `completion_status` `repetition_loop` or `time_limit`, outcome `truncated`, and no training approval. The heuristic can flag legitimately repetitive material, which must be reviewed rather than silently repaired. It checks only generated tokens, not source prompt tokens. The deadline is checked between generation steps, excludes loading/preprocessing, and is not a hard process timeout. DeepSeek's upstream text-returning API has neither guard in this adapter.

Push the changed Python module before cloning a fresh Colab checkout. Changes in your laptop repository do not change an already running Colab process. Keep previous run outputs as evidence and choose a new prediction folder for any retry. Use one page for a compatibility trial before all 14 broad-pilot pages.

## Paired Qwen/Gemma broader trial

See [OCR_BROAD_PILOT.md](OCR_BROAD_PILOT.md) for the prepared 14-page packet and coverage gaps. After Qwen's one-page compatibility trial, rerun the model-selection cell to create a fresh run folder, set `MAX_PAGES = 14`, and run the full packet. Then use a fresh T4 runtime with `BACKEND = 'gemma'` on exactly the same images. The earlier maths-only run cannot replace this paired run.

Qwen's local-weight adapter uses float16/eager attention, bounded image pixels and the same repetition/soft deadline protections. This is an engineering trial; actual T4 performance and Sinhala accuracy remain unmeasured. [Official Qwen model card](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct). Predictions can be generated before human references are ready; measured CER/WER requires independent verified references.

## Current next trial: Surya

The notebook now defaults to **Surya**. Use a fresh T4 runtime, the same broad packet and `MAX_PAGES = 1`; see [SURYA_OCR_TRIAL.md](SURYA_OCR_TRIAL.md) for current step-by-step instructions. It uses an isolated Python 3.12.12 environment and pinned dependencies, downloads detector and recognition weights without a Hugging Face token, and verifies all component hashes before offline OCR. Surya GPU execution remains pending. The supplied Qwen handwriting trial produced Hindi output and is retained as failure evidence; the earlier Qwen-first instructions describe the preceding experiment.
