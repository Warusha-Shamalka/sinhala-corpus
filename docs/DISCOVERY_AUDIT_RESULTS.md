# Discovery reliability and audit — 9 October 2026

Branch: `feat/discovery-audit`, based on locally recorded `origin/dev` at merge commit `b4d4574`. The catalog and TODO work were already committed and merged there. No commit, push or merge was performed by this task.

## Implemented behavior

- Robots.txt 404/410 is recorded as absent and allows crawling. 401/403 blocks crawling. Network errors, exhausted transient retries, invalid encoding/MIME and oversized policy responses block that origin for the remainder of the run. This is the project's conservative policy; source approval still does not establish content rights.
- Available robots rules are respected, including supported Crawl-delay and Request-rate directives. HTTP 429/500/502/503/504 and network failures use bounded retries. Retry-After seconds/HTTP dates are supported; waits longer than the configured retry-wait budget defer the request rather than shortening the server's instruction.
- Queued URLs are deduplicated. Queue size, page attempts, network requests (including redirect hops/retries), and elapsed time are bounded per source. Queue overflow leaves candidates discoverable but reports incomplete traversal.
- HTML over 2,000,000 bytes and robots over 512,000 bytes are rejected, not silently parsed as complete responses. HTML decoding failures are explicit failures.
- Each run creates a unique ID, a human-readable log, a `*.decisions.jsonl` evidence stream and a `*.summary.json` result under `corpus/logs/discovery/`. Audit files are ignored generated artifacts. Decision records include source, referring/candidate URLs, title, score/reasons, metadata, local evidence, timestamp and run ID; working code also preserves the original href. Repeated links are retained as separate observations.
- Decision writes are flushed while processing; a write failure aborts before a later catalog commit. Normal mode still uses the catalog transaction added previously. Dry runs never modify or lock the catalog.

## Exit codes and interpretation

| Exit code | Meaning |
| --- | --- |
| `0` | At least one source completed successfully; a source with no candidates can be `success_empty` |
| `1` | Useful work exists, but at least one source failed or stopped early (including page/queue/request/time limits) |
| `2` | Run failed, configuration/audit/catalog errors occurred, or no selected source could be processed |

Individual sources distinguish `success`, `success_empty`, `partial`, `failed` and `skipped`. A skipped disabled/unverified source is recorded. A forbidden/disallowed root with no processed HTML is skipped; an unavailable policy is failed. Recovered retries and an absent policy may contribute request-error counts without making a completed source fail. Consult outcomes rather than treating every error count as a terminal failure.

Normal mode may commit independently accepted candidates from partial traversals; exit code 1 and the summary still disclose incompleteness. A budget-limited dry run is expected to return 1 when pages remain queued.

## New options

| Option | Default | Scope |
| --- | --- | --- |
| `--max-queue` | 1000 | Pending URLs per source |
| `--max-requests` | 250 | HTTP attempts, retries and redirect hops per source |
| `--max-seconds` | 300 | Elapsed-time budget per source |
| `--max-retries` | 2 | Retries after an initial failed request |
| `--max-retry-wait` | 30 | Maximum retry wait; longer requested waits defer the request |

Existing source, depth, page, delay, timeout and dry-run options remain available. Numeric budgets must be finite and within allowed ranges. Time is checked between requests, waits, response chunks and link processing; an already-blocking network read can overrun the elapsed budget by its configured socket timeout. This is not an external hard process deadline.

## Verification

```bash
python3 -B -m unittest discover -s tests -v
```

All 63 tests passed: the previous 46 plus 17 new reliability/audit tests. Offline fixtures cover robots status distinctions, cached policy failures, delays/request rates, malformed/oversized responses, retry budgets, Retry-After, charged redirects, queue overflow/deduplication, honest exit codes, audit file linkage, audit-write failure and nonfinite limits. Fake clocks exercise waits without depending on a live rate-limited server.

Bounded live command:

```bash
python3 -B -m pipeline.discovery.crawler --source alapiedu --dry-run --max-pages 10 --max-depth 2 --delay 1 --timeout 8 --max-requests 30 --max-seconds 60 --max-retries 1
```

The sandbox first failed DNS resolution: two robots attempts, zero HTML page attempts, unavailable policy and exit 2. With approved network access the same command reported:

| Measure | Result |
| --- | --- |
| HTML pages attempted/succeeded | 10 / 10 |
| Direct document candidates | 481 |
| Navigation/listing URLs excluded | 4 / 26 |
| Requests/retries | 11 / 0 |
| Robots policy | Absent (HTTP 404) |
| Queue peak / pending at stop | 26 / 21 |
| Queue drops / truncated responses | 0 / 0 |
| Decision observations | 1,372 |
| Outcome / exit code | Partial / 1, stopped at page limit |
| Runtime | 33.72 seconds |

The accepted URL count matches the preceding bounded check. These live counts are not a measured candidate precision audit. No resource bodies were downloaded. The live child began before the additional original-href field was added; its other evidence fields were parsed and verified.

Local artifacts share prefix `discovery_20261009T084155Z_4dc532a7_100917` in `corpus/logs/discovery/`. Every decision's run ID matches the summary; unique accepted URLs total 481. Catalog bytes and eight pilot IDs remain unchanged, with SHA256:

```text
1b2f0e7e32e004810b04dfe4194ab66e1aff9087975836810a525501f39c9055
```

## Next work

Build a stratified, independently sourced annotation sample from these decision records and source-shaped fixtures; measure precision/recall with denominators. Record source approval/rights evidence, improve generic-link local context and extend reviewed aliases. The eight pilot URLs remain missing. Downloader, extraction/OCR and training stages remain unimplemented.
