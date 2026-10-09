# Offline review results

Date: 8 October 2026. Reviewed application revision: `373ce62`. Review branch: `docs/sinhalammlu-pipeline-review`. The commands below ran locally; no source crawl, download, training, or test-set inspection was performed.

## Existing tests

Command: `python3 -m unittest discover -s tests -v`.

Result: 19 tests passed. No new regression tests were added in this documentation-first change. The evidence script is an observational audit, not a passing test that encodes broken behavior.

For future runs use `python3 -B -m unittest discover -s tests -v` to avoid altering tracked bytecode; removing tracked caches is a separate maintenance task.

## Edge-case probes

Command: `python3 -B docs/evidence/reproduce_review.py`.

| Probe | Observed result |
| --- | --- |
| `History of Sri Lanka` | Subject/domain empty because of overlapping configured names |
| `Sinhala Language and Literature` | Subject/domain empty because of overlapping configured names |
| `ඉතිහාසය` | Subject/domain empty |
| `8 ශ්‍රේණිය ඉතිහාසය` | Subject and grade empty |
| `Grade 8-9 History` | History recognized, range reduced to grade 8 |
| Malformed IPv6-style URL | `ValueError: Invalid IPv6 URL` |
| Same-host FTP PDF | Normalized and accepted as a candidate |
| Script followed by download anchor | Script text enters link context |
| Generic `/download` under an educational page title | Rejected; page title is unused |
| English-labeled PDF under Sinhala source | Accepted and labeled `si` from source hint |
| Two ID batches using one stale snapshot | Both appended with `LK-EDU-000001` |
| Current catalog | Eight rows; eight missing URLs and eight missing licenses |

The temporary-catalog probe leaves the real catalog unchanged. Future fixes should change these outcomes deliberately and add meaningful regression tests in `tests/`.

## Artifact/document verification

Both YAML templates parsed successfully and declare `TEMPLATE_INCOMPLETE`. Local Markdown links resolved. `git diff --check` passed. Existing discovery source/config/catalog files were preserved. Catalog SHA256 at review:

```text
1b2f0e7e32e004810b04dfe4194ab66e1aff9087975836810a525501f39c9055
```

The original shared conversation was inaccessible through browsing; the supplied handover text was incorporated instead. ACL Anthology was consulted only for paper citation metadata, not benchmark question files. Historical completed crawl counts are described in the current-state review and are not new verification results.
