# Purpose

This directory is reserved for OCR-related processing.

# Contents

- OCR pipelines
- image preprocessing logic
- OCR quality controls and text output handling

# Produced by

OCR outputs should be routed to `corpus/extracted/` and logs to `corpus/logs/ocr/`.

# Consumed by

The extraction and cleaning stages may rely on OCR outputs for scanned or image-based source files.

# Git policy

The implementation code belongs in version control. OCR outputs are generated data and are usually kept out of Git.
