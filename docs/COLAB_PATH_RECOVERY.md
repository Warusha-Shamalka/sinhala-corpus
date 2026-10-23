# Recover a moved VM/Drive raw-file path

Use this when `collect` fails with `Catalog and raw artifact path disagree` or
`Receipt and raw artifact path disagree` after raw files were moved to Drive.

The validator found a stored path that disagrees with the current raw root. In
the affected VM importer, an existing matching SHA256 caused the catalog update
to be skipped. The raw file may be intact. `requests=0` means the failure occurred
during local verification; re-downloading is unnecessary when hashes match.

## Repair the existing store

Stop other store writers. Use the corrected branch checkout, or upload the
standalone [repair script](../scripts/repair_store_paths.py) to `/content` in the
current Colab session. It uses only Python's standard library and works without
restarting the runtime or downloading model weights.

If the script was uploaded directly, run this cell **before the actual collect
cell**:

```python
from pathlib import Path
import subprocess, sys

STORE = Path('/content/drive/MyDrive/sinhala-corpus/production_02')
DOC_IDS = [f'LK-EDU-{n:06d}' for n in range(1501, 1506)]
repair_script = Path('/content/repair_store_paths.py')
args = [sys.executable, str(repair_script), '--store', str(STORE),
        *[part for doc in DOC_IDS for part in ['--doc-id', doc]]]
subprocess.run(args, check=True)              # Read-only preview/verification
subprocess.run([*args, '--apply'], check=True) # Backup and update verified paths
```

For a corrected repository checkout, set
`repair_script = ROOT / 'scripts/repair_store_paths.py'` instead. The canonical
notebook includes this step as the **verified-store-path-repair** cell immediately
before download preview. It also runs a repair after VM import.

For each selected document the script verifies catalog identity, receipt identity,
requested source URL, relative artifact path, byte count, and the complete file
SHA256. It stops before replacements if any selected file is invalid or missing.
It updates only `local_filename` fields in the catalog and receipts. Original raw
bytes, source URLs, IDs, statuses and content hashes are retained.

Expected result: `dry_run: false`, document entries showing `verified_path`, and a
backup directory under `corpus/catalog/path_repairs/`. A second run should report
`changed: false`. If verification fails, inspect the named missing/corrupt file;
restore its exact matching original and receipt before retrying.

## Correct the document limit

`batch_limit` is a separate configuration result. The older configure cell sets
both limits to 1. After the old configuration cell, run:

```python
limit_code = """
import sys, yaml
from pathlib import Path
path = Path(sys.argv[1])
config = yaml.safe_load(path.read_text())
config['download']['max_documents'] = int(sys.argv[2])
config['processing']['max_documents'] = int(sys.argv[2])
path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
"""
subprocess.run([PYTHON, '-c', limit_code, str(CONFIG), str(len(DOC_IDS))], check=True)
```

This passes the selected document count into the isolated Python environment.
Do not rerun the old configuration cell afterward, since it resets the limits.
The corrected notebook includes this change directly. Then rerun:

```python
download_report = execute('collect', '--config', str(CONFIG),
                          *selection_args(), '--progress', 'plain')
```

Intact imported documents should return `verified_existing` with no download
requests. Continue to the processing cell afterward. The corrected VM importer
updates the matching row's local path, preventing the same stale-path condition
on future imports.

## Recovery evidence and rollback

The repair prints its unique backup directory. It contains the pre-repair
`documents.csv`, a plan, and copies of any receipts that needed changes. With
writers stopped, those specific files can be restored to their original locations
if a repair must be undone. Do not restore an old catalog after newer acquisition
writes without reconciling those changes. Receipt and catalog replacements are
atomic individually; a runtime interruption between replacements can be recovered
by rerunning the same verified repair.
