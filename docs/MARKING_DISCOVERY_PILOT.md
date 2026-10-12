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
