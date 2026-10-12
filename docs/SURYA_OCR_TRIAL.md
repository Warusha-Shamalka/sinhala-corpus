# Surya OCR trial on the frozen Sinhala packet

Surya is the next candidate after Qwen's supplied one-page trial produced Hindi/Devanagari output from a Sinhala handwritten physics page. That Qwen run completed technically (389 generated tokens, 25.688 seconds), but its text is unsuitable for training. This is a recognition failure on one configuration/sample, not a measured score or proof that all Qwen variants fail Sinhala.

## What is implemented

The adapter pins **surya-ocr 0.17.1**. It uses two public Datalab checkpoints: `text_recognition/2025_09_23` and `text_detection/2025_05_07`. The setup stage downloads them into `/content/surya-models`, hashes every component file and writes `selection.json`. A SHA256 fingerprint of that manifest serves as the model revision; it is not a Hugging Face commit. `model_selection.json` on Drive contains the component IDs/file hashes and fingerprint for reproduction. Code and dependency versions are saved separately.

Inference loads both checkpoints from local paths, verifies all recorded files and rejects added/changed files. Socket access is blocked during model loading and OCR because Surya's S3 loader is not controlled by Hugging Face offline flags. Core pipeline dependencies remain unchanged; heavy libraries are installed only in the isolated Colab environment.

This adapter performs line detection followed by regional recognition using `ocr_with_boxes`, math mode enabled and simple line sorting. It preserves upstream line/word/character boxes, confidence values and text as `raw_result`. It does not load separate layout/table models, correct spellings, translate text or approve training exports. Simple line sorting may misorder columns and tables; inspect those samples explicitly.

Recognition batch size is **4**, detection batch size **1**, and the region cap is **256 tokens**. The 0.17.1 loader selects float16 on T4 when native BF16 is unavailable. The adapter leaves the loader's dtype selection intact and requests eager attention. Actual T4 memory use, runtime and accuracy are pending until the trial is executed.

Sources: [pinned Surya usage/API](https://github.com/datalab-to/surya/tree/v0.17.1), [pinned loader and T4 fallback](https://github.com/datalab-to/surya/blob/v0.17.1/surya/foundation/loader.py), [pinned checkpoint settings](https://github.com/datalab-to/surya/blob/v0.17.1/surya/settings.py). This release is an engineering trial selection, not a reproduction of the exact unidentified Surya version used in the 2025 Sinhala study.

## Run in Colab

1. Commit/push the updated Python modules and notebook on the branch cloned by the notebook (`feat/pdf-extraction` currently).
2. Upload the updated `notebooks/ocr_accuracy_colab.ipynb` into Colab. An already open notebook does not automatically receive laptop changes.
3. Use a **fresh T4 GPU runtime**, not a TPU. Keep the complete existing packet at `My Drive/sinhala-corpus/reviews/ocr/broad_20261011`, including its ignored `images` folder.
4. Leave `BACKEND = 'surya'`, `PACKET_NAME = 'broad_20261011'` and `MAX_PAGES = 1`. Run code cells in order. No Hugging Face token is needed for these public Datalab checkpoint downloads.
5. The first-page trial uses the same handwritten physics image as the supplied Qwen trial (`LK-EDU-000104_p000001`). Open the saved JSON and its source PNG side by side. Check Sinhala spelling, omitted lines, incorrect equations and invented material. A completed run is not proof of accuracy.
6. If it loads and produces useful text, rerun the **model-selection cell** to create a new `RUN` directory. It reuses the verified local checkpoints. Set `MAX_PAGES = 14` and rerun transcription. The existing predictions folder cannot be overwritten.
7. Keep `predictions`, `model_selection.json`, `requirements.lock.txt`, `repository_commit.txt` and `accuracy_report.json` together on Drive. Transcription reads no reference files or review labels. All output remains `review_required: true`, `training_approved: false`.

The notebook creates an isolated **Python 3.12.12** environment with uv and pins Torch 2.7.1 / torchvision 0.22.1 (CUDA 12.6 wheels), Transformers 4.57.6, Pillow 10.4.0 and Surya 0.17.1. This isolates the trial from Colab's preinstalled packages. Other dependencies resolve during setup and their installed versions are recorded by `pip freeze`. These pins are not an assertion that GPU execution has already passed. Python/models/package installation happens during online setup, not inference.

## Completion and limits

The adapter captures regional token outputs from the pinned recognition predictor. Every region must end in EOS or the upstream no-output token to qualify as completed decoding. Missing token evidence yields `completion_unverified`; a region reaching its cap without a terminal token yields `truncated`. Both are excluded from scored accuracy. Empty text is recorded as empty. This check establishes decoding termination only, not correct or exhaustive page recognition.

Upstream token removal for repetitive regions is disabled in this trial so incomplete/repeated output is exposed for review. Regional token limits and a default **120-second page deadline** bound decoding. The deadline is checked between prefill/decode steps and after OCR returns; it cannot interrupt model loading, a long detection call or an in-progress GPU kernel. If it interrupts decoding, the page is saved as failed with the error and is excluded from scoring; unfinished regional text is unavailable, while previously saved page JSONs persist. No hard process watchdog is claimed.

Reference verification follows [OCR_ACCURACY_GUIDE.md](OCR_ACCURACY_GUIDE.md). Reports without verified references show outcomes, not accuracy. Compare subject/style coverage and equations separately; do not promote outputs merely because their confidence is high. All source images and evaluation references remain excluded from training exports.

## Troubleshooting and reproduction

- **Environment or checkpoint folder already exists:** retain completed results and use a fresh runtime if setup was incomplete. For a successful setup, rerunning the model-selection cell reuses verified weights and creates a new run folder.
- **Missing checkpoint / network blocked:** finish the download cell first. Do not enable network during OCR to hide missing artifacts.
- **Out of memory:** preserve the error and runtime information. One page reduces processing work, not weight memory. A smaller recognition batch or different preprocessing is a separate recorded experiment; no runtime success is assumed here.
- **Truncated / timed-out page:** inspect its outcome and source. Increasing limits is not an accuracy fix; record changed settings and retain previous evidence.
- **Recovering weights after runtime deletion:** download the pinned component URLs again and compare every file hash with the saved model selection. If they differ, treat the new snapshot as a different experiment.

The pinned release's code and weights have distinct licenses; record the applicable GPL code and modified AI Pubs Open Rail-M weight terms when sharing the reproducibility bundle. [Release licensing](https://github.com/datalab-to/surya/tree/v0.17.1#commercial-usage).
