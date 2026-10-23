"""Verify relocated raw artifacts, then explicitly repair their saved paths.

Standard-library-only so this can also run after uploading the file to Colab.
The default is a read-only preview. Stop other store writers before --apply.
"""
import argparse
from contextlib import nullcontext
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replace_bytes(path, content):
    fd, temporary = tempfile.mkstemp(prefix='.path-repair-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def repair(catalog, raw_root, doc_ids, *, apply=False):
    catalog, raw_root = Path(catalog).resolve(), Path(raw_root).resolve()
    if not doc_ids or len(set(doc_ids)) != len(doc_ids):
        raise ValueError('Select at least one document, with no duplicate IDs')
    lock_path = catalog.with_name(f'.{catalog.name}.lock')
    # Preview has no filesystem writes. Apply uses the same catalog lock as collection.
    with lock_path.open('a') if apply else nullcontext() as lock:
        if lock is not None: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_catalog = catalog.read_bytes()
        reader = csv.DictReader(io.StringIO(original_catalog.decode('utf-8'), newline=''))
        fields, rows = reader.fieldnames, list(reader)
        required = {'doc_id', 'status', 'sha256', 'local_filename', 'source_url'}
        if not fields or not required <= set(fields) or len(fields) != len(set(fields)):
            raise ValueError('Invalid catalog schema')
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise ValueError('Malformed catalog row')
        if len({row['doc_id'] for row in rows}) != len(rows):
            raise ValueError('Duplicate catalog IDs')
        selected = {row['doc_id']: row for row in rows if row['doc_id'] in doc_ids}
        if set(selected) != set(doc_ids): raise ValueError('Selected document missing from catalog')
        plans, receipt_changes = [], []
        for doc_id in doc_ids:
            row = selected[doc_id]
            sha = row['sha256']
            if not re.fullmatch(r'LK-EDU-\d{6}', doc_id) or not re.fullmatch(r'[0-9a-f]{64}', sha):
                raise ValueError(f'{doc_id}: invalid document identity/hash')
            if row['status'] not in {'DOWNLOADED', 'EXTRACTED'}:
                raise ValueError(f'{doc_id}: expected DOWNLOADED or EXTRACTED status')
            kind = Path(row['local_filename']).suffix.lower().lstrip('.')
            if kind not in {'pdf', 'html', 'png', 'jpg'}: raise ValueError(f'{doc_id}: unsupported format')
            relative = Path(kind) / doc_id / f'{sha}.{kind}'
            artifact = raw_root / relative
            receipt_path = artifact.with_suffix('.json')
            if not artifact.resolve().is_relative_to(raw_root) or not receipt_path.resolve().is_relative_to(raw_root):
                raise ValueError(f'{doc_id}: artifact escapes raw root')
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
            if (receipt.get('schema_version') != 'raw-download-1' or receipt.get('doc_id') != doc_id
                    or receipt.get('sha256') != sha or receipt.get('format', 'pdf') != kind
                    or not row['source_url'] or receipt.get('requested_url') != row['source_url']
                    or receipt.get('artifact_path') != str(relative)
                    or type(receipt.get('bytes')) is not int or receipt['bytes'] < 1
                    or artifact.stat().st_size != receipt['bytes'] or file_hash(artifact) != sha):
                raise ValueError(f'{doc_id}: receipt/source/hash/size verification failed')
            # Match the repository's canonical path convention without importing it.
            repo = Path(__file__).resolve().parents[1]
            in_checkout = (repo / 'pipeline/workflow.py').is_file() and artifact.is_relative_to(repo)
            canonical = str(artifact.relative_to(repo)) if in_checkout else str(artifact)
            plan = {'doc_id': doc_id, 'old_catalog_path': row['local_filename'],
                    'old_receipt_path': receipt.get('local_filename'), 'verified_path': canonical,
                    'catalog_changed': row['local_filename'] != canonical,
                    'receipt_changed': receipt.get('local_filename') != canonical}
            row['local_filename'] = canonical
            if plan['receipt_changed']:
                receipt['local_filename'] = canonical
                receipt_changes.append((receipt_path, receipt_bytes,
                                        (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode()))
            plans.append(plan)
        changed = any(p['catalog_changed'] or p['receipt_changed'] for p in plans)
        report = {'dry_run': not apply, 'changed': changed, 'documents': plans, 'backup': None}
        if apply and changed:
            backup = catalog.parent / 'path_repairs' / uuid4().hex
            backup.mkdir(parents=True)
            (backup / 'documents.csv').write_bytes(original_catalog)
            for path, before, _ in receipt_changes:
                (backup / f'{path.parent.name}_{path.name}').write_bytes(before)
            (backup / 'plan.json').write_text(json.dumps(plans, indent=2) + '\n')
            # Every selected artifact has passed validation before the first replacement.
            for path, _, after in receipt_changes: replace_bytes(path, after)
            stream = io.StringIO(newline='')
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
            replace_bytes(catalog, stream.getvalue().encode('utf-8'))
            report['backup'] = str(backup)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--doc-id', action='append', required=True, dest='doc_ids')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(repair(args.store / 'corpus/catalog/documents.csv', args.store / 'corpus/raw',
                                args.doc_ids, apply=args.apply), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Path repair stopped: {exc}\n')


if __name__ == '__main__': main()
