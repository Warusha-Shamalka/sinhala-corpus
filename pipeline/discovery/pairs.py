"""Propose paper/marking-scheme relationships without inventing approved answers."""
from collections import Counter, defaultdict
import csv
import io
from pathlib import Path

import yaml

from pipeline.dataset.native import digest, encode, publish
from pipeline.discovery.crawler import read_catalog
from pipeline.discovery.exams import FIELDS, metadata
from pipeline.download.downloader import file_hash


REQUIRED = ('exam', 'subject', 'exam_year', 'medium', 'paper_number', 'paper_kind')
REVIEW_FIELDS = ('pair_id', 'paper_doc_id', 'marking_scheme_doc_id', 'match_status',
                 'decision', 'reviewer', 'source_evidence', 'notes')


def build(rows, subjects, *, max_candidates=10000, subject=None, exam_year=None):
    if type(max_candidates) is not int or max_candidates < 1:
        raise ValueError('max_candidates must be a positive integer')
    if exam_year is not None and (type(exam_year) is not int or not 1900 <= exam_year <= 2099):
        raise ValueError('exam_year must be between 1900 and 2099')
    records = []
    for row in rows:
        if row['document_type'] not in {'past_paper', 'marking_scheme'}: continue
        info = metadata(row['title'], row['source_url'], subjects, row)
        if subject and info['subject'].casefold() != subject.casefold(): continue
        if exam_year and info['exam_year'] != str(exam_year): continue
        records.append({'doc_id': row['doc_id'], 'document_type': row['document_type'],
                        'source': row['source'], 'source_url': row['source_url'],
                        'raw_sha256': row.get('sha256', ''), 'metadata': info})
    schemes = defaultdict(list)
    for record in records:
        info = record['metadata']
        if record['document_type'] == 'marking_scheme' and info['subject'] and info['exam_year'] and not info['conflicts']:
            schemes[info['subject'], info['exam_year']].append(record)
    proposals, unmatched, proposed_ids = [], [], set()
    for paper in records:
        if paper['document_type'] != 'past_paper': continue
        left = paper['metadata']
        if left['conflicts'] or not left['subject'] or not left['exam_year']:
            unmatched.append({'doc_id': paper['doc_id'], 'reason': 'conflicting_or_missing_identity',
                              'conflicts': left['conflicts']})
            continue
        compatible = []
        for scheme in schemes[left['subject'], left['exam_year']]:
            right = scheme['metadata']
            # Never match across known medium, part, session, version or issuer conflicts.
            if any(left[key] and right[key] and left[key] != right[key] for key in FIELDS): continue
            compatible.append(scheme)
        if not compatible:
            unmatched.append({'doc_id': paper['doc_id'], 'reason': 'no_compatible_marking_scheme'})
        for scheme in compatible:
            if len(proposals) >= max_candidates:
                raise ValueError('Pairing candidate budget exceeded; narrow the catalog or increase max_candidates')
            right = scheme['metadata']
            missing = [key for key in REQUIRED if not left[key] or not right[key]]
            # School/model papers need an explicit issuer and session as well.
            if left['paper_kind'] in {'term_test', 'model'} or right['paper_kind'] in {'term_test', 'model'}:
                missing.extend(key for key in ('issuer', 'session') if not left[key] or not right[key])
            unresolved = [key for key in ('grade', 'session', 'syllabus', 'issuer') if bool(left[key]) != bool(right[key])]
            pair_id = digest(encode([paper['doc_id'], scheme['doc_id']]))[:24]
            proposals.append({'pair_id': pair_id, 'paper_doc_id': paper['doc_id'],
                              'marking_scheme_doc_id': scheme['doc_id'], 'paper_source_url': paper['source_url'],
                              'marking_scheme_source_url': scheme['source_url'],
                              'paper_raw_sha256': paper['raw_sha256'], 'marking_scheme_raw_sha256': scheme['raw_sha256'],
                              'match_status': 'needs_metadata' if missing or unresolved else 'unique_candidate',
                              'missing_fields': sorted(set(missing + unresolved)),
                              'matching_fields': {key: left[key] for key in FIELDS if left[key] and left[key] == right[key]},
                              'paper_evidence': left['evidence'], 'marking_scheme_evidence': right['evidence'],
                              'review_required': True, 'training_approved': False})
            proposed_ids.update((paper['doc_id'], scheme['doc_id']))
    paper_counts = Counter(p['paper_doc_id'] for p in proposals)
    scheme_counts = Counter(p['marking_scheme_doc_id'] for p in proposals)
    for proposal in proposals:
        if paper_counts[proposal['paper_doc_id']] > 1 or scheme_counts[proposal['marking_scheme_doc_id']] > 1:
            proposal['match_status'] = 'ambiguous'
    for record in records:
        if record['document_type'] == 'marking_scheme' and record['doc_id'] not in proposed_ids:
            unmatched.append({'doc_id': record['doc_id'], 'reason': 'unpaired_marking_scheme',
                              'conflicts': record['metadata']['conflicts']})
    return {'records': records, 'proposals': proposals, 'unmatched': unmatched}


