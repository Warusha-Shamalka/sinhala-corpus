# Development and automated checks

Use Linux/POSIX with Python 3.11–3.14. Windows without a POSIX environment is not supported by the current `fcntl` catalog locking. Python 3.14.7 has been tested locally; other versions are CI targets until their GitHub runs pass.

## Local setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -B scripts/check_offline.py
```

PyYAML 6.0.3 is the only third-party runtime/test dependency. The tests use standard-library `unittest`; pytest is not required. This pins the dependency version, not the entire OS, Python patch version or downloaded wheel hash.

## What GitHub checks

`.github/workflows/checks.yml` runs on pull requests targeting `dev` and `main`, pushes to those branches, and manual workflow dispatch. It uses an Ubuntu matrix for Python 3.11, 3.12, 3.13 and 3.14, installs the pinned dependency, checks package consistency, runs `scripts/check_offline.py`, and checks that tracked files were not modified.

The runner executes the regression suite, then validates every review bundle below `reviews/discovery/`. A bundle must contain both `review.csv` and `manifest.json`. It reuses the existing review validator; candidate columns, row membership and labels are checked. Labeled rows require a reviewer and explanatory notes. Blank labels and unresolved reviews are allowed so the teammate can submit an initial 10-row PR.

Passing CI does **not** certify candidate correctness, completed human review, source rights or permission to download. The report continues to show the review status and unresolved count.

Dependency/action installation needs network access. The check runner blocks socket connection, DNS and datagram-send audit events in its own process and fails if an attempted request was caught elsewhere. This is a regression guard, not OS-level network isolation. Spawned catalog-test workers perform local filesystem operations; the guard is not automatically installed in those workers. No live crawl or document download belongs in CI.

## Reviewing a teammate's PR

1. Confirm the PR targets `dev`.
2. Inspect the CSV diff: only `review_label`, `reviewer`, `review_notes` and `review_evidence` should change.
3. Confirm all CI matrix jobs pass.
4. Read their reasoning and discuss questionable labels in the PR. CI checks structure, not whether a human judgment is correct.
5. Merge the first 10-row review after validation, then continue the remaining rows under the existing issue.

## Troubleshooting

- **Invalid review bundle:** restore accidentally changed candidate columns or missing rows from Git; preserve intentional edits to the four review columns. Do not regenerate the manifest to bypass the validation error.
- **Dependency consistency fails:** use the project virtual environment. An unrelated system/Colab environment can contain missing dependencies from other installed applications.
- **Network attempt detected:** mock the HTTP operation in the test. Run intentional live discovery separately using a bounded dry run.
- **Checks absent:** this workflow must be committed and pushed before GitHub can run it. Repository Actions settings can disable execution. Branch protection is configured separately; adding this file does not make checks mandatory for merging.

Action usage follows the official [checkout](https://github.com/actions/checkout) and [setup-python](https://github.com/actions/setup-python) documentation. The dependency release is listed on [PyPI](https://pypi.org/project/PyYAML/6.0.3/).
