# Purpose

This directory is reserved for the downloader stage of the pipeline.

# Contents

- downloader implementation
- fetch logic for approved source URLs
- download scheduling and retry behavior
- fetch error handling and audit metadata

# Produced by

A future downloader module is expected to live here and write retrieved files into `corpus/raw/`.

# Consumed by

This stage consumes the catalog and source configuration, then feeds files into extraction and OCR operations.

# Git policy

Pipeline code belongs in version control. Downloaded raw files should remain local and not be committed unless intentionally versioned.
