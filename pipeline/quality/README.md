# Purpose

`discovery_review.py` implements offline sampling and reporting for independent discovery-candidate review. Other corpus content-quality validation remains planned. See [DISCOVERY_REVIEW_GUIDE.md](../../docs/DISCOVERY_REVIEW_GUIDE.md) for commands, labeling rules and statistical limits.

This directory is reserved for quality-assessment workflows.

# Contents

- validation scripts
- content-quality checks
- scoring and issue classification logic

# Produced by

The quality stage should produce quality flags, rejection records, and final validated data.

# Consumed by

Dataset-generation and reporting workflows use the quality checks and scores.

# Git policy

Code belongs in source control. Quality outputs are generated artifacts and should generally remain local unless intentionally archived.
