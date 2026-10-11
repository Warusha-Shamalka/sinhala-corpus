# Run OCR on Google Colab

Colab runs Python on a remote machine. Your laptop needs a browser and an internet connection; it does not need to load the model. Google Drive holds persistent inputs and results. `/content` is temporary compute storage and may disappear when the runtime ends.

## First run: Gemma

1. Commit and push the notebook and its Python modules on your current branch. This notebook currently clones `feat/pdf-extraction`; update its `BRANCH` value if the work is subsequently merged elsewhere.
2. Open Google Drive in your browser. Create `sinhala-corpus/reviews/ocr`. Upload the entire local folder `reviews/ocr/pilot_20261011` inside `ocr`. Include `images`, `references`, `manifest.json`, `review.csv`, and `README.md`. The ten images occupy approximately 30 MB; Git deliberately excludes these generated images. Uploading code to GitHub alone does not upload the images.
3. Open [Google Colab](https://colab.research.google.com/). Choose **File → Upload notebook**, then select `notebooks/ocr_accuracy_colab.ipynb` from this repository. Save a copy in Drive if prompted.
4. Choose **Runtime → Change runtime type**, then choose a GPU accelerator. A T4 is a candidate for the smaller Gemma run; memory and compatibility still need checking on the actual runtime. GPU availability is not guaranteed, including on paid plans.
5. Leave `BACKEND = 'gemma'`. Click the triangle beside each code cell, starting at the top. Wait for one cell to finish before running the next. The first cell asks permission to mount your Drive.
6. Follow the notebook's Hugging Face access instructions if the model requires authentication. Store a read token using the Colab Secrets panel, never in code or notebook output.
7. Packages and weights may take several minutes to download. The transcription cell prints `[1/10] ...`, then saves each page's JSON immediately to Drive. Start with `MAX_PAGES = 1` for a small compatibility trial; use a new run folder for the full ten-page run.
8. Inspect the results in `My Drive/sinhala-corpus/ocr-comparison/gemma_<timestamp>/`. Keep `predictions`, `model_selection.json`, `repository_commit.txt`, `requirements.lock.txt`, and `accuracy_report.json` together.
9. When finished, choose **Runtime → Disconnect and delete runtime**. Saved Drive outputs persist. Cached model weights in `/content` will need downloading again in a new runtime.

**Current validation:** notebook JSON/code syntax and orchestration are checked locally with fixtures. Neither neural model has run on a GPU in this project yet. No Sinhala accuracy claim is available. First-run dependency installation resolves packages; the resulting lock file records exact installed versions for reproduction, rather than claiming an already validated fixed neural environment.

## What the notebook does

It mounts Drive, clones this branch, creates an isolated Python environment, validates the source-image packet, resolves a full Hugging Face model commit, downloads that snapshot, and runs transcription using local GPU weights. Model inference is configured with Hugging Face/Transformers offline flags after downloading. This is corpus processing, not the final benchmark inference system.

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
| `nvidia-smi` or CUDA unavailable | Change runtime type to GPU; wait for an available runtime. |
| Model access denied | Check model-page access conditions and the read token in Secrets. |
| Out of memory | Preserve the failure log. Start with one page to diagnose; page count does not reduce model weight memory. Smaller image settings or another GPU require a separate documented experiment. |
| DeepSeek BF16 error | Use a suitable GPU or continue the Gemma pilot; do not buy compute until the requirement is understood. |
| Flash Attention installation fails | Save the installation error and runtime versions; this upstream environment has not been GPU validated here. |
| Existing repository/run directory | Inspect existing results. Use a fresh runtime/new output folder; the runner refuses overwrites. |
| Runtime disconnects | Completed page JSONs already saved on Drive remain. A later run uses a new folder; partial runs are not reported as complete comparisons. |

Sources: [Colab FAQ](https://research.google.com/colaboratory/faq.html), [Gemma E2B model instructions](https://huggingface.co/google/gemma-4-E2B-it), [DeepSeek-OCR-2 upstream setup](https://github.com/deepseek-ai/DeepSeek-OCR-2). Hardware choices are engineering trial targets, not verified Sinhala accuracy findings.
