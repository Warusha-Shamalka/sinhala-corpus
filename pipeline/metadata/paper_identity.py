"""Conservative paper identity hints with frozen, inspectable source evidence."""
import csv
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import yaml

from pipeline.dataset import pair_index
from pipeline.dataset.native import digest, encode, publish
from pipeline.discovery.filters import extract_medium_hint, subject_matches
from pipeline.download.downloader import file_hash
from pipeline.processing.pages import verify_page

FIELDS = ('exam', 'subject', 'year', 'paper_number', 'language', 'variant')
ROMAN = {'I': '1', 'II': '2', 'III': '3'}


def hints(text, subjects):
    """Return sets, keeping ambiguity instead of choosing a plausible value."""
    text = re.sub(r'[_-]+', ' ', text)
    result = {f: set() for f in FIELDS}
    for exam, pattern in [('AL', r'\ba\s*[/ .]?\s*l\b|advanced\s+level|උසස්\s*පෙළ'),
                          ('OL', r'\bo\s*[/ .]?\s*l\b|ordinary\s+level|සාමාන්‍ය\s*පෙළ')]:
        if re.search(pattern, text, re.I): result['exam'].add(exam)
    subject, _ = subject_matches(text, subjects)
    if subject: result['subject'].add(subject)
    medium = extract_medium_hint(text, subjects)
    if medium: result['language'].add(medium)
    # These dates are not evidence for the exam year.
    if not re.search(r'upload|publish|copyright|©|printed|downloaded', text, re.I):
        result['year'].update(re.findall(r'\b(?:19|20)[0-9]{2}\b', text))
    for part in re.findall(r'\b(?:paper|part)\s*[: ]*\s*(III|II|I|[123AB])\b', text, re.I):
        result['paper_number'].add(ROMAN.get(part.upper(), part.upper()))
    for variant, pattern in [('model', r'\bmodel\s+(?:paper|exam)|ආදර්ශ'),
                             ('resit', r'\bre\s*sit\b'),
                             ('term', r'\bterm\s*(?:test|exam|paper)|වාර\s*විභාග'),
                             ('official', r'\bofficial\b')]:
        if re.search(pattern, text, re.I): result['variant'].add(variant)
    return result


def enrich(index, output, *, page_bundles=(), subjects_path=None, header_lines=40):
    index, output = Path(index), Path(output)
    if type(header_lines) is not int or not 1 <= header_lines <= 100:
        raise ValueError('header_lines must be 1–100')
    subjects_path = Path(subjects_path or Path(__file__).resolve().parents[2] / 'configs/subjects.yaml')
    checks = [(index, file_hash(index)), (subjects_path, file_hash(subjects_path))]
    subjects = yaml.safe_load(subjects_path.read_text(encoding='utf-8'))
    original = index.read_bytes()
    reader = csv.DictReader(io.StringIO(original.decode('utf-8')))
    if set(reader.fieldnames or []) != set(pair_index.FIELDS): raise ValueError('Unexpected pairing index columns')
    rows = list(reader)
    if any(not r['doc_id'] for r in rows) or len({r['doc_id'] for r in rows}) != len(rows):
        raise ValueError('Missing or duplicate document ID')
    by_id = {r['doc_id']: r for r in rows}
    headers, receipts = {}, []
    for folder in map(Path, page_bundles):
        sha = file_hash(folder / 'manifest.json')
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        page = verify_page(folder, manifest['identity'])
        identity = page['identity']; sid = identity['doc_id']
        if sid not in by_id or identity['page_number'] != 1:
            raise ValueError('Header evidence must be page 1 of an indexed document')
        if sid in headers: raise ValueError('Duplicate first-page evidence')
        if by_id[sid]['raw_sha256'] and by_id[sid]['raw_sha256'] != identity['raw_sha256']:
            raise ValueError('Header raw hash does not match indexed document')
        if page['source_url'] != by_id[sid]['source_url']:
            raise ValueError('Header URL does not match indexed source')
        if page.get('method') == 'ocr' and (page.get('prediction', {}).get('outcome') != 'predicted' or
                                          page.get('prediction', {}).get('completion_status') != 'complete'):
            raise ValueError('Incomplete OCR cannot supply header hints')
        headers[sid] = page
        by_id[sid]['raw_sha256'] = identity['raw_sha256']
        receipts.append({'doc_id': sid, 'manifest_sha256': sha, 'identity': identity,
                         'quality_flags': page.get('quality_flags', []), 'method': page.get('method')})
        checks.append((folder / 'manifest.json', sha))
    reports = []
    for row in rows:
        evidence = {f: [] for f in FIELDS}
        for f in FIELDS:
            if row[f]: evidence[f].append({'value': row[f], 'origin': 'input_index', 'text': row[f]})
        inputs = [('title', row['title'], None),
                  ('filename', unquote(urlsplit(row['source_url']).path.rsplit('/', 1)[-1]), None)]
        page = headers.get(row['doc_id'])
        if page:
            inputs.extend(('header', line, n) for n, line in enumerate(page['text'].splitlines()[:header_lines], 1))
        for origin, text, line in inputs:
            for f, values in hints(text, subjects).items():
                for value in sorted(values):
                    item = {'value': value, 'origin': origin, 'text': text}
                    if line is not None:
                        item.update(page_number=1, line=line, raw_sha256=page['identity']['raw_sha256'],
                                    text_sha256=digest(page['text'].encode()))
                    evidence[f].append(item)
        fields = {}
        for f in FIELDS:
            values = {pair_index.canonical(e['value']): e['value'] for e in evidence[f]}
            status = 'conflict' if len(values) > 1 else 'hint' if values else 'missing'
            row[f] = next(iter(values.values())) if len(values) == 1 else ''
            fields[f] = {'status': status, 'value': row[f], 'evidence': evidence[f]}
        # Compilation identity is distinct from a single original exam.
        if row['collection_id']:
            row['year'] = ''; fields['year'].update(status='compilation_requires_review', value='')
        row.update(metadata_status='unverified', reviewer='')
        row['notes'] += ' Enriched hints only; see metadata_evidence.jsonl. Check original identity and edition.'
        reports.append({'doc_id': row['doc_id'], 'fields': fields, 'review_required': True,
                        'training_approved': False, 'header_used': bool(page)})
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=pair_index.FIELDS)
    writer.writeheader(); writer.writerows(rows)
    for path, sha in checks:
        if file_hash(path) != sha: raise ValueError('Metadata input changed during enrichment')
    for folder in map(Path, page_bundles):
        manifest = json.loads((folder / 'manifest.json').read_text()); verify_page(folder, manifest['identity'])
    files = {'documents.csv': stream.getvalue().encode(), 'input_documents.csv': original,
             'metadata_evidence.jsonl': b''.join(encode(r) for r in reports),
             'header_receipts.jsonl': b''.join(encode(r) for r in receipts)}
    manifest = {'schema_version': 'paper-metadata-1', 'documents': len(rows), 'headers': len(headers),
                'conflicting_fields': sum(f['status'] == 'conflict' for r in reports for f in r['fields'].values()),
                'index_sha256': checks[0][1], 'subjects_sha256': checks[1][1],
                'code_sha256': file_hash(Path(__file__)), 'header_lines': header_lines,
                'output_sha256': {name: digest(data) for name, data in files.items()}}
    publish(output, {**files, 'manifest.json': encode(manifest)})
    return {'output': str(output), **manifest}
