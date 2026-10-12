"""Separate public-source theory and source-backed MCQs from a daily text release.

Annotations select inclusive, one-based line ranges; source text is never rewritten.
This stage neither fetches benchmarks nor generates questions or answer labels.
"""
import json
from pathlib import Path

from pipeline.dataset import daily
from pipeline.dataset.native import digest, encode, publish
from pipeline.download.downloader import file_hash


SPLITS = ('train', 'validation')


def _sources(root):
    manifest = daily.verify(root)
    rows = [row for split in SPLITS for row in daily.jsonl(root / f'{split}.jsonl')]
    return manifest, {row['record_id']: row for row in rows}


def _outside(output, *inputs):
    if any(output.resolve().is_relative_to(path.resolve()) for path in inputs):
        raise ValueError('Output must be outside its inputs')


def prepare(release, output):
    release, output = Path(release), Path(output)
    _outside(output, release)
    source_manifest_sha = file_hash(release / 'manifest.json')
    manifest, records = _sources(release)
    annotations, display = [], []
    for sid, row in sorted(records.items()):
        annotations.append({'record_id': sid, 'text_sha256': row['text_sha256'], 'segments': []})
        display.append(f"\n{sid} [{row['split']}]\nSource: {row['source_url']}\n")
        display.extend(f'{i:04d}: {line}\n' for i, line in enumerate(row['text'].splitlines(), 1))
    sources = b''.join(encode(row) for _, row in sorted(records.items()))
    display = ''.join(display).encode('utf-8')
    packet = {'schema_version': 'task-annotation-packet-1', 'daily_release_id': manifest['release_id'],
              'daily_manifest_sha256': source_manifest_sha,
              'output_sha256': {'sources.jsonl': digest(sources), 'pages.txt': digest(display)}}
    daily.verify(release)
    if file_hash(release / 'manifest.json') != source_manifest_sha:
        raise ValueError('Daily release changed during packet preparation')
    publish(output, {'sources.jsonl': sources, 'pages.txt': display,
                     'annotations.jsonl': b''.join(encode(row) for row in annotations),
                     'manifest.json': encode(packet)})
    return {'packet': str(output), 'pages': len(records), 'note': 'No pages have been classified yet.'}


def _range(value, size):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(v) is not int for v in value) or not 1 <= value[0] <= value[1] <= size):
        raise ValueError('Line range must be [first, last], inclusive and within the page')
    return value


def _text(row, span):
    lines = row['text'].splitlines()
    start, end = _range(span, len(lines))
    result = '\n'.join(lines[start - 1:end]).strip()
    if not result:
        raise ValueError('Selected source text is empty')
    return result


