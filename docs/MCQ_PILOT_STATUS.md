# MCQ pilot status — 2026-10-12

Status: source acquisition and visual layout inspection complete; Surya OCR and
provisional MCQ joining are **not complete**. No human verification or training
approval has been recorded. The user chose a newer exam after the 2011 investigation.

## 2011 investigation

The 27-page question PDF contains Chemistry I (PDF pages 1–10), Chemistry II
(starting at page 11) and an advertisement on page 27. Its first page identifies
August 2011/new syllabus. The 16-page ALapi answer document has a cover and Paper II
explanations on pages 2–16; all those page images were inspected. No Paper I key was
found in it. These files must not be used to attach Paper II answers to Paper I MCQs.

An alternate key from IslandPrep had the identical raw SHA256 to the ALapi file,
so it supplied no additional answer evidence. Sources and immutable raw files are
in `corpus/experiments/chemistry_2011/store/`; production catalog unchanged.

- Question PDF SHA256: `90ef0cc935f410955024329cdd85aa230a61c1eaf1fea9be6fbfda660509dd00`
- Both key copies SHA256: `707222fbd90f6720e6da5ae28192e2e5416359e7e0f0ed3ea75a340f632c2466`
- Native extraction required OCR for all 27 question and 16 key pages.

## Selected replacement: Chemistry 2021 (2022)

[Paper](https://www.alapiedu.com/Category/paper_hub/uploads/1753416960_2021AL%20Chemistry.pdf)
and [marking scheme](https://www.alapiedu.com/Category/marking_hub/uploads/1753427919_New%202021%20Chemistry_Marking.pdf)
were downloaded through the existing bounded, robots-aware downloader. Pilot IDs
`LK-EDU-910001` and `LK-EDU-910002` are local to the isolated store, not master catalog IDs.

- Paper: 26 PDF pages. Page 1 has the Chemistry I header and questions 1–4.
- Key: 36 PDF pages. Page 3 has a five-column Paper I answer table.
- Both display the session as 2021 (2022); do not interpret it as two unrelated exam years.
- Key row 29 permits multiple answers; row 48 has a handwritten correction. Both
  require unresolved handling, not forced single labels.
- Visual observations are assistant inspection notes, not a human-approved match.
- The paper's native layer contains a promotional watermark. Although extraction
  returned `extracted`, that is not usable question text; selected pages require OCR.

Pinned URLs/hashes/page selections are in `configs/pilots/chemistry_2021.json`.
Local raw files, receipts and native extraction are under
`corpus/experiments/chemistry_2021/store/`. These ignored local data folders are not
pushed with Git and have not been uploaded to Drive.

## Required next action: run the two-page OCR notebook

The local NVIDIA driver is unavailable (`nvidia-smi` exits 9), and the local Python
has neither Torch nor Surya installed. A prepared Colab notebook runs the existing
Surya backend on only paper page 1 and key page 3:

1. Push `feat/mcq-answer-matching` after the notebook/config commit. Do not merge
   merely to run this pilot; the notebook clones that feature branch.
2. Open `notebooks/mcq_pilot_colab.ipynb` in Google Colab.
3. Choose **Runtime → Change runtime type → T4 GPU** and use a fresh runtime.
4. Run cells from top to bottom and grant Drive access when Colab requests it.
5. The notebook downloads only these two PDFs, verifies pinned hashes, freezes
   Surya weights, processes two pages and saves results to
   `MyDrive/sinhala-corpus/mcq_pilots/chemistry_2021_v1/`.
6. The last cell downloads `pilot_ocr_handoff.zip`. Return that ZIP for the next
   pipeline step; no Sinhala typing or answer approval is required.

The handoff includes page images, OCR text, raw Surya layout/word geometry, manifests
and completion/quality flags. It cannot be treated as successful transcription merely
because the notebook finished. Model caches stay in temporary `/content`.

After the handoff: validate OCR completion, use question and table-cell geometry to
construct source-backed provisional matches, exclude ambiguity and write a report.
The present strict line matcher cannot directly ingest the full five-column key;
layout normalization must preserve cell/source evidence. This remains work to finish
after the real OCR layout is available. No MCQ training rows have been generated.