def prepare(catalog, subjects_path, output=None, *, dry_run=False, max_candidates=10000, subject=None, exam_year=None):
    catalog, subjects_path = Path(catalog), Path(subjects_path)
    catalog_sha, subjects_sha = file_hash(catalog), file_hash(subjects_path)
    rows = read_catalog(catalog)
    subjects = yaml.safe_load(subjects_path.read_text(encoding='utf-8'))
    if not isinstance(subjects, dict) or not isinstance(subjects.get('domains'), dict):
        raise ValueError('Invalid subject configuration')
    packet = build(rows, subjects, max_candidates=max_candidates, subject=subject, exam_year=exam_year)
    if file_hash(catalog) != catalog_sha or file_hash(subjects_path) != subjects_sha:
        raise ValueError('Catalog or subjects changed while pairing; rerun from a stable snapshot')
    report = {'schema_version': 'paper-pairing-report-1', 'dry_run': dry_run,
              'catalog_sha256': catalog_sha, 'subjects_sha256': subjects_sha,
              'filters': {'subject': subject, 'exam_year': exam_year},
              'documents_by_type': dict(Counter(r['document_type'] for r in packet['records'])),
              'proposals': len(packet['proposals']), 'match_statuses': dict(Counter(p['match_status'] for p in packet['proposals'])),
              'unmatched_documents': len(packet['unmatched']), 'training_approved': False,
              'note': 'Title/URL metadata proposes relationships. Even unique candidates require source review; no answers are assigned.'}
    if dry_run: return report
    if output is None: raise ValueError('Choose an output directory or use --dry-run')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS); writer.writeheader()
    for proposal in packet['proposals']:
        writer.writerow({**{key: proposal[key] for key in REVIEW_FIELDS if key in proposal}, 'decision': 'pending'})
    files = {'proposals.jsonl': b''.join(encode(p) for p in packet['proposals']),
             'metadata.jsonl': b''.join(encode(r) for r in packet['records']),
             'unmatched.jsonl': b''.join(encode(r) for r in packet['unmatched']),
             'review.csv': stream.getvalue().encode('utf-8'),
             'catalog.csv': catalog.read_bytes(), 'subjects.yaml': subjects_path.read_bytes()}
    if digest(files['catalog.csv']) != catalog_sha or digest(files['subjects.yaml']) != subjects_sha:
        raise ValueError('Inputs changed before publication')
    manifest = {**report, 'schema_version': 'paper-pairing-packet-1',
                'pairing_code_sha256': file_hash(Path(__file__)),
                'metadata_code_sha256': file_hash(Path(__file__).with_name('exams.py')),
                'output_sha256': {name: digest(content) for name, content in files.items()}}
    publish(Path(output), {**files, 'manifest.json': encode(manifest)})
    return {**report, 'packet': str(Path(output).resolve())}
