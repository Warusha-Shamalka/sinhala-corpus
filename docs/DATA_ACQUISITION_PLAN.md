# Data acquisition and coverage plan

This plan extends the existing corpus architecture. Discovery remains its own stage; do not start bulk downloading until candidate filtering has been evaluated. Proposed sources below are collection candidates, not verified availability, rights, or academic-quality claims.

## Existing sources and proposed additions

| Source | Current repository state | Recommended first work |
| --- | --- | --- |
| e-Thaksalawa | Enabled and crawl-approved at `https://e-thaksalawa.moe.gov.lk/lcms/` | Capture a small source-shaped HTML fixture; inspect course/resource navigation and approved document hosts |
| NIE | Enabled and crawl-approved at `https://www.nie.ac.lk/` | Verify reachable resource routes and source rights; capture curriculum/teacher-guide fixtures |
| AlApiEdu | Enabled and crawl-approved at `https://www.alapiedu.com/` | Annotate samples from a bounded dry run; measure listing/resource discrimination |
| MathsAPI | Named in supplied handover at `https://www.mathsapi.com/`; not configured | Add only after explicit crawl approval and source review; initially disabled/unverified |
| Other official education/examination publishers | Not configured | Verify canonical publisher endpoints and permissions before adding sources |
| Independent open educational text/MCQ releases | Not configured | Screen benchmark contamination, licensing, Sinhala relevance, and label quality |

`verified` remains the source approval switch. It must not stand in for language detection, document validation, license approval, or correctness of an answer key. Preserve configurable sources; add source adapters only where generic HTML parsing cannot express a resource relationship.

## Pilot before scale

Use the existing eight intended pilot IDs: Grade 6/7/10 History, O/L History paper, Grade 10 Sinhala, Grade 11 Business, A/L Economics, and A/L Political Science. Obtain real publisher URLs and record the evidence without changing their identity. No URL may be synthesized from the title.

Once discovery passes its gate, process these pilots first. Extend the pilot with one marking scheme, one scanned page/document, one born-digital PDF, one HTML lesson, and one deliberately unsuitable resource to exercise rejection. These are proposed fixture categories; they are not claimed to exist in the current corpus. Keep copyright-sensitive fixtures local or use minimal licensed/synthetic fixtures in Git.

For each source, record approval, observed robots policy, access time, redirects, resource hosts, contact/usage terms if stated, license evidence and language hints. Do not assume government hosting implies an open redistribution license. Unknown rights remain explicitly unknown; a release decision needs recorded evidence.

## Coverage priorities

Prioritise useful verified material over raw URL counts:

1. Question papers with matching authoritative answer/marking schemes, for supervised MCQs.
2. Sinhala textbooks, teacher guides, and syllabus-aligned explanations, for knowledge adaptation and grounded synthetic exercises.
3. Independently licensed Sinhala MCQ collections with credible answer evidence.
4. Broader explanatory content for under-covered subjects after core sources are reliable.

These are priorities, not permission to merge document types or label textbook prose as answered questions. Explanatory corpus text and supervised MCQs become different derived datasets.

Maintain coverage tables by source, subject, grade/level, document type, observed language, and usable content count. Separately report verified MCQs with answers by subject and provenance. A subject with many PDFs may still have zero useful labeled questions.

The handover's subject list distinguishes benchmark subjects from broader project additions such as `Sinhala` and `Business Studies`. Keep all project labels but add an explicit benchmark mapping validated against paper/organiser metadata. Never merge Eastern Music with Oriental Music, Dancing with Dancing Indigenous, Buddhism with Buddhist Civilization, or Christianity with Catholicism. Existing grade ranges are collection targets, not proof of a complete curriculum mapping.

Difficulty is a property of questions supplied by the organiser or measured/labeled under a documented training-data process. Do not assign Easy/Medium/Hard from grade alone. Synthetic difficulty predictions remain unverified metadata until checked.

## Discovery validation protocol

- Store the dry-run summary and versioned decision records locally. A dry run may write logs but must leave the catalog byte-identical.
- Keep hubs crawlable; reject them as resource records unless there is strong evidence of an individual document.
- Manually annotate an independently sourced sample of accepted and rejected candidates, stratified by source, document extension, language, and score band. Do not use test questions. Human training-data review is separate from fully automatic inference.
- Use a fixed source-shaped fixture corpus for before/after comparison so site changes do not masquerade as filtering improvements.
- Report candidate precision on accepted samples and missed-resource rate/recall within the labeled fixture set. Global site recall is unknown without a complete inventory.
- Proposed initial gate: at least 95% accepted-candidate precision on a reviewed sample, no obvious navigation candidates, and at least 90% recall on fixture resources. Record sample size and uncertainty; revise targets deliberately if the pilot shows they are unsuitable.
- Preserve known PDF/past-paper/teacher-guide/notes/marking-scheme discoveries. A lower candidate count alone is not proof of improvement.

The supplied older handover reports 1,465 candidates from 61 pages. The latest completed tracked run reports 1,406, and the existing tests already reject several named hubs. New runs must record exact versions and sample decisions rather than compare counts across different site content or claim the full filtering task is still unimplemented.

## Persistent storage and recovery

Google Drive is the intended persistent data store; Colab is compute and temporary scratch space. No Drive connection or Colab setup is performed in this documentation work.

Store immutable raw artifacts, catalog snapshots, stage manifests, accepted/rejected outputs, and release hashes in Drive. Use Colab scratch for downloads/extraction, then verify checksums when copying completed artifacts to persistent storage. Never mark a document downloaded merely because a file exists in ephemeral Colab storage.

Use one catalog writer at a time. Stage CSV replacements locally under a lock, verify them, and checkpoint to Drive with a run ID. Do not assume Drive-mounted filesystem operations provide the same locking/atomicity as a local filesystem, or that a local SQLite database is safe for concurrent writers through Drive. Keep the existing CSV until a measured need justifies a storage migration.

To recover: fetch a catalog snapshot and stage manifests, verify immutable hashes, identify incomplete tasks, and resume only missing/failed work. Releasing data publicly is a separate decision constrained by source rights and competition secrecy.
