"""Explicit Sinhala study/MCQ collection policy and deterministic mirror selection."""
from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote

import yaml

from pipeline.dataset.native import digest, encode, publish
from pipeline.discovery.exams import metadata
from pipeline.discovery.filters import normalize_url


EXAM_TYPES = {'past_paper', 'marking_scheme'}


def load_policy(path):
    policy = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(policy, dict) or policy.get('schema_version') != 'sinhala-collection-1':
        raise ValueError('Expected sinhala-collection-1 policy')
    if policy.get('language') != 'si' or policy.get('mcq_only') is not True or policy.get('require_complete_pairs') is not True:
        raise ValueError('This collection requires Sinhala, MCQ-only exams and complete pairs')
    for key in ('source_ids', 'source_preference', 'study_types', 'exam_types'):
        if (not isinstance(policy.get(key), list) or not policy[key]
                or any(not isinstance(v, str) for v in policy[key]) or len(set(policy[key])) != len(policy[key])):
            raise ValueError(f'Invalid collection list: {key}')
    from pipeline.discovery.crawler import DOCUMENT_TYPES
    if set(policy['exam_types']) != EXAM_TYPES or not set(policy['study_types']) <= DOCUMENT_TYPES - EXAM_TYPES:
        raise ValueError('Invalid collection document types')
    overrides = policy.setdefault('overrides', {})
    if not isinstance(overrides, dict): raise ValueError('overrides must be a mapping')
    allowed = {'medium', 'question_format', 'exam', 'subject', 'exam_year', 'paper_kind',
               'paper_number', 'grade', 'session', 'syllabus', 'issuer', 'reviewer', 'source_evidence'}
    for key, value in overrides.items():
        if (not re.fullmatch(r'LK-EDU-\d{6,}', str(key)) or not isinstance(value, dict) or set(value) - allowed
                or any(not isinstance(v, str) for v in value.values())
                or not value.get('reviewer', '').strip() or not value.get('source_evidence', '').strip()
                or value.get('medium', 'si') not in {'si', 'en', 'ta'}
                or value.get('question_format', 'mcq') not in {'mcq', 'essay', 'mixed', 'unknown'}
                or value.get('paper_kind', 'past') not in {'past', 'model', 'term_test'}
                or ('exam_year' in value and not re.fullmatch(r'(?:19|20)\d{2}', value['exam_year']))):
            raise ValueError(f'{key}: reviewed overrides require string values, reviewer and source_evidence')
    return policy


def question_format(text):
    text = re.sub(r'[_-]+', ' ', unquote(text).casefold())
    mcq = bool(re.search(r'\bmcqs?\b|multiple[ -]+choice|බහුවරණ', text))
    essay = bool(re.search(r'\bessay\b|structured[ -]+(?:questions?|paper)|රචනා|ව්‍යුහගත', text))
    full = bool(re.search(r'\bfull\s+paper\b|papers?\s*(?:i|1)\s*(?:and|&|\+)\s*(?:ii|2)\b', text))
    if (mcq and essay) or full: return 'mixed'
    if essay: return 'essay'
    return 'mcq' if mcq else 'unknown'


def identify(row, subjects, policy):
    info = metadata(row['title'], row['source_url'], subjects, row)
    original_format = question_format(row['title'] + ' ' + row['source_url'])
    info['question_format'] = original_format
    override = policy.get('overrides', {}).get(row['doc_id'], {})
    for key, value in override.items():
        if key not in {'reviewer', 'source_evidence'}:
            info[key] = value
            info['conflicts'].pop(key, None)
    if override: info['reviewed_override'] = override
    if (info['paper_kind'] in {'term_test', 'model'}
            and re.search(r'\b(?:college|school|vidyalaya)\b|විද්‍යාල', row['title'], re.I)
            and not override.get('issuer')):
        info['issuer_needs_review'] = True
    if original_format in {'mixed', 'essay'} and info['question_format'] == 'mcq':
        info['conflicts']['question_format'] = [original_format, 'mcq']
    return info


def exam_key(info):
    required = ['exam', 'subject', 'exam_year', 'medium', 'paper_kind']
    if info['paper_kind'] in {'term_test', 'model'}: required += ['grade', 'session', 'issuer']
    if any(not info.get(key) for key in required): return None
    identity = dict(info)
    if info['paper_kind'] == 'past':
        if info['issuer']: return None  # Province/school identity needs an explicit exam kind.
        identity['grade'] = ''  # A/L grade labels are not separate national exam papers.
    return tuple(identity.get(key, '') for key in ('exam', 'subject', 'exam_year', 'medium', 'paper_kind',
                                                  'grade', 'session', 'issuer', 'syllabus'))


