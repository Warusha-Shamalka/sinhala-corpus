"""Conservative public paper/answer-key matching; never approve model labels."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import unicodedata

import yaml

from pipeline.dataset import daily, tasks
from pipeline.dataset.native import digest, encode, publish
from pipeline.download.downloader import file_hash
from pipeline.processing.pages import verify_page


IDENTITY = ('exam', 'subject', 'year', 'paper_number', 'language', 'variant')
QUESTION = re.compile(r'^\s*(?:Q\s*)?([0-9]{1,4})[.)]\s+\S', re.IGNORECASE)
CHOICE = re.compile(r'^\s*(?:\(([A-Za-z]|[0-9]{1,2})\)|([A-Za-z])[.)])\s+\S')
KEY = re.compile(r'^\s*([0-9]{1,4})\s*[.):-]\s*(?:\(([A-Za-z]|[0-9]{1,2})\)|([A-Za-z]|[0-9]{1,2}))\s*$')


def canonical(value):
    return ' '.join(unicodedata.normalize('NFC', str(value)).casefold().split())


def load_pairs(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict) or config.get('schema_version') != 'paper-answer-pairs-1':
        raise ValueError('Invalid paper pair configuration')
    pairs = config.get('pairs')
    if not isinstance(pairs, list) or not pairs:
        raise ValueError('At least one explicitly identified paper/key pair is required')
    ids = set()
    for pair in pairs:
        pid = pair.get('pair_id')
        if not isinstance(pid, str) or not pid.strip() or pid in ids:
            raise ValueError('Missing or duplicate pair ID')
        ids.add(pid)
        for role in ('paper', 'marking_scheme'):
            document = pair[role]
            if not isinstance(document.get('doc_id'), str) or not document['doc_id'].strip() or not re.fullmatch('[0-9a-f]{64}', document.get('raw_sha256', '')):
                raise ValueError('Both documents need a document ID and immutable raw SHA256')
            for field in IDENTITY:
                value = document.get(field)
                if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
                    raise ValueError(f'Missing paper identity: {role}.{field}')
            if not re.fullmatch('[0-9]{4}', str(document['year'])):
                raise ValueError('Exam year must have four digits')
        if any(canonical(pair['paper'][field]) != canonical(pair['marking_scheme'][field]) for field in IDENTITY):
            raise ValueError(f'Paper/marking-scheme identity mismatch: {pid}')
        labels = pair.get('choice_labels')
        if (not isinstance(labels, list) or not 2 <= len(labels) <= 10 or
                any(not isinstance(label, str) or not re.fullmatch('[A-Z]|[1-9]|10', label) for label in labels) or
                len(labels) != len(set(labels))):
            raise ValueError('Declare 2–10 distinct printed choice labels as strings')
        for role in ('questions', 'answers'):
            if not isinstance(pair.get(role), list) or not pair[role]:
                raise ValueError(f'Missing {role} regions')
            for region in pair[role]:
                if not isinstance(region.get('section'), str) or not region['section'].strip():
                    raise ValueError('Every region needs an explicit section, even when numbering never restarts')
        if pair.get('pairing_verified') is True and (not isinstance(pair.get('pairing_reviewer'), str) or not pair['pairing_reviewer'].strip()):
            raise ValueError('Verified pairing needs a reviewer')
    return config


def _document(row, declaration):
    identity = row['source_identity']
    return identity['doc_id'] == declaration['doc_id'] and identity['raw_sha256'] == declaration['raw_sha256']


def _region(region, sources, declaration):
    row = sources.get(region['record_id'])
    if row is None or not _document(row, declaration):
        raise ValueError('Region is missing or belongs to a different document/version')
    lines = row['text'].splitlines()
    lo, hi = tasks._range(region['lines'], len(lines))
    return row, [(n, lines[n - 1]) for n in range(lo, hi + 1)]


def _evidence(row, lines):
    return {'record_id': row['record_id'], 'text_sha256': row['text_sha256'], 'lines': lines}


def questions(row, numbered_lines, labels):
    """Only parse numbered stems and explicit parenthesized/letter choice labels."""
    starts = [(index, int(match[1])) for index, (_, line) in enumerate(numbered_lines)
              if (match := QUESTION.match(line))]
    results = []
    for position, (index, number) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(numbered_lines)
        block = numbered_lines[index:end]
        options = [(j, (match[1] or match[2]).upper()) for j, (_, line) in enumerate(block)
                   if (match := CHOICE.match(line))]
        issues = []
        if number < 1: issues.append('invalid_question_number')
        if [label for _, label in options] != labels: issues.append('missing_reordered_or_duplicate_choices')
        if not options or options[0][0] == 0: issues.append('missing_question_stem')
        item = {'number': number, 'source': _evidence(row, [block[0][0], block[-1][0]]), 'reasons': issues}
        if not issues:
            item['segment'] = {'kind': 'mcq', 'lines': item['source']['lines'],
                'question_lines': [block[0][0], block[options[0][0] - 1][0]],
                'choice_lines': [[block[j][0], block[(options[k + 1][0] if k + 1 < len(options) else len(block)) - 1][0]]
                                 for k, (j, _) in enumerate(options)],
                'answer': None, 'question_choices_verified': False, 'answer_verified': False, 'reviewer': '',
                'answer_evidence': None, 'source_question_number': number}
        results.append(item)
    return results


def _import_keys(sources, config, bundles, release, parent):
    receipts, checks = [], []
    if not bundles: return receipts, checks
    if release is None: raise ValueError('External key bundles require --release for source-family split checks')
    release = Path(release)
    original_sha = file_hash(release / 'manifest.json')
    manifest = daily.verify(release)
    if manifest['release_id'] != parent['daily_release_id'] or original_sha != parent['daily_manifest_sha256']:
        raise ValueError('Key evidence must use the originating daily release')
    ledger = daily.jsonl(release / 'candidates.jsonl')
    checks.append((release / 'manifest.json', original_sha))
    for folder in map(Path, bundles):
        sha = file_hash(folder / 'manifest.json')
        page_manifest = json.loads((folder / 'manifest.json').read_text())
        page = verify_page(folder, page_manifest['identity'])
        identity = page['identity']
        matches = [p for p in config['pairs'] if identity['doc_id'] == p['marking_scheme']['doc_id'] and identity['raw_sha256'] == p['marking_scheme']['raw_sha256']]
        if not matches: raise ValueError('Imported key bundle is not declared in any pair')
        splits = set()
        for pair in matches:
            for region in pair['questions']:
                paper, _ = _region(region, sources, pair['paper']); splits.add(paper['split'])
        if len(splits) != 1: raise ValueError('Shared key document would bridge paper splits')
        split = next(iter(splits))
        for existing in [*ledger, *sources.values()]:
            other = existing['source_identity']
            same_family = other['doc_id'] == identity['doc_id'] or other['raw_sha256'] == identity['raw_sha256'] or existing['source_url'] == page['source_url']
            if same_family and existing['split'] != split: raise ValueError('Imported answer evidence crosses an inherited source split')
        sid = f"{identity['doc_id']}_{identity['raw_sha256']}_p{identity['page_number']:06d}"
        if sid in sources: raise ValueError('Key page already exists in packet; omit its external bundle')
        sources[sid] = {'record_id': sid, 'source_identity': identity, 'source_url': page['source_url'],
            'text': page['text'], 'text_sha256': digest(page['text'].encode()), 'metadata_hints': page['metadata_hints'],
            'split': split, 'evidence_only': True, 'source_review_status': 'provisional',
            'review_required': True, 'training_approved': False, 'quality_flags': page['quality_flags'],
            'method': page['method'], 'prediction_outcome': page.get('prediction', {}).get('outcome'),
            'completion_status': page.get('prediction', {}).get('completion_status'),
            'model_id': page.get('model_id'), 'model_revision': page.get('model_revision'),
            'source_record_sha256': file_hash(folder / 'page.json')}
        receipts.append({'record_id': sid, 'bundle': str(folder.resolve()), 'manifest_sha256': sha,
                         'split': split, 'role': 'answer_evidence_only'})
        checks.append((folder / 'manifest.json', sha))
    return receipts, checks


def match(packet, pairs_path, output, *, key_bundles=(), release=None):
    packet, pairs_path, output = Path(packet), Path(pairs_path), Path(output)
    tasks._outside(output, packet, *map(Path, key_bundles))
    if release is not None: tasks._outside(output, Path(release))
    parent, sources = tasks._load(packet)
    if 'matching_report.json' in parent['output_sha256']:
        raise ValueError('Start from an unmatched task packet; do not overwrite earlier matching provenance')
    # Validate existing annotations before extending them.
    tasks._render(packet)
    input_hashes = {name: file_hash(packet / name) for name in ('manifest.json', 'annotations.jsonl', *parent['output_sha256'])}
    config_sha = file_hash(pairs_path)
    config = load_pairs(pairs_path)
    receipts, checks = _import_keys(sources, config, key_bundles, release, parent)
    annotations = {a['record_id']: a for a in daily.jsonl(packet / 'annotations.jsonl')}
    for sid, row in sources.items():
        annotations.setdefault(sid, {'record_id': sid, 'text_sha256': row['text_sha256'], 'segments': []})
        if row.get('evidence_only') and row['text'].splitlines():
            annotations[sid]['segments'] = [{'kind': 'exclude', 'lines': [1, len(row['text'].splitlines())], 'reason': 'answer evidence only'}]
    report = {'schema_version': 'paper-answer-matches-1', 'pairs': [], 'matches': [], 'issues': [],
              'input_manifest_sha256': input_hashes['manifest.json'], 'pair_config_sha256': config_sha,
              'training_approved': False, 'matcher_code_sha256': file_hash(Path(__file__))}
    # Regions may not overlap across any role/pair: duplicate configurations are errors.
    region_used = defaultdict(set)
    for pair in config['pairs']:
        pid, labels = pair['pair_id'], pair['choice_labels']
        paper_splits, entries, found, unparsed_sections = set(), defaultdict(list), [], set()
        for role, document in (('questions', 'paper'), ('answers', 'marking_scheme')):
            for region in pair[role]:
                row, lines = _region(region, sources, pair[document])
                coverage = {n for n, _ in lines}
                if coverage & region_used[row['record_id']]: raise ValueError('Configured source regions overlap')
                region_used[row['record_id']].update(coverage)
                section = region['section'].strip()
                paper_splits.add(row['split'])
                if role == 'questions':
                    if row.get('evidence_only'): raise ValueError('Evidence-only key pages cannot supply training questions')
                    parsed = questions(row, lines, labels)
                    for item in parsed: item['section'] = section
                    found.extend(parsed)
                    if not parsed: report['issues'].append({'pair_id': pid, 'source': _evidence(row, region['lines']), 'reason': 'no_supported_questions'})
                else:
                    overlaps = [old for old in annotations[row['record_id']]['segments']
                                if region['lines'][0] <= old['lines'][1] and region['lines'][1] >= old['lines'][0]]
                    if any(old['kind'] != 'exclude' for old in overlaps):
                        raise ValueError('Answer region overlaps an existing training annotation')
                    if not overlaps:
                        annotations[row['record_id']]['segments'].append({'kind': 'exclude', 'lines': region['lines'], 'reason': 'answer key'})
                    if row.get('method') == 'ocr' and (row.get('prediction_outcome') != 'predicted' or row.get('completion_status') != 'complete'):
                        unparsed_sections.add(section)
                        report['issues'].append({'pair_id': pid, 'source': _evidence(row, region['lines']), 'reason': 'incomplete_key_ocr'})
                    warnings = set(row.get('quality_flags', [])) - {'short_text', 'little_sinhala_or_legacy_font'}
                    if warnings and row.get('source_review_status') != 'human_verified':
                        unparsed_sections.add(section)
                        report['issues'].append({'pair_id': pid, 'source': _evidence(row, region['lines']),
                                                 'reason': 'key_quality_warning', 'warnings': sorted(warnings)})
                    for n, line in lines:
                        if not line.strip(): continue
                        key = KEY.fullmatch(line)
                        label = (key[2] or key[3]).upper() if key else None
                        if key is None or int(key[1]) < 1 or label not in labels:
                            unparsed_sections.add(section)
                            report['issues'].append({'pair_id': pid, 'section': section, 'source': _evidence(row, [n, n]), 'reason': 'unsupported_answer_key_line'})
                        else:
                            entries[(section, int(key[1]))].append({'label': label, 'source': _evidence(row, [n, n])})
        if len(paper_splits) != 1: raise ValueError('Paired paper and marking scheme cross inherited splits')
        paired = pair.get('pairing_verified') is True
        report['pairs'].append({'pair_id': pid, 'split': next(iter(paper_splits)), 'pairing_verified': paired,
                                'paper': pair['paper'], 'marking_scheme': pair['marking_scheme']})
        counts = Counter((q['section'], q['number']) for q in found)
        for item in found:
            key = (item['section'], item['number'])
            issues = list(item['reasons'])
            if not paired: issues.append('pairing_unverified')
            if counts[key] != 1: issues.append('duplicate_question_number_in_section')
            if not entries[key]: issues.append('missing_key_entry')
            elif len(entries[key]) != 1: issues.append('duplicate_or_conflicting_key_entries')
            if item['section'] in unparsed_sections: issues.append('answer_section_needs_layout_review')
            sid = item['source']['record_id']
            segment = item.get('segment')
            if segment:
                lo, hi = segment['lines']
                if any(lo <= old['lines'][1] and hi >= old['lines'][0] for old in annotations[sid]['segments']):
                    issues.append('existing_annotation_overlap'); segment = None
            status = 'proposed_match' if not issues else 'unresolved'
            if segment:
                segment.update(source_section=item['section'], paper_pair_id=pid,
                               matching_reasons=issues, source_choice_labels=labels)
                if not issues:
                    segment['answer'] = labels.index(entries[key][0]['label']) + 1
                    segment['answer_evidence'] = entries[key][0]['source']
                annotations[sid]['segments'].append(segment)
            report['matches'].append({'pair_id': pid, 'section': key[0], 'question_number': key[1],
                'source': item['source'], 'status': status, 'reasons': issues,
                'key_entries': entries[key], 'answer': segment.get('answer') if segment else None})
        for key, values in entries.items():
            if key not in counts:
                report['issues'].append({'pair_id': pid, 'section': key[0], 'question_number': key[1],
                                         'reason': 'key_without_question', 'key_entries': values})
    report['counts'] = dict(Counter(row['status'] for row in report['matches']))
    report['counts']['issues'] = len(report['issues'])
    display = ''.join(f'\n{sid} [{row["split"]}]\nSource: {row["source_url"]}\n' +
                      ''.join(f'{i:04d}: {line}\n' for i, line in enumerate(row['text'].splitlines(), 1))
                      for sid, row in sorted(sources.items()))
    files = {'sources.jsonl': b''.join(encode(row) for _, row in sorted(sources.items())), 'pages.txt': display.encode(),
             'annotations.jsonl': b''.join(encode(row) for _, row in sorted(annotations.items())),
             'matching_report.json': encode(report), 'pairing.json': encode(config),
             'source_bundles.jsonl': b''.join(encode(row) for row in receipts)}
    manifest = {**parent, 'output_sha256': {name: digest(data) for name, data in files.items() if name != 'annotations.jsonl'}}
    for name, sha in input_hashes.items():
        if file_hash(packet / name) != sha: raise ValueError('Input packet changed during matching')
    if file_hash(pairs_path) != config_sha: raise ValueError('Pair configuration changed during matching')
    for path, sha in checks:
        if file_hash(path) != sha: raise ValueError('Key evidence changed during matching')
    for receipt in receipts:
        folder = Path(receipt['bundle']); m = json.loads((folder / 'manifest.json').read_text())
        verify_page(folder, m['identity'])
    if release is not None and key_bundles: daily.verify(Path(release))
    publish(output, {**files, 'manifest.json': encode(manifest)})
    return {'packet': str(output), 'counts': report['counts'], 'report': str(output / 'matching_report.json'),
            'note': 'Proposed matches still require source question/choice and answer checks.'}
