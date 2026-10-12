# Public marking-scheme discovery pilot

Date: 2026-10-12. This is a discovery/metadata trial, not a verified answered-MCQ release.

## What changed

The approved ALapi source now starts at its [public marking listing](https://www.alapiedu.com/Category/marking_hub/MarkingSubject).
Some homepage links use the bare host while the configured source uses `www`;
strict host restrictions remain unchanged. An explicit same-host seed reaches the
listing without broadening source permissions or consuming the budget on navigation.

Resource headings in `paper-card` containers now accompany generic View/Download
anchors. This improves classification of abbreviated PDF filenames without borrowing
text from neighboring cards. Answer-key and Sinhala marking labels are recognized.
Pair-index subject and medium hints remain unverified, and conflicting hints are blank.

## Results and reproducible command

```bash
python3 -B -m pipeline.discovery.crawler --source alapiedu \
  --max-pages 1 --max-depth 0 --max-requests 5 --max-seconds 50 \
  --timeout 12 --max-retries 0 --delay 1 --dry-run \
  --log-root /tmp/sinhala-marking-discovery-logs --quiet --json
```

The live trial visited one listing and found 543 unique candidates. It returned
exit code 1 / partial because the one-page budget left the home seed unvisited.
There were two requests, zero retries and one logged robots error (robots.txt was
absent). This is not a claim of complete source coverage. Listing/navigation pages
were excluded from catalog candidates. Dry-run changed no catalog and fetched no PDFs.

On the same saved HTML, resource-card context changed classifications from
56 marking schemes, 7 past papers and 480 other candidates to 212 marking schemes,
37 past papers and 294 other candidates. Counts describe heuristic classifications;
site labels such as “official” have not been independently checked.

An isolated catalog copy received only the 212 marking-scheme candidates. Its
pairing index contained 87 existing paper entries and 212 key entries, with zero
suggested pairs and 299 unresolved entries. Of the papers, 83 lacked a subject,
72 lacked an exam hint and 85 lacked a language hint. Do not fill these by guessing.

Local temporary evidence (not committed and not persistent storage):

- `/tmp/sinhala-marking-discovery-report.json`: live CLI result.
- `/tmp/sinhala-marking-discovery-logs/`: decisions, progress and summary.
- `/tmp/marking-pair-review-n14_cwmb/index/documents.csv`: editable isolated index.
- `/tmp/marking-pair-review-n14_cwmb/suggestions/`: unresolved/pair reports.

## Validation and next steps

Five new offline tests cover seed validation/priority, local card context,
marking labels and pairing metadata conflicts/normalization. Full suite: 301 tests,
300 passed and one Tesseract-dependent test skipped.

Next, collect compatible public question-paper counterparts and inspect original
headers for exam, subject, year, medium, paper part and edition. Download/process
one bounded pair, verify the pairing, then select question/key source regions using
[the answer matching guide](MCQ_ANSWER_MATCHING_GUIDE.md). Missing answers remain
unresolved. Pesuru source identification and compilation-origin mapping remain TODOs.
No benchmark test data is needed for any of these steps.

## User inspection notes

The user inspected two candidates after the pilot:

- Temporary ID `LK-EDU-000490`, filename `1788109345_2026 biology mcq answers .pdf`: answers only. Keep as a key; find the corresponding question paper.
- Temporary ID `LK-EDU-000586`, filename `1753420693_2011 Chemistry_Marking.pdf`: correct answers with explanations. Full question stems and choices have not been confirmed, so keep as a key until inspected further.

These are user-reported observations, not independently verified extraction or answer approval. IDs belong to the isolated review catalog.

This pilot selected only `--source alapiedu`; its CSV does not represent all configured sources. `e_thaksalawa` and `nie` are also enabled and crawl-approved in `configs/sources.yaml`, but were not included in this marking-scheme trial. MathsAPI and Pesuru are not active source entries in the current configuration.

## Metadata enrichment and a cross-source lead

The title/filename enrichment trial processed 299 existing review-index records,
flagged three conflicting fields and still yielded zero compatible pairs. No
first-page bundles were supplied in that run. Synthetic offline tests separately
exercise verified first-page evidence, incomplete OCR and corrupt-artifact rejection.

A public [2011 Chemistry Sinhala paper listing](https://pastpapers.wiki/2011-a-l-chemistry-past-paper-sinhala-medium/)
links to [a 27-page PDF](https://pastpapers.wiki/download/7820/gce-a-l/29462/2011-ppr-3.pdf).
The listing identifies AL/Chemistry/2011/Sinhala; the PDF's complete identity has not
been verified. This source was researched as a single pilot lead, not enabled for
bulk crawling. Another Examlanka listing was inspected but its paper download link
returned 404. The web tool could not fetch the supplied ALapi Chemistry marking PDF.

Adding the paper listing as an unverified isolated candidate produced **one suggestion**:

- Paper: temporary `PILOT-CHEMISTRY-2011-PAPER` from the linked listing.
- Key: temporary `LK-EDU-000586`, the user-inspected ALapi marking scheme.
- Matching hints: AL, Chemistry, 2011.
- Missing on one or both sides: paper number, medium and variant.
- Metadata and pairing remain unverified; no answers were assigned.

Temporary local output: `/tmp/chemistry-2011-enriched/` and
`/tmp/chemistry-2011-suggestions/`. These are not production catalog entries or
persistent Drive artifacts. No production data was modified. Next inspect both
original headers, obtain processing bundles and confirm part/medium/edition before
configuring question/key regions. The downloadable PDF lead is not proof that all
its questions correspond to the key.

Later source inspection supersedes the preliminary 2011 MCQ suggestion: the ALapi
key contains Paper II explanations, with no Paper I key found. The user chose a
2021 (2022) replacement pilot. See [MCQ_PILOT_STATUS.md](MCQ_PILOT_STATUS.md).
