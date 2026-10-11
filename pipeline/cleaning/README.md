# Purpose

This directory contains conservative native-text normalization after extraction.
`native.py` preserves source meaning and flags unsuitable pages for quarantine.
See [the native dataset guide](../../docs/NATIVE_TEXT_DATASET_GUIDE.md).

# Contents

- text normalization utilities
- cleaning scripts for noisy extraction output
- rules for removing malformed or irrelevant content

# Produced by

The cleaning stage writes cleaned records to `corpus/clean/` and rejected records to `corpus/clean/rejected/`.

# Consumed by

Deduplication and quality assessment stages read the cleaned output.

# Git policy

Cleaning code belongs in source control. Generated cleaned artifacts are usually treated as local generated data rather than committed project metadata.
