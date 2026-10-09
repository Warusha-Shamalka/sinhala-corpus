# Purpose

This directory stores the catalog metadata for discovered educational resources.

# Contents

- `documents.csv` is the authoritative metadata table for the corpus.
- `pilots.json` explicitly identifies the eight intended pilot IDs/titles awaiting source URLs. It allows their incomplete DISCOVERED records to remain valid without implying download eligibility.
- New discovery rows should be added here only after verification and candidate filtering.
- Catalog records should describe source documents without duplicating raw files.

# Produced by

The discovery stage writes initial candidates here. Later pipeline stages may update metadata as documents are downloaded, extracted, or validated.

# Consumed by

The downloader and later stages may read the catalog to determine which resources still need retrieval or follow-up processing.

# Git policy

Keep this table in version control because it captures source, discovery status, and project metadata. Do not overwrite it casually or insert fabricated entries.

## Integrity and concurrent discovery

Discovery commits use a local POSIX advisory lock at `.documents.csv.lock`. The lock covers reading/validation, normalized URL deduplication, ID allocation and atomic CSV replacement. Incoming IDs are previews; `append_catalog` returns the actual committed rows and skips URLs already present. Existing IDs and extension columns are preserved. All writers must cooperate with the lock; manual edits bypass it.

The persistent lock sidecar is ignored by Git. Do not unlink it while writers may run, because a new inode would defeat coordination. Lock waits time out after ten seconds by default. Dry runs only read the catalog and do not acquire/create its lock.

Validation rejects malformed CSV rows/headers, duplicate IDs/normalized URLs, invalid statuses/types/URLs, malformed hashes and invalid numeric fields. New discovery candidates require real source URLs, source names and titles; pilot exceptions apply only to the annotated existing IDs/titles. Processed states require raw artifact paths and hashes, but the validator does not verify file existence or content/rights quality.

This locking implementation targets Linux/POSIX local filesystems, including local Colab scratch. It does not establish reliable multi-writer locking on mounted Google Drive; keep one writer there and persist/checkpoint local catalog snapshots as described in the acquisition plan.
