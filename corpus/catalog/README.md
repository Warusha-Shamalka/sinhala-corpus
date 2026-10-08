# Purpose

This directory stores the catalog metadata for discovered educational resources.

# Contents

- `documents.csv` is the authoritative metadata table for the corpus.
- New discovery rows should be added here only after verification and candidate filtering.
- Catalog records should describe source documents without duplicating raw files.

# Produced by

The discovery stage writes initial candidates here. Later pipeline stages may update metadata as documents are downloaded, extracted, or validated.

# Consumed by

The downloader and later stages may read the catalog to determine which resources still need retrieval or follow-up processing.

# Git policy

Keep this table in version control because it captures source, discovery status, and project metadata. Do not overwrite it casually or insert fabricated entries.
