# Purpose

This directory is reserved for the extraction stage.

# Contents

- extraction scripts and utilities
- HTML/PDF-to-text conversion logic
- intermediate parsing logic for extracted content

# Produced by

This stage writes structured or text output into `corpus/extracted/`.

# Consumed by

Cleaning, validation, and dataset-generation stages read outputs from here.

# Git policy

Pipeline code stays in Git. Extracted outputs are generated artifacts and should generally remain local unless curated intentionally.
