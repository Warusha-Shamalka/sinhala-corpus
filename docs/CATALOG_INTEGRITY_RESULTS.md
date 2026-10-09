# Catalog integrity implementation — 9 October 2026

Implemented on the existing user-created branch `fix/catalog-intergrity` (spelling preserved). Base commit: `550f7d6`, which includes the merged discovery fixes. No commit, push or merge was performed by this task.

## Behavior

Discovery catalog commits now lock a stable `.documents.csv.lock` sidecar before reading the current catalog, validating it, deduplicating URLs, allocating IDs, and replacing the CSV. Preview IDs supplied by a stale caller are not trusted. `append_catalog` returns only committed rows; normal-mode reporting uses that result. Duplicate URLs within/across batches are skipped without modifying an already-current catalog.

Validation fails before rewriting invalid input. It checks required/duplicate headers, row widths, ID format/uniqueness, normalized URL uniqueness, source provenance, known states/document types, grade ranges, hashes, numeric fields and processed-state artifact metadata. Extension columns and existing records are preserved. Taxonomy consistency, actual artifact existence/content quality and source rights require later stage-specific validation.

`corpus/catalog/pilots.json` records the eight intended pilot IDs/titles as awaiting source URLs. Existing annotated DISCOVERED pilots remain valid; new candidates cannot use this exception to bypass required provenance. The original catalog bytes and all eight IDs remain unchanged. Annotations contain no fabricated source URLs.

## Verification

Command: `python3 -B -m unittest discover -s tests -v`.

Result: all 46 tests passed, including 12 new catalog integrity tests.

The suite now includes stale-preview IDs, idempotent URLs, four independent concurrent processes writing overlapping batches, lock timeout/recovery, malformed catalogs/candidates, extended-column preservation, injected replacement failure, pilot preservation and reporting after a racing writer. All mutations in these tests use temporary catalogs; no network access is needed for catalog verification.

The updated offline review script now reports distinct stale-writer IDs (`LK-EDU-000001`, `LK-EDU-000002`) instead of the former duplicate. Catalog SHA256 remains:

```text
1b2f0e7e32e004810b04dfe4194ab66e1aff9087975836810a525501f39c9055
```

## Scope and limits

The lock is cooperative and POSIX-specific. Uncooperative manual writers can bypass it. The lock sidecar persists and must not be unlinked during active writes. A ten-second default timeout prevents indefinite waits. Atomic replacement protects readers from partial CSV output; raw files and later processing state updates are outside this discovery append API.

Mounted Drive does not inherit a demonstrated multi-writer guarantee from these local filesystem tests. Continue using one persistent-store writer and checkpoint local snapshots. The eight pilots still need independently verified URLs before downloading. No live crawl was repeated: network/filtering code is unchanged, and the integration checks cover catalog reporting and dry-run safety offline.

Next work: distinguish robots failure outcomes and failed runs, bound the discovery queue, persist structured decisions, and audit real-source candidate quality before downloading at scale.
