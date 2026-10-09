# Resource-local discovery evidence

Implemented on `fix/discovery-local-evidence` from the merged `dev` baseline `109bd40`. This is a discovery-only change; no catalog entries, source configurations, document files or teammate review labels are changed.

## Problem and behavior

The parser previously captured up to six preceding page text fragments and subsequent text as link context. This did not respect document boundaries. Meanwhile, a generic “Download” anchor pointing to an opaque URL often lacked sufficient item evidence to identify its subject, grade and type.

The parser now attaches bounded structural evidence to a link only when a completed `tr`, `li`, `article`, `dd`, or explicit resource/card `div` contains one distinct href. Supported generic div classes are `card`, `resource`, `resource-card`, `document`, `material` and `item`. These are layout conventions, not site-specific rules or proof that the item is educational. The ordinary candidate classifier still decides suitability.

Visible scoped text is limited to 500 characters; oversized sections do not provide inferred context. At more than 128 nested elements, structural inference is disabled for the remainder of the page while explicit links remain discoverable. Navigation, header/footer/aside, navigation roles, hidden and aria-hidden sections cannot provide local evidence. Script/style/template content is excluded, including nested templates. Multiple distinct link destinations are ambiguous; a multi-link paper/answer-key card therefore supplies no inferred description in this version.

For generic or empty anchors, an informative anchor `title` attribute takes precedence, then eligible local context, then the URL filename. Informative anchor text is preserved. Global page titles and unstructured div text are not inherited. Sibling rows/cards do not share subjects or grades. Local descriptions cannot promote category, contact/login or other navigation routes to candidates. Metadata still represents inference from link evidence, not verified document contents.

Audit decisions retain `resource_context` and `context_kind`, and applied local evidence is named in `reasons`. Decision rule version is now `discovery-0.3`; the additive decision fields retain schema `discovery-decision-1`. Old review manifests remain unchanged because they describe the historical crawl.

## Offline verification

Run:

```bash
python3 -B scripts/check_offline.py
```

The new test file `tests/test_discovery_local_evidence.py` contains synthetic structural fixtures, not captured source pages. It covers row text before/after anchors; sibling/nested item boundaries; cards and semantic containers; Sinhala descriptions; multiple destinations; global headings; hidden/navigation sections; oversized/unclosed scopes; anchor/title precedence; navigation route protection; nested ignored templates; malformed anchors; filename fallback; and excessive nesting.

All 89 tests passed, including 16 new structural-evidence tests. The previous 13 classification examples and all catalog/retry/review tests remain part of the suite. The teammate's 80-row historical bundle continues to validate with labels unresolved. This is regression verification, not measured real-source precision or recall.

## Bounded live dry run

On 9 October 2026:

```bash
python3 -B -m pipeline.discovery.crawler --source alapiedu --dry-run --max-pages 10 --max-depth 2 --delay 1 --timeout 8 --max-requests 30 --max-seconds 60 --max-retries 1
```

| Observation | Result |
|---|---:|
| HTML pages visited / succeeded | 10 / 10 |
| Unique accepted URLs | 481 |
| Direct document URL candidates | 481 |
| Navigation / listing exclusions | 4 / 26 |
| Requests / retries | 11 / 0 |
| Decision observations | 1,372 |
| Queued pages not visited | 21 |
| Local-evidence rule applications | 0 |
| Accepted URLs added / removed against earlier bounded run | 0 / 0 |

The run returned exit code `1` with `partial` outcome because the page cap left pages pending. The one request error was a robots.txt HTTP 404; the policy was recorded as absent. No HTML pages failed and no responses were truncated. Runtime was 15.75 seconds.

Ignored local artifacts: `corpus/logs/discovery/discovery_20261009T125244Z_dcc936e8_426083.{log,decisions.jsonl,summary.json}`. Compared against `discovery_20261009T084155Z_4dc532a7_100917.decisions.jsonl`.

These visited pages do not exercise the new generic-link behavior; the unchanged URL set demonstrates preservation on this small crawl, not a live recall improvement. The final filename-fallback/depth guards were subsequently covered by the offline suite. No resource documents were downloaded and the catalog is unchanged.

## Remaining work

Complete the independent review issue and capture approved, source-shaped offline fixtures. Add more complex link-to-description associations only with reviewed examples; do not relax the one-destination restriction speculatively. Before adding a later crawl's candidates to the historical review task, create a separate versioned sample and manifest.