def _load(packet):
    manifest = json.loads((packet / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'task-annotation-packet-1':
        raise ValueError('Invalid annotation packet')
    if set(manifest.get('output_sha256', {})) != {'sources.jsonl', 'pages.txt'}:
        raise ValueError('Invalid packet artifacts')
    for name, sha in manifest['output_sha256'].items():
        if file_hash(packet / name) != sha:
            raise ValueError('Packet source evidence changed')
    records = daily.jsonl(packet / 'sources.jsonl')
    by_id = {r['record_id']: r for r in records}
    if len(by_id) != len(records):
        raise ValueError('Duplicate source records')
    for row in records:
        if row['split'] not in SPLITS or digest(row['text'].encode()) != row['text_sha256']:
            raise ValueError('Invalid packet text/split')
    return manifest, by_id


def _render(packet):
    manifest, sources = _load(packet)
    annotations = daily.jsonl(packet / 'annotations.jsonl')
    seen, outputs, unresolved, excluded, duplicates = set(), {f'{kind}/{split}.jsonl': [] for kind in ('theory', 'mcq') for split in SPLITS}, [], [], []
    candidates, keys = [], {}
    for annotation in annotations:
        sid = annotation['record_id']
        if sid in seen or sid not in sources:
            raise ValueError('Duplicate or unknown annotated page')
        seen.add(sid)
        row = sources[sid]
        if annotation['text_sha256'] != row['text_sha256']:
            raise ValueError('Annotation is stale: page text changed')
        covered, size = set(), len(row['text'].splitlines())
        for segment in annotation['segments']:
            kind, span = segment['kind'], segment['lines']
            start, end = _range(span, size)
            selected = set(range(start, end + 1))
            if selected & covered:
                raise ValueError('Theory, MCQ and excluded segments must not overlap')
            covered.update(selected)
            if kind not in {'theory', 'mcq', 'exclude'}:
                raise ValueError('Unknown segment kind')
            item_id = digest(encode([sid, row['text_sha256'], kind, span]))
            provenance = {'page_record_id': sid, 'source_identity': row['source_identity'],
                          'source_url': row['source_url'], 'text_sha256': row['text_sha256'],
                          'lines': span, 'daily_release_id': manifest['daily_release_id']}
            if kind == 'exclude':
                excluded.append({'record_id': item_id, 'provenance': provenance, 'reason': segment.get('reason', '')})
                continue
            if kind == 'theory':
                text = _text(row, span)
                result = {'record_id': item_id, 'text': text, 'split': row['split'],
                          'metadata': row['metadata_hints'], 'provenance': provenance,
                          'source_review_status': row['source_review_status'],
                          'review_required': row['review_required'], 'training_approved': row['training_approved']}
                key = ('theory', daily.content_key(text))
            else:
                ranges = [segment['question_lines'], *segment['choice_lines']]
                if not 2 <= len(segment['choice_lines']) <= 10:
                    raise ValueError('MCQs need between two and ten choices')
                used = set()
                for part in ranges:
                    lo, hi = _range(part, size)
                    lines = set(range(lo, hi + 1))
                    if not lines <= selected or lines & used:
                        raise ValueError('Question/choice ranges must be disjoint and inside the MCQ segment')
                    used.update(lines)
                question, *choices = [_text(row, part) for part in ranges]
                choice_keys = [daily.content_key(choice) for choice in choices]
                if len(set(choice_keys)) != len(choices):
                    raise ValueError('MCQ has duplicate choices')
                answer = segment.get('answer')
                if answer is not None and (type(answer) is not int or not 1 <= answer <= len(choices)):
                    raise ValueError('MCQ answer must be a one-based integer within the choices')
                hints = row['metadata_hints']
                grade = hints.get('grade')
                grade = int(grade) if str(grade).isdigit() and 1 <= int(grade) <= 13 else None
                domain = hints.get('domain')
                result = {'record_id': item_id, 'question': question, 'choices': choices, 'answer': answer,
                          'subject': hints.get('subject') or None, 'category': domain.lower().replace(' ', '_') if domain else None,
                          'metadata': {'difficulty': None, 'grade': grade,
                                       'type': 'source_mcq', 'subject_original': None},
                          'split': row['split'], 'provenance': provenance,
                          'source_review_status': row['source_review_status']}
                reasons = []
                if answer is None: reasons.append('missing_answer')
                if segment.get('question_choices_verified') is not True: reasons.append('question_choices_unverified')
                if segment.get('answer_verified') is not True: reasons.append('answer_unverified')
                if not isinstance(segment.get('reviewer'), str) or not segment['reviewer'].strip(): reasons.append('missing_reviewer')
                evidence = segment.get('answer_evidence')
                if not evidence:
                    reasons.append('missing_answer_evidence')
                else:
                    source = sources.get(evidence['record_id'])
                    if source is None or evidence.get('text_sha256') != source['text_sha256']:
                        raise ValueError('Unknown or stale answer evidence')
                    if source['split'] != row['split']:
                        raise ValueError('Answer evidence crosses source splits')
                    result['provenance']['answer_evidence'] = {**evidence, 'text': _text(source, evidence['lines']),
                                                              'source_url': source['source_url']}
                if reasons:
                    candidates.append({**result, 'answer': None, 'proposed_answer': answer,
                                       'review_required': True, 'training_approved': False, 'reasons': reasons})
                    continue
                result['provenance']['metadata_hints'] = hints
                result.update(reviewer=segment['reviewer'].strip(), review_required=False,
                              question_choices_verified=True, answer_verified=True,
                              training_approved=row['split'] == 'train', answer_status='source_verified')
                # Reordered choices still describe the same MCQ; compare the actual answer text.
                key = ('mcq', daily.content_key(question), tuple(sorted(choice_keys)))
                result['provenance']['question_lines'] = segment['question_lines']
                result['provenance']['choice_lines'] = segment['choice_lines']
            if key in keys:
                previous = keys[key]
                if previous['split'] != result['split']:
                    raise ValueError('Duplicate task content crosses splits')
                if kind == 'mcq' and daily.content_key(previous['choices'][previous['answer'] - 1]) != daily.content_key(choices[answer - 1]):
                    raise ValueError('Duplicate MCQs have conflicting answer keys')
                duplicates.append({'record_id': item_id, 'duplicate_of': previous['record_id']})
                continue
            keys[key] = result
            outputs[f'{kind}/{row["split"]}.jsonl'].append(result)
        missing = sorted(set(range(1, size + 1)) - covered)
        if missing:
            unresolved.append({'record_id': sid, 'reason': 'unclassified_lines', 'lines': missing})
    for sid in sorted(sources.keys() - seen):
        unresolved.append({'record_id': sid, 'reason': 'unclassified_page'})
    # q_no is a release-local row number, never a benchmark question identifier.
    for split in SPLITS:
        for number, row in enumerate(sorted(outputs[f'mcq/{split}.jsonl'], key=lambda r: r['record_id']), 1):
            row['q_no'] = number
    outputs.update({'mcq_candidates.jsonl': candidates, 'unresolved.jsonl': unresolved,
                    'excluded.jsonl': excluded, 'duplicates.jsonl': duplicates})
    return manifest, outputs


def build(packet, output):
    packet, output = Path(packet), Path(output)
    _outside(output, packet)
    # Freeze edited annotations and source evidence into the release for reproducibility.
    snapshot = {name: (packet / name).read_bytes() for name in ('manifest.json', 'sources.jsonl', 'pages.txt', 'annotations.jsonl')}
    parent, rows = _render(packet)
    files = {name: b''.join(encode(row) for row in values) for name, values in rows.items()}
    files.update({f'evidence/{name}': data for name, data in snapshot.items()})
    if any((packet / name).read_bytes() != data for name, data in snapshot.items()):
        raise ValueError('Annotation packet changed during export')
    hashes = {name: digest(data) for name, data in files.items()}
    manifest = {'schema_version': 'task-dataset-release-1', 'daily_release_id': parent['daily_release_id'],
                'release_id': digest(encode(hashes)), 'output_sha256': hashes,
                'counts': {name: len(values) for name, values in rows.items()},
                'answer_base': 1, 'code_sha256': file_hash(Path(__file__)),
                'note': 'Source review declarations are not authenticated accuracy measurements. No synthetic labels were generated.'}
    publish(output, {**files, 'manifest.json': encode(manifest)})
    return {'output': str(output), **verify(output)}


def verify(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'task-dataset-release-1':
        raise ValueError('Invalid task release schema')
    parent, expected = _render(root / 'evidence')
    names = set(expected) | {f'evidence/{name}' for name in ('manifest.json', 'sources.jsonl', 'pages.txt', 'annotations.jsonl')}
    hashes = manifest['output_sha256']
    if set(hashes) != names or manifest['release_id'] != digest(encode(hashes)):
        raise ValueError('Invalid task release identity/artifacts')
    for name, sha in hashes.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != sha:
            raise ValueError('Task release artifact changed')
    if manifest['daily_release_id'] != parent['daily_release_id'] or manifest['answer_base'] != 1:
        raise ValueError('Task release lineage/answer base changed')
    for name, rows in expected.items():
        if daily.jsonl(root / name) != rows or manifest['counts'][name] != len(rows):
            raise ValueError('Task export differs from its source annotations')
    return manifest
