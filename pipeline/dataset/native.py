"""Prepare native PDF pages for review; export only explicitly approved text."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from pipeline.cleaning.native import VERSION, clean, reasons
from pipeline.discovery.crawler import read_catalog, _catalog_lock
from pipeline.extraction.extractor import ExtractionError, verify_bundle

FIELDS = ['record_id', 'text_sha256', 'decision', 'reviewer', 'review_notes',
          'rights_evidence', 'split']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')


def publish(output, files):
    """Commit a complete new directory, never replace an existing packet/release."""
    if output.exists():
        raise ValueError('Output already exists; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Stable file locks are released by the OS even after SIGKILL/runtime loss.
    # The old mkdir lock may remain from a previous version; it is not reused.
    with _catalog_lock(output.with_name(output.name + '.publish'), 0):
        _publish_locked(output, files)


def _publish_locked(output, files):
    temporary = None
    try:
        if output.exists():
            raise ValueError('Output already exists; choose a new directory')
        temporary = Path(tempfile.mkdtemp(prefix='.native-', dir=output.parent))
        for name, content in files.items():
            path = (temporary / name).resolve()
            if not path.is_relative_to(temporary.resolve()):
                raise ValueError('Artifact path escapes output')
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, Path):
                shutil.copyfile(content, path)
            else:
                path.write_bytes(content)
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
        from pipeline.download.downloader import sync_directory
        for directory in sorted((p for p in temporary.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            sync_directory(directory)
        sync_directory(temporary)
        os.rename(temporary, output)
        sync_directory(output.parent)
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def visible_manifests(root):
    """Exclude unpublished staging directories left by abrupt termination."""
    return (path for path in root.rglob('manifest.json')
            if not any(part.startswith('.') for part in path.relative_to(root).parts))


def prepare(extraction_root, catalog_path, output, min_chars=80, min_sinhala_ratio=0.8, dry_run=False):
    if min_chars < 1 or not 0 <= min_sinhala_ratio <= 1:
        raise ValueError('Invalid quality thresholds')
    catalog = {r['doc_id']: r for r in read_catalog(catalog_path)}
    candidates, rejected, seen = [], [], set()
    bundles = []
    for path in sorted(visible_manifests(extraction_root)):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        row = catalog.get(manifest.get('doc_id'))
        if row is None:
            raise ValueError(f'Extraction document missing from catalog: {path}')
        # Validate immutable extraction identity and every output hash first.
        verify_bundle(path.parent, {**row, 'sha256': manifest['raw_sha256']}, manifest['config_hash'])
        bundles.append({'path': str(path.resolve()), 'sha256': digest(path.read_bytes())})
        for line in (path.parent / 'pages.jsonl').read_text(encoding='utf-8').splitlines():
            page = json.loads(line)
            text = clean(page['text'])
            identity = f"{page['doc_id']}:{page['raw_sha256']}:{page['page_number']}"
            if identity in seen:
                raise ValueError('Multiple extraction versions for a page; select one extraction root')
            seen.add(identity)
            rejected_reasons = reasons(page, text, min_chars, min_sinhala_ratio)
            record = {'record_id': identity, 'doc_id': page['doc_id'], 'raw_sha256': page['raw_sha256'],
                      'page_number': page['page_number'], 'text': text, 'text_sha256': digest(text.encode()),
                      'original_text_sha256': digest(page['text'].encode()), 'config_hash': page['config_hash'],
                      'extraction_manifest_sha256': bundles[-1]['sha256'], 'cleaning_version': VERSION,
                      'source_url': row['source_url'], 'title': row['title'], 'source': row['source'],
                      'metadata_hints': {k: row[k] for k in ('subject', 'domain', 'grade', 'language', 'license')},
                      'review_required': True, 'training_approved': False}
            if rejected_reasons:
                rejected.append({**record, 'rejection_reasons': rejected_reasons})
            else:
                candidates.append(record)
    report = {'candidates': len(candidates), 'rejected': len(rejected), 'bundles': len(bundles),
              'rejection_reasons': dict(Counter(r for d in rejected for r in d['rejection_reasons'])),
              'training_approved': False}
    if dry_run:
        return report
    import io
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    for record in candidates:
        writer.writerow({'record_id': record['record_id'], 'text_sha256': record['text_sha256'], 'decision': 'pending'})
    files = {'candidates.jsonl': b''.join(encode(r) for r in candidates),
             'rejected.jsonl': b''.join(encode(r) for r in rejected), 'review.csv': stream.getvalue().encode()}
    manifest = {'schema_version': 'native-review-1', 'cleaning_version': VERSION, 'report': report,
                'thresholds': {'min_chars': min_chars, 'min_sinhala_ratio': min_sinhala_ratio},
                'catalog_sha256': digest(catalog_path.read_bytes()), 'bundles': bundles,
                'output_sha256': {k: digest(v) for k, v in files.items() if k != 'review.csv'}}
    publish(output, {**files, 'manifest.json': encode(manifest)})
    return report


def export(packet, output):
    manifest = json.loads((packet / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'native-review-1':
        raise ValueError('Invalid review manifest')
    hashes = manifest.get('output_sha256', {})
    if set(hashes) != {'candidates.jsonl', 'rejected.jsonl'}:
        raise ValueError('Invalid packet artifact list')
    for name, sha in hashes.items():
        if digest((packet / name).read_bytes()) != sha:
            raise ValueError(f'Packet changed: {name}')
    records = [json.loads(line) for line in (packet / 'candidates.jsonl').read_text(encoding='utf-8').splitlines()]
    with (packet / 'review.csv').open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('Invalid review columns')
        reviews = list(reader)
    by_id = {r['record_id']: r for r in reviews}
    if len(by_id) != len(reviews) or set(by_id) != {r['record_id'] for r in records} or len(records) != len(by_id):
        raise ValueError('Missing, extra or duplicate review IDs')
    groups, unique, approved, duplicates = {}, {}, [], []
    for record in records:
        review = by_id[record['record_id']]
        if record['text_sha256'] != digest(record['text'].encode()) or review['text_sha256'] != record['text_sha256']:
            raise ValueError('Review text identity mismatch')
        if review['decision'] not in {'pending', 'reject', 'approve'}:
            raise ValueError('Invalid review decision')
        if review['decision'] != 'approve':
            continue
        if any(not review[k].strip() for k in ('reviewer', 'review_notes', 'rights_evidence')):
            raise ValueError('Approval requires reviewer, source comparison notes and rights evidence')
        split = review['split']
        if split not in {'train', 'validation', 'test'}:
            raise ValueError('Approved pages require an explicit split')
        raw = record['raw_sha256']
        if raw in groups and groups[raw] != split:
            raise ValueError('A source PDF cannot occur in multiple splits')
        groups[raw] = split
        sha = record['text_sha256']
        if sha in unique:
            if unique[sha]['split'] != split:
                raise ValueError('Duplicate text crosses splits')
            duplicates.append({'record_id': record['record_id'], 'duplicate_of': unique[sha]['record_id']})
            continue
        item = {**record, 'split': split, 'review': review, 'review_required': False, 'training_approved': split == 'train'}
        unique[sha] = item
        approved.append(item)
    if not approved:
        raise ValueError('No approved pages; no dataset was written')
    files = {f'{split}.jsonl': b''.join(encode(r) for r in approved if r['split'] == split)
             for split in ('train', 'validation', 'test')}
    report = {'schema_version': 'native-dataset-1', 'counts': dict(Counter(r['split'] for r in approved)),
              'duplicates': duplicates, 'review_manifest_sha256': digest((packet / 'manifest.json').read_bytes()),
              'review_csv_sha256': digest((packet / 'review.csv').read_bytes()),
              'output_sha256': {k: digest(v) for k, v in files.items()}}
    # Snapshot the review evidence so the release remains auditable after packet edits.
    files['review.csv'] = (packet / 'review.csv').read_bytes()
    files['review_manifest.json'] = (packet / 'manifest.json').read_bytes()
    publish(output, {**files, 'manifest.json': encode(report)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('--extraction-root', type=Path, required=True)
    prepare_parser.add_argument('--catalog', type=Path, required=True)
    prepare_parser.add_argument('--output', type=Path, required=True)
    prepare_parser.add_argument('--min-chars', type=int, default=80)
    prepare_parser.add_argument('--min-sinhala-ratio', type=float, default=0.8)
    prepare_parser.add_argument('--dry-run', action='store_true')
    export_parser = commands.add_parser('export')
    export_parser.add_argument('--packet', type=Path, required=True)
    export_parser.add_argument('--output', type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'prepare':
        args['catalog_path'] = args.pop('catalog')
    try:
        print(json.dumps((prepare if command == 'prepare' else export)(**args), indent=2))
    except (ValueError, OSError, KeyError, ExtractionError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
