"""Editable public document index and conservative, unapproved pair suggestions."""
import csv
import io
from collections import Counter
from pathlib import Path
import re
import yaml

from pipeline.dataset.native import digest, encode, publish
from pipeline.download.downloader import file_hash
from pipeline.discovery.filters import detect_document_type, extract_medium_hint, subject_matches


FIELDS = ['doc_id', 'source_url', 'title', 'raw_sha256', 'role', 'exam', 'subject', 'year',
          'paper_number', 'language', 'variant', 'collection_id', 'metadata_status', 'reviewer', 'notes']
IDENTITY = ['exam', 'subject', 'year', 'paper_number', 'language', 'variant', 'collection_id']


def canonical(value):
    return ' '.join(value.casefold().split())


def prepare(catalog, output):
    catalog, output = Path(catalog), Path(output)
    sha = file_hash(catalog)
    subjects = yaml.safe_load((Path(__file__).resolve().parents[2] / 'configs/subjects.yaml').read_text())
    rows, ids = [], set()
    with catalog.open(encoding='utf-8', newline='') as stream:
        for source in csv.DictReader(stream):
            sid, title = source['doc_id'], source.get('title', '')
            if sid in ids: raise ValueError('Duplicate catalog document ID')
            ids.add(sid)
            text = title.casefold()
            kind = source.get('document_type', '')
            key = kind == 'marking_scheme' or detect_document_type('', title) == 'marking_scheme' or bool(re.search(r'\banswers\b', text))
            paper = kind == 'past_paper' or bool(re.search(r'\b(past\s+paper|question\s+paper|pesuru)\b', text))
            if not (key or paper): continue
            years = set(re.findall(r'\b(?:19|20)[0-9]{2}\b', title))
            exam_year = source.get('exam_year', '')
            if exam_year: years.add(exam_year)
            exams = [name for name, pattern in [('AL', r'\ba\s*[/.-]?\s*l\b|advanced\s+level'),
                                                ('OL', r'\bo\s*[/.-]?\s*l\b|ordinary\s+level')]
                     if re.search(pattern, text)]
            parts = {v.upper() for v in re.findall(r'\b(?:paper|part)\s*[-:]?\s*(III|II|I|[123AB])\b', title, re.I)}
            row = {field: '' for field in FIELDS}
            row.update(doc_id=sid, source_url=source.get('source_url', ''), title=title,
                       raw_sha256=source.get('sha256', ''), role='key' if key else 'paper',
                       exam=exams[0] if len(exams) == 1 else '', subject=source.get('subject', ''),
                       year=next(iter(years)) if len(years) == 1 else '',
                       paper_number=next(iter(parts)) if len(parts) == 1 else '',
                       language=source.get('language', ''), metadata_status='unverified',
                       notes='Catalog/title hints only; verify from the original document.')
            subject, _ = subject_matches(title, subjects)
            medium = extract_medium_hint(title, subjects)
            for field, hint in (('subject', subject), ('language', medium)):
                if hint:
                    if row[field] and canonical(row[field]) != canonical(hint):
                        row[field] = ''
                        row['notes'] += f' Conflicting catalog/title {field}; original-source review required.'
                    else:
                        row[field] = hint
            row['paper_number'] = {'I': '1', 'II': '2', 'III': '3'}.get(row['paper_number'], row['paper_number'])
            if 'pesuru' in text or len(years) > 1:
                row['notes'] += ' Possible compilation: record collection/edition ID; do not infer one exam year.'
                row['year'] = ''
                row['collection_id'] = 'UNRESOLVED'
            rows.append(row)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    if file_hash(catalog) != sha: raise ValueError('Catalog changed while preparing index')
    publish(output, {'documents.csv': stream.getvalue().encode(), 'manifest.json': encode({
        'schema_version': 'paper-pair-index-1', 'catalog_sha256': sha, 'documents': len(rows),
        'note': 'documents.csv is editable; every identity starts unverified. No sources were crawled.'})})
    return {'output': str(output), 'documents': len(rows), 'roles': dict(Counter(r['role'] for r in rows))}


def suggest(index, output, max_comparisons=100000):
    index, output = Path(index), Path(output)
    sha = file_hash(index)
    with index.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or []) != set(FIELDS): raise ValueError('Unexpected pairing index columns')
        rows = list(reader)
    if len({r['doc_id'] for r in rows}) != len(rows): raise ValueError('Duplicate index document ID')
    for row in rows:
        if not row['doc_id'] or row['role'] not in {'paper', 'key'}: raise ValueError('Invalid indexed document')
        if row['metadata_status'] not in {'unverified', 'verified'}: raise ValueError('Invalid metadata status')
        if row['metadata_status'] == 'verified' and not row['reviewer'].strip(): raise ValueError('Verified metadata requires reviewer')
    papers, keys = [r for r in rows if r['role'] == 'paper'], [r for r in rows if r['role'] == 'key']
    if len(papers) * len(keys) > max_comparisons: raise ValueError('Comparison limit exceeded; narrow the index')
    suggestions = []
    for paper in papers:
        for key in keys:
            if 'UNRESOLVED' in (paper['collection_id'], key['collection_id']): continue
            # A collection must have its own matching edition identity, not match an ordinary exam.
            if canonical(paper['collection_id']) != canonical(key['collection_id']): continue
            if any(paper[f] and key[f] and canonical(paper[f]) != canonical(key[f]) for f in IDENTITY): continue
            required = ['subject', 'collection_id'] if paper['collection_id'] else ['exam', 'subject', 'year']
            if not all(paper[f] and key[f] and canonical(paper[f]) == canonical(key[f]) for f in required): continue
            matched = [f for f in IDENTITY if paper[f] and key[f]]
            missing = [f for f in IDENTITY if f != 'collection_id' and (not paper[f] or not key[f])]
            suggestions.append({'pair_id': digest(encode([paper['doc_id'], key['doc_id']])),
                'paper_doc_id': paper['doc_id'], 'key_doc_id': key['doc_id'],
                'matched_fields': matched, 'missing_fields': missing, 'match_count': len(matched),
                'metadata_verified': all(r['metadata_status'] == 'verified' for r in (paper, key)),
                'pairing_verified': False, 'review_required': True})
    counts = Counter(s['paper_doc_id'] for s in suggestions)
    reverse = Counter(s['key_doc_id'] for s in suggestions)
    for s in suggestions:
        s['ambiguous'] = counts[s['paper_doc_id']] > 1 or reverse[s['key_doc_id']] > 1
    involved = {s[f] for s in suggestions for f in ('paper_doc_id', 'key_doc_id')}
    unresolved = [{'doc_id': r['doc_id'], 'reason': 'no_compatible_pair_or_insufficient_identity'} for r in rows if r['doc_id'] not in involved]
    if file_hash(index) != sha: raise ValueError('Index changed while suggesting pairs')
    files = {'suggestions.jsonl': b''.join(encode(s) for s in suggestions),
             'unresolved.jsonl': b''.join(encode(r) for r in unresolved), 'documents.csv': index.read_bytes()}
    manifest = {'schema_version': 'paper-pair-suggestions-1', 'index_sha256': sha,
                'suggestions': len(suggestions), 'unresolved_documents': len(unresolved),
                'output_sha256': {name: digest(data) for name, data in files.items()},
                'note': 'Suggestions never approve pairs or supply MCQ answers.'}
    publish(output, {**files, 'manifest.json': encode(manifest)})
    return {'output': str(output), **manifest}