def plan(rows, sources, subjects, policy):
    by_name = {s['name']: s for s in sources}
    preference = {name: i for i, name in enumerate(policy['source_preference'])}
    eligible, deferred, excluded, groups = [], [], [], defaultdict(lambda: defaultdict(list))
    def rank(item):
        row, _, source = item
        return (row['status'] not in {'DOWNLOADED', 'EXTRACTED', 'CLEANED', 'DEDUPLICATED', 'VALIDATED', 'READY'},
                row['status'] == 'DOWNLOAD_FAILED',
                preference.get(source['id'], len(preference)), normalize_url(row['source_url']), row['doc_id'])
    for row in rows:
        source = by_name.get(row['source'])
        entry = {'doc_id': row['doc_id'], 'source_url': row['source_url'], 'document_type': row['document_type']}
        if not source or source['id'] not in policy['source_ids'] or not source['enabled'] or not source['verified']:
            excluded.append({**entry, 'reason': 'source_not_selected'}); continue
        if row['status'] == 'DUPLICATE':
            excluded.append({**entry, 'reason': 'duplicate_content'}); continue
        if row['document_type'] not in policy['study_types'] + policy['exam_types']:
            excluded.append({**entry, 'reason': 'document_type_not_selected'}); continue
        info = identify(row, subjects, policy)
        if info['conflicts']:
            deferred.append({**entry, 'reason': 'conflicting_metadata', 'metadata': info}); continue
        if not info['medium']:
            deferred.append({**entry, 'reason': 'medium_unknown', 'metadata': info}); continue
        if info['medium'] != policy['language']:
            excluded.append({**entry, 'reason': 'not_sinhala'}); continue
        if row['document_type'] in policy['study_types']:
            eligible.append((row, info, source)); continue
        if info['question_format'] != 'mcq':
            target = excluded if info['question_format'] == 'essay' else deferred
            target.append({**entry, 'reason': 'exam_' + info['question_format'], 'metadata': info}); continue
        if info.get('issuer_needs_review'):
            deferred.append({**entry, 'reason': 'school_identity_needs_review', 'metadata': info}); continue
        key = exam_key(info)
        if key is None:
            deferred.append({**entry, 'reason': 'exam_identity_incomplete', 'metadata': info}); continue
        groups[key][row['document_type']].append((row, info, source))
    selected_pairs = []
    explicit_versions = {key[:-1] for key in groups if key[-1]}
    for key, roles in sorted(groups.items()):
        if not key[-1] and key[:-1] in explicit_versions:
            for items in roles.values():
                deferred.extend({'doc_id': item[0]['doc_id'], 'reason': 'syllabus_version_unknown'} for item in items)
            continue
        papers = sorted(roles['past_paper'], key=rank)
        schemes = sorted(roles['marking_scheme'], key=rank)
        chosen = None
        # Prefer already collected complete pairs; deterministic across mirror order.
        combinations = []
        if len(papers) * len(schemes) > 10000:
            for item in papers + schemes:
                deferred.append({'doc_id': item[0]['doc_id'], 'reason': 'pair_ambiguity_budget'})
            continue
        for paper in papers:
            for scheme in schemes:
                left, right = paper[1], scheme[1]
                if left['paper_number'] and right['paper_number'] and left['paper_number'] != right['paper_number']: continue
                if paper[0].get('sha256') and paper[0]['sha256'] == scheme[0].get('sha256'): continue
                score = (rank(paper)[0] + rank(scheme)[0], rank(paper)[1] + rank(scheme)[1], rank(paper), rank(scheme))
                combinations.append((score, paper, scheme))
        if combinations:
            _, paper, scheme = min(combinations, key=lambda item: item[0])
            chosen = {paper[0]['doc_id'], scheme[0]['doc_id']}
            eligible.extend((paper, scheme))
            selected_pairs.append({'pair_key': list(key), 'paper_doc_id': paper[0]['doc_id'],
                                   'marking_scheme_doc_id': scheme[0]['doc_id'],
                                   'review_required': True, 'training_approved': False})
        for item in papers + schemes:
            entry = {'doc_id': item[0]['doc_id'], 'source_url': item[0]['source_url'], 'metadata': item[1]}
            if chosen is None: deferred.append({**entry, 'reason': 'matching_mcq_counterpart_missing'})
            elif item[0]['doc_id'] not in chosen:
                excluded.append({**entry, 'reason': 'duplicate_exam_mirror', 'preferred_doc_ids': sorted(chosen)})
    # Hash duplicates among study resources are collected once; generic titles are not identities.
    selected, hashes, urls = [], {}, {}
    for row, info, source in sorted(eligible, key=rank):
        identity = row.get('sha256')
        url = normalize_url(row['source_url'])
        previous = hashes.get(identity) if identity else None
        previous = previous or urls.get(url)
        if previous:
            excluded.append({'doc_id': row['doc_id'], 'reason': 'duplicate_artifact_or_url', 'duplicate_of': previous})
            continue
        selected.append({'doc_id': row['doc_id'], 'source_url': row['source_url'], 'raw_sha256': row.get('sha256', ''),
                         'document_type': row['document_type'], 'metadata': info})
        if identity: hashes[identity] = row['doc_id']
        urls[url] = row['doc_id']
    # Never publish a pair whose member was removed by content deduplication.
    ids = {item['doc_id'] for item in selected}
    valid_pairs = [p for p in selected_pairs if {p['paper_doc_id'], p['marking_scheme_doc_id']} <= ids]
    paired_ids = {p[k] for p in valid_pairs for k in ('paper_doc_id', 'marking_scheme_doc_id')}
    deferred.extend({'doc_id': item['doc_id'], 'source_url': item['source_url'], 'reason': 'counterpart_content_duplicate'}
                    for item in selected if item['document_type'] in EXAM_TYPES and item['doc_id'] not in paired_ids)
    selected = [item for item in selected if item['document_type'] not in EXAM_TYPES or item['doc_id'] in paired_ids]
    return {'schema_version': 'sinhala-collection-plan-1', 'selected': selected, 'pairs': valid_pairs,
            'selected_doc_ids': [item['doc_id'] for item in selected], 'deferred': deferred, 'excluded': excluded,
            'counts': {'selected': len(selected), 'pairs': len(valid_pairs), 'deferred': len(deferred), 'excluded': len(excluded)},
            'deferred_reasons': dict(Counter(item['reason'] for item in deferred)),
            'exclusion_reasons': dict(Counter(item['reason'] for item in excluded)), 'training_approved': False}


