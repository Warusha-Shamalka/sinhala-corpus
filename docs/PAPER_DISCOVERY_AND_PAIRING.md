# Discover textbooks, papers and related marking schemes

You do not need to upload and categorize each document link. Configure websites
and category entry points once in `sources.yaml`. Discovery finds individual
links and assigns types. A separate report proposes paper/scheme relationships
for source review; it never invents answers or approves training data.

## Colab workflow

Update the repository checkout and run the notebook's configuration-update cell
so the new source settings reach `STORE/configs/sources.yaml`. That cell backs up
the previous source config. Keep the Drive-specific `pipeline.yaml`.

The maintained notebook now enables:

```python
DISCOVER_RESOURCES = True
IMPORT_VM_PDFS = False  # No pre-uploaded VM files required for automatic discovery.
DISCOVERY_SOURCE_IDS = ['govdoc', 'alapiedu']
DISCOVERY_MAX_PAGES = 30
RESOURCE_TYPES = ['textbook', 'past_paper', 'marking_scheme']
```

Its new cells discover resources, download a categorized batch, and publish a
pairing packet before processing all available pages/images. Partial or blocked
sites are reported; available verified files can still be processed. Set
`DISCOVER_RESOURCES=False` to use the earlier selected-ID acquisition workflow.
Discovery budgets do not guarantee exhaustive website coverage.

Manual commands, using the existing notebook variables:

```python
# Preview: requests and audit logs, but no catalog changes.
execute('discover', '--config', str(CONFIG), '--source', 'alapiedu',
        '--max-pages', '30', '--max-depth', '3', '--dry-run', '--progress', 'plain')

# Append newly found URLs and automatically assigned types.
execute('discover', '--config', str(CONFIG), '--source', 'alapiedu',
        '--max-pages', '30', '--max-depth', '3', '--progress', 'plain')

# Download a bounded batch from the requested categories.
execute('collect', '--config', str(CONFIG),
        '--document-type', 'textbook', '--document-type', 'past_paper',
        '--document-type', 'marking_scheme', '--progress', 'plain')

# Inspect relationship counts without writing a packet.
execute('pair-papers', '--config', str(CONFIG), '--dry-run')

# Choose a new output directory for each snapshot.
PAIR_REVIEW = STORE / 'corpus/clean/paper_pairs/batch_001'
execute('pair-papers', '--config', str(CONFIG), '--output', str(PAIR_REVIEW))
```

Use `--source govdoc` for the other website. Download batch size remains
`download.max_documents`; rerun collect for further batches or adjust the limit.
For large pairing reports, use `--subject Physics --exam-year 2023`, or explicitly
increase `--max-candidates` from 10,000. Budget failures publish no partial packet.
Then use [complete-store OCR processing](PROCESS_ALL_AVAILABLE.md).

## Discovery implementation

`start_urls` accepts up to 32 additional same-domain entry points. They share the
existing depth, request, queue, page and time budgets. GovDoc's configuration now
covers educational categories instead of only Grade 6 History. AlApiEdu includes
paper/marking hubs, their real Physics subject routes, and the root/`www` resource
hosts. Other subject links are followed from those website entry points.

GovDoc's exact `/view?fid=...&id=...` wrapper maps to the existing canonical
`/downloadFile/<id>` identity; arbitrary `?id=` links do not. Resource link text
retains medium, marking labels and paper parts. AlApiEdu's observed `paper-card`
structure supplies headings even when filenames are opaque. Its known hubs and
single subject filters can identify a direct PDF's category/subject. Generic
global headings and ambiguous cards still do not supply document identity.

A single unambiguous exam year can fill the existing `exam_year` column for new
paper/scheme candidates. File IDs and tracking parameters are not exam years.
Medium remains an unverified hint, and catalog `language` stays blank until
validation. Existing catalog rows are preserved; new discovery does not silently
rewrite older metadata or incorrectly classified entries.

## Pairing and review

Matching groups papers and schemes by subject/year. Known conflicts in exam,
medium, paper number, kind, grade, session, syllabus or issuer exclude a pair.
Required identifiers are exam, subject, year, medium, paper number and kind
(past/model/term). School/model papers also need explicit issuer and session.
More-specific metadata present on only one side remains unresolved.

| Status | Meaning |
| --- | --- |
| `unique_candidate` | One compatible pair with the required explicit identifiers; still pending source review. |
| `needs_metadata` | Subject/year align, but other identifiers are missing. |
| `ambiguous` | Multiple compatible papers or schemes exist; no first match is selected. |
| Unmatched | No compatible counterpart, insufficient basic identity, or conflicting metadata. |

Combined Paper I/II documents and titles such as `2023 (2024)` retain their
ambiguity. Source-wide language is not used to guess a file's medium. Extracting
more identifiers from PDF headers/OCR and resolving missing metadata remain
future work; metadata-only matching does not establish authority or correctness.

Each snapshot contains `proposals.jsonl`, `metadata.jsonl`, `unmatched.jsonl`,
`review.csv`, catalog/subject snapshots and a hash manifest. Copy the pending
review CSV to a working location, inspect both source documents, and record
decisions and source evidence. This initial feature does not consume declarations
to assign question answers or approve training data.

## Live verification and access limits — 23 October 2026

Category pages checked:
[GovDoc papers](https://govdoc.lk/category/past-papers),
[GovDoc textbooks](https://govdoc.lk/category/text-books),
[AlApiEdu paper subjects](https://www.alapiedu.com/Category/paper_hub/PaperSubject?subject=Physics),
[AlApiEdu marking subjects](https://alapiedu.com/Category/marking_hub/MarkingSubject?subject=physics).
They establish site structure, not the correctness of individual files.

Bounded probes fetched eight successful HTML pages from each site. An initial
GovDoc probe found no candidates before its budget, exposing the viewer-wrapper
gap. After its fix, a targeted Physics page yielded two medium-specific paper
links. Further AlApiEdu subject-page checks confirmed direct PDFs and the
`paper-card` structure; View/Download links repeat URLs. The probes did not write
the project catalog or save raw corpus artifacts.

The GovDoc PDF response probe was blocked because
`govdoc.nyc3.digitaloceanspaces.com/robots.txt` returned **HTTP 403**. That block is
preserved. Existing imported PDFs remain usable. A source that blocks automation
may require a permitted manual import or another accessible source.

Offline tests cover category seeds, real listing-card shapes, wrappers, identifier
conflicts, category download selection, ambiguous matches, candidate budgets and
immutable snapshots. Actual marking-scheme authority and question-level answers
still need source review.

Local verification on Python 3.14.4: 304 tests ran successfully, with one optional
Tesseract integration test skipped. Coverage includes a synthetic end-to-end
category-discovery -> catalog -> typed-download -> pairing-packet workflow.
