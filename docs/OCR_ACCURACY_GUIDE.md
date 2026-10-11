# OCR accuracy and training-data acceptance

The corpus pipeline exists to produce accurate source-derived training data. Preserve the source image and every raw transcription. Never repair apparent errors using a model's general knowledge: a fluent Sinhala sentence can still be an invented transcription. Accuracy must be checked against what the source actually says.

## Prepared pilot

`reviews/ocr/pilot_20261011` contains ten real rendered pages from seven downloaded public-source PDFs. All reference files are initially empty and all reviews are pending. No transcription has been human verified. Images are local generated artifacts excluded from Git; transfer the entire folder to Drive for Colab.

Sampling gives each document a first page, then adds middle/end pages in document order. Raw SHA256 groups keep a whole document in either calibration or holdout. This pilot has seven calibration pages and three holdout pages. It is a small source sample, not representative coverage of Sinhala printed books, all subjects or all handwriting styles. Content types remain unknown until reviewed. Add representative printed, mixed-layout, MCQ, table and equation pages in a later packet without changing this frozen packet.

Validate metadata alone after a Git clone:

```bash
python3 -B -m pipeline.quality.ocr_benchmark status reviews/ocr/pilot_20261011 --metadata-only
```

On the machine holding the images, omit `--metadata-only` to check their hashes too.

## Make a reference transcription

1. Open a PNG from `images/` and its matching empty TXT in `references/`, side by side. A Sinhala reader types the visible content into the TXT. Work directly from the image, without looking at model outputs. Keep reading order, spelling, punctuation, numbers, question/option labels and visible watermarks.
2. Use UTF-8 text. Use LaTeX for mathematical expressions consistently: inline `\( ... \)`, display `\[ ... \]`. Preserve signs, powers, fractions, units and subscripts. Preserve table row order with clear separators. Describe no unseen diagram content; record problems in review notes.
3. Write `[UNREADABLE]` for anything you cannot read; do not guess. Leave that reference pending, or mark its row `unreadable`. Such a reference cannot be approved or scored. Report unreadable coverage separately; do not claim the readable subset measures all pages.
4. A different Sinhala reader compares the complete TXT against the image, including every equation, and fixes mistakes. Review the content type (`printed`, `handwritten`, `mixed`) and whether equations are present. Neither person should tune prompts using holdout content.
5. Only after both people have actually completed those checks, record their names and verification using the command below. `--equations yes` declares that equations have also been checked. The tool checks metadata and freezes a reference hash; it cannot independently prove that human review happened.

Example after a real review (replace the example names with the actual reviewers):

```bash
python3 -B -m pipeline.quality.ocr_benchmark approve reviews/ocr/pilot_20261011 \
  --sample-id LK-EDU-000009_p000001 \
  --transcriber 'Actual transcriber name' --verifier 'Actual independent reviewer name' \
  --content-type handwritten --equations yes
```

The tool refuses empty text, identical reviewer names, unknown content classifications and `[UNREADABLE]`. Editing an already verified TXT invalidates its recorded hash. For a correction, change that row back to `pending`, perform the independent check again, then approve again. Commit review metadata and verified references through a review PR. Keep generated source images in persistent storage with the recorded hashes.

## Compare model predictions

Run the notebook in [COLAB_OCR_GUIDE.md](COLAB_OCR_GUIDE.md). Transcription never reads reference text. The fixed prompt prohibits solving, translation, summarization, source correction and invented content. The same frozen packet image hashes must be used for each model; record any future prompt/configuration change as a separate experiment and use calibration pages only for choosing settings.

The evaluator accepts the actual prediction directory containing `run.json`. In Python/Colab, use concrete paths:

```python
import subprocess
subprocess.run([
    PYTHON, '-B', '-m', 'pipeline.quality.ocr_benchmark', 'evaluate', str(PACKET),
    '--predictions', str(gemma_prediction_folder),
    '--predictions', str(deepseek_prediction_folder),
], cwd=ROOT, check=True)
```

`gemma_prediction_folder` and `deepseek_prediction_folder` must be Python variables set to your saved Drive run directories, not literal shell placeholders.

CER is character edit distance divided by reference characters; WER uses whitespace-separated words. NFC normalization and whitespace folding preserve case, punctuation, ZWJ and ZWNJ. These are Unicode-codepoint scores, not Sinhala grapheme scores. Both can exceed 1 for large hallucinations. Scores are aggregated separately for calibration and holdout, with expected/scored page counts. Failed, truncated, empty and completion-unverified outputs are excluded and count as missing coverage. Missing coverage prevents a complete comparison.

The evaluator never automatically chooses a winner or approves training. A measured score from a few pages does not justify bulk export. Also manually count missing lines, hallucinated lines, damaged options, wrong numbers and equation errors. Low text CER does not prove equations or answer labels are correct. DeepSeek completion detection is currently incomplete; see the Colab guide.

## Training acceptance policy

Implemented now: raw/native artifacts are preserved; OCR predictions carry pending review/false training approval; the comparison packet is explicitly `ocr_evaluation`; no training exporter is implemented or invoked. These flags alone are not an implemented repository-wide export enforcement mechanism.

Required before adding an exporter:

- Accept only source-provenanced, reviewed page text with a frozen image/raw hash and an explicit quality decision.
- Exclude hidden benchmark content and OCR-evaluation reference documents, grouping by raw document hash rather than page name alone.
- Quarantine unreadable, truncated, unsupported diagram/table and unresolved equation/option pages. Preserve rejection reasons.
- Preserve original text and corrected text separately, with correction evidence, reviewer and processing/model/prompt versions.
- Keep complete MCQ stems/options together; do not invent answers or use unverified generated answer keys.
- Group duplicate/related documents before dataset splits and document permitted source usage.

Next implementation gate is a reviewed-page acceptance stage and a tested exporter that rejects pending/reserved pages. Do not bulk-process the 132 scanned pages into training files before selecting an OCR configuration using independently verified, representative source samples.

## Broader diagnostic packet

The second packet, `reviews/ocr/broad_20261011`, has 14 pages across six subject groups. See [OCR_BROAD_PILOT.md](OCR_BROAD_PILOT.md) for source/style coverage, gaps, explicit selection and paired Qwen/Gemma trials. Use the same approval/evaluation commands above with this packet path. Model predictions may be generated before references are ready. Reports count all-page prediction outcomes but score only independently verified pages. Subject/style breakdowns describe scored pages only; always inspect sample counts, failed/missing/truncated outcomes and holdout coverage. A run checkpoint marked `running` does not constitute a complete comparison.