def for_config(config, policy_path):
    from pipeline.discovery.crawler import read_catalog
    from pipeline.download.downloader import load_settings, load_sources, file_hash
    config = Path(config)
    config_sha = file_hash(config)
    settings = load_settings(config)
    subjects_path = config.parent / 'subjects.yaml'
    sources_path = config.parent / 'sources.yaml'
    inputs = [settings['catalog_path'], subjects_path, sources_path, Path(policy_path)]
    before = {path: file_hash(path) for path in inputs}
    policy = load_policy(policy_path)
    result = plan(read_catalog(settings['catalog_path']), load_sources(sources_path),
                  yaml.safe_load(subjects_path.read_text()), policy)
    if any(file_hash(path) != sha for path, sha in before.items()) or file_hash(config) != config_sha:
        raise ValueError('Collection inputs changed during planning; rerun from a stable snapshot')
    result.update(policy_sha256=before[Path(policy_path)], catalog_sha256=before[settings['catalog_path']])
    result.update(source_config_sha256=before[sources_path], subjects_sha256=before[subjects_path],
                  collection_code_sha256=file_hash(Path(__file__)),
                  metadata_code_sha256=file_hash(Path(__file__).parent / 'discovery/exams.py'))
    return result


def write(config, policy_path, output=None):
    result = for_config(config, policy_path)
    if output is not None:
        files = {name + '.jsonl': b''.join(encode(row) for row in result[name])
                 for name in ('selected', 'pairs', 'deferred', 'excluded')}
        files['selection.json'] = encode(result)
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=['doc_id', 'reason', 'source_url', 'metadata', 'reviewer', 'source_evidence'])
        writer.writeheader()
        for row in result['deferred']:
            writer.writerow({key: (json.dumps(row.get('metadata', {}), ensure_ascii=False) if key == 'metadata' else row.get(key, ''))
                             for key in writer.fieldnames})
        files['deferred_review.csv'] = stream.getvalue().encode('utf-8')
        publish(Path(output), {**files, 'manifest.json': encode({'schema_version': 'collection-plan-bundle-1',
                'output_sha256': {name: digest(value) for name, value in files.items()}})})
    return {key: result[key] for key in ('schema_version', 'counts', 'deferred_reasons', 'exclusion_reasons', 'policy_sha256')} | {
            'output': str(output) if output else None}
