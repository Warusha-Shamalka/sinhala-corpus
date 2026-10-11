# Purpose

`grouping.py` groups exact and conservative word-shingle near-duplicates for the
reviewed corpus exporter. It rejects duplicate groups crossing dataset splits.
See [the production guide](../../docs/CORPUS_PRODUCTION_GUIDE.md) for thresholds and limits.

This directory is reserved for deduplication logic.

# Contents

- duplicate detection logic
- near-duplicate handling
- hash-based or metadata-based dedupe rules

# Produced by

Deduplication reduces redundant records in the cleaned corpus before quality validation and dataset creation.

# Consumed by

Quality validation and dataset generation stages expect de-duplicated input.

# Git policy

The implementation belongs in version control. Large deduplicated outputs are usually generated locally rather than committed.
