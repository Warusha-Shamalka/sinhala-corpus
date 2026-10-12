"""Snapshot unreviewed corpus text for inspection, never a reviewed training release."""
from collections import Counter
import json
from pathlib import Path

from pipeline.dataset.native import digest, encode, publish
from pipeline.download.downloader import file_hash
from pipeline.processing.pages import verify_page


def export(run_report, output):
    run_report, output = Path(run_report), Path(output)
    input_sha = file_hash(run_report)
    run = json.loads(run_report.read_text(encoding='utf-8'))
    if run.get('schema_version') != 'corpus-batch-run-1' or run.get('active_phase') != 'finished':
        raise ValueError('Provisional export requires a finished batch-run report')
    if not isinstance(run.get('processed_bundles'), list) or not run['processed_bundles']:
        raise ValueError('Batch run contains no processed bundles')
    rows, exclusions, evidence, identities = [], [], [], set()
    for name in sorted(set(run['processed_bundles'])):
        folder = Path(name)
        if output.resolve().is_relative_to(folder.resolve()):
            raise ValueError('Provisional output must be outside source page bundles')
        manifest_sha = file_hash(folder / 'manifest.json')
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        record = verify_page(folder, manifest['identity'])
        identity = record['identity']
        key = (identity['doc_id'], identity['raw_sha256'], identity['page_number'])
        if key in identities:
            raise ValueError('Multiple processing versions of a page; select one batch run')
        identities.add(key)
        sid = f"{identity['doc_id']}_{identity['raw_sha256']}_p{identity['page_number']:06d}"
        evidence.append({'record_id': sid, 'bundle': str(folder.resolve()), 'manifest_sha256': manifest_sha})
        if not record['text'].strip():
            exclusions.append({'record_id': sid, 'reason': 'empty_text', 'quality_flags': record['quality_flags']})
            continue
        rows.append({'schema_version': 'provisional-corpus-text-1', 'record_id': sid,
                     'text': record['text'], 'text_sha256': digest(record['text'].encode('utf-8')),
                     'source_identity': identity, 'source_url': record['source_url'], 'source': record['source'],
                     'metadata_hints': record['metadata_hints'], 'method': record['method'],
                     'ocr_backend': record.get('ocr_backend'), 'model_id': record.get('model_id'),
                     'model_revision': record.get('model_revision'), 'runtime': record.get('runtime'),
                     'quality_flags': record['quality_flags'],
                     'prediction_outcome': record.get('prediction', {}).get('outcome'),
                     'completion_status': record.get('prediction', {}).get('completion_status'),
                     'source_record_sha256': file_hash(folder / 'page.json'),
                     'review_required': True, 'training_approved': False})
        if file_hash(folder / 'manifest.json') != manifest_sha:
            raise ValueError('Source bundle changed during provisional export')
    if not rows: raise ValueError('No nonempty provisional text; nothing was exported')
    for entry in evidence:
        folder = Path(entry['bundle'])
        if file_hash(folder / 'manifest.json') != entry['manifest_sha256']:
            raise ValueError('Source bundle changed during provisional export')
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        verify_page(folder, manifest['identity'])
    if file_hash(run_report) != input_sha: raise ValueError('Batch report changed during provisional export')
    files = {'provisional_text.jsonl': b''.join(encode(row) for row in rows),
             'source_bundles.jsonl': b''.join(encode(row) for row in evidence),
             'excluded.jsonl': b''.join(encode(row) for row in exclusions)}
    manifest = {'schema_version': 'provisional-corpus-1', 'pages': len(rows),
                'empty_pages_excluded': len(exclusions), 'training_approved': False,
                'review_required': True, 'batch_report_sha256': input_sha,
                'export_code_sha256': file_hash(Path(__file__)),
                'methods': dict(Counter(row['method'] for row in rows)),
                'quality_flags': dict(Counter(flag for row in rows for flag in set(row['quality_flags']))),
                'output_sha256': {name: digest(data) for name, data in files.items()},
                'accuracy_note': 'Unreviewed extraction only; no accuracy percentage, approval, deduplication or train/evaluation split is certified.'}
    publish(output, {**files, 'manifest.json': encode(manifest)})
    return {'output': str(output), **manifest}
