"""Versioned text candidates for daily training, with cumulative/delta lineage."""
from collections import Counter
import json
from pathlib import Path
import unicodedata

from pipeline.cleaning.native import clean
from pipeline.dataset import reviewed
from pipeline.dataset.native import digest, encode, publish
from pipeline.deduplication.grouping import group
from pipeline.download.downloader import file_hash
from pipeline.quality.text import flags


POLICY = {'version': 'daily-text-filter-1', 'min_characters': 80, 'min_sinhala_letter_ratio': 0.8,
          'validation_percent': 10, 'split_seed': 'sinhala-corpus-v1', 'max_candidates': 5000,
          'near_threshold': 0.9, 'near_minimum_words': 30}


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def content_key(text):
    return digest(' '.join(clean(text).split()).encode('utf-8'))


def normalize(text):
    text = clean(text)
    lines = text.splitlines()
    removed = 0
    while lines and lines[-1].strip() in {'Scanned with CamScanner', 'Scanned by CamScanner'}:
        lines.pop(); removed += 1
        while lines and not lines[-1].strip(): lines.pop()
    return '\n'.join(lines).strip(), removed


def verify(root, schema='daily-text-release-1'):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != schema: raise ValueError('Invalid release schema')
    hashes = manifest.get('output_sha256', {})
    if not isinstance(hashes, dict) or not hashes: raise ValueError('Missing release hashes')
    if schema == 'daily-text-release-1' and set(hashes) != {'train.jsonl', 'validation.jsonl', 'added_train.jsonl',
            'candidates.jsonl', 'excluded.jsonl', 'duplicates.jsonl', 'changes.json', 'handoff.json'}:
        raise ValueError('Invalid daily release artifact list')
    if schema == 'provisional-corpus-1' and set(hashes) != {'provisional_text.jsonl', 'source_bundles.jsonl', 'excluded.jsonl'}:
        raise ValueError('Invalid provisional artifact list')
    for name, sha in hashes.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or file_hash(path) != sha:
            raise ValueError('Release artifact changed or escaped root')
    if schema == 'daily-text-release-1':
        ledger = jsonl(root / 'candidates.jsonl')
        by_id = {record['record_id']: record for record in ledger}
        if len(by_id) != len(ledger) or not ledger: raise ValueError('Invalid daily candidate ledger')
        aliases = {}
        for record in ledger:
            identity = record['source_identity']
            sid = f"{identity['doc_id']}_{identity['raw_sha256']}_p{identity['page_number']:06d}"
            if record['record_id'] != sid or record['text_sha256'] != digest(record['text'].encode()) or record['split'] not in {'train', 'validation', 'test'}:
                raise ValueError('Invalid daily source/text/split identity')
            if reasons(record, manifest['policy']): raise ValueError('Daily ledger contains filtered text')
            for key in (('doc', identity['doc_id']), ('raw', identity['raw_sha256']), ('url', record['source_url'])):
                if aliases.setdefault(key, record['split']) != record['split']: raise ValueError('Daily source family crosses splits')
        group(ledger)
        retained = []
        counts = {}
        for split in ('train', 'validation'):
            rows = jsonl(root / f'{split}.jsonl'); counts[split] = len(rows)
            for row in rows:
                original = by_id.get(row['record_id'])
                if not original or row['text_sha256'] != original['text_sha256'] or row['text'] != original['text'] or row['split'] != split or original['split'] != split:
                    raise ValueError('Daily split differs from candidate ledger')
                if row.get('schema_version') != 'daily-text-candidate-1' or row.get('experimental_training_eligible') is not (split == 'train'):
                    raise ValueError('Invalid candidate eligibility')
                verified = row.get('source_review_status') == 'human_verified'
                if row.get('training_approved') is not (verified and split == 'train') or row.get('review_required') is not (not verified):
                    raise ValueError('Candidate misrepresents verification')
            retained.extend(rows)
        if len({row['record_id'] for row in retained}) != len(retained) or any(len(members) > 1 for members in group(retained)):
            raise ValueError('Daily split retains duplicate text')
        changes = json.loads((root / 'changes.json').read_text())
        previous_content = set(changes['previous_train_content_sha256'])
        expected_added = [row for row in retained if row['split'] == 'train' and content_key(row['text']) not in previous_content]
        added = jsonl(root / 'added_train.jsonl')
        if added != expected_added: raise ValueError('Daily delta disagrees with cumulative training text')
        counts.update(added_train=len(added), quarantined=len(jsonl(root / 'excluded.jsonl')))
        if counts != manifest['counts']: raise ValueError('Daily counts disagree with artifacts')
        release_id = digest(encode({'policy': manifest['policy'], 'previous': manifest['previous_release_id'],
                                   'files': {name: sha for name, sha in hashes.items() if name != 'handoff.json'}}))
        if release_id != manifest['release_id']: raise ValueError('Daily release ID mismatch')
        handoff = json.loads((root / 'handoff.json').read_text())
        if handoff['release_id'] != release_id or handoff['continual_checkpoint_must_have_consumed_release'] != manifest['previous_release_id']:
            raise ValueError('Invalid training handoff lineage')
        if handoff['input_sha256'] != {name: hashes[name] for name in ('train.jsonl', 'added_train.jsonl', 'validation.jsonl')}:
            raise ValueError('Invalid training handoff checksums')
    return manifest


def reasons(record, policy):
    text = clean(record['text'])
    issues = []
    if len(''.join(text.split())) < policy['min_characters']: issues.append('short_text')
    letters = [c for c in text if c.isalpha()]
    ratio = sum('\u0d80' <= c <= '\u0dff' for c in letters) / len(letters) if letters else 0
    if ratio < policy['min_sinhala_letter_ratio']: issues.append('little_sinhala_or_legacy_font')
    if '\ufffd' in text or '[UNREADABLE]' in text: issues.append('invalid_or_unreadable_text')
    if any(unicodedata.category(c) == 'Cc' and c not in '\n\r\t' for c in text): issues.append('control_character')
    issues.extend(flags(text))
    if record['source_review_status'] != 'human_verified':
        if record.get('method') == 'ocr' and (record.get('prediction_outcome') != 'predicted' or record.get('completion_status') != 'complete'):
            issues.append('incomplete_or_unverified_ocr')
        issues.extend(record.get('quality_flags', []))
    return sorted(set(issues))


def build(output, *, provisional_roots=(), reviewed_roots=(), previous=None, policy=None, replace_existing=False):
    output = Path(output)
    policy = {**POLICY, **(policy or {})}
    if set(policy) != set(POLICY) or policy['version'] != POLICY['version']: raise ValueError('Unknown daily policy')
    if type(policy['min_characters']) is not int or policy['min_characters'] < 1 or type(policy['max_candidates']) is not int or policy['max_candidates'] < 1:
        raise ValueError('Character/candidate limits must be positive integers')
    if type(policy['validation_percent']) is not int or not 0 <= policy['validation_percent'] <= 100:
        raise ValueError('Validation percent must be between 0 and 100')
    if not isinstance(policy['split_seed'], str) or not policy['split_seed'].strip(): raise ValueError('Empty split seed')
    if isinstance(policy['min_sinhala_letter_ratio'], bool) or not isinstance(policy['min_sinhala_letter_ratio'], (int, float)) or not 0 <= policy['min_sinhala_letter_ratio'] <= 1:
        raise ValueError('Invalid Sinhala letter ratio')
    if policy['near_threshold'] != POLICY['near_threshold'] or policy['near_minimum_words'] != POLICY['near_minimum_words']:
        raise ValueError('Deduplication rule changes need a new release policy version')
    candidates, prior_train, prior_ids, prior_train_ids, inputs = {}, set(), set(), set(), []
    previous_id, replacements, snapshots = None, [], []
    if previous:
        previous = Path(previous)
        if output.resolve().is_relative_to(previous.resolve()): raise ValueError('Daily output must be outside previous release')
        old = verify(previous)
        if {k:v for k,v in old['policy'].items() if k != 'max_candidates'} != {k:v for k,v in policy.items() if k != 'max_candidates'}:
            raise ValueError('Policy changed within a release lineage; start a separate lineage explicitly')
        previous_id = old['release_id']
        for record in jsonl(previous / 'candidates.jsonl'):
            candidates[record['record_id']] = record; prior_ids.add(record['record_id'])
        prior_training = jsonl(previous / 'train.jsonl')
        prior_train = {content_key(record['text']) for record in prior_training}
        prior_train_ids = {record['record_id'] for record in prior_training}
        sha = file_hash(previous / 'manifest.json')
        inputs.append({'kind': 'previous', 'manifest_sha256': sha})
        snapshots.append((previous, 'previous', sha))
    for kind, roots in (('provisional', provisional_roots), ('reviewed', reviewed_roots)):
        for root in roots:
            root = Path(root).resolve()
            if output.resolve().is_relative_to(root): raise ValueError('Daily output must be outside input releases')
            if kind == 'provisional':
                manifest = verify(root, 'provisional-corpus-1')
                rows = jsonl(root / 'provisional_text.jsonl')
            else:
                reviewed.verify_release(root)
                manifest = json.loads((root / 'manifest.json').read_text())
                rows = jsonl(root / 'train.jsonl') + jsonl(root / 'validation.jsonl') + jsonl(root / 'test.jsonl')
            sha = file_hash(root / 'manifest.json')
            snapshots.append((root, kind, sha)); inputs.append({'kind': kind, 'manifest_sha256': sha})
            for row in rows:
                if row.get('text_sha256') != digest(row['text'].encode('utf-8')): raise ValueError('Input text hash mismatch')
                expected_schema = 'provisional-corpus-text-1' if kind == 'provisional' else 'reviewed-training-text-1'
                if row.get('schema_version') != expected_schema: raise ValueError('Unexpected input record schema')
                if kind == 'provisional' and (row.get('training_approved') is not False or row.get('review_required') is not True):
                    raise ValueError('Provisional record misrepresents approval')
                identity = row['source_identity']
                sid = f"{identity['doc_id']}_{identity['raw_sha256']}_p{identity['page_number']:06d}"
                if row['record_id'] != sid: raise ValueError('Record ID disagrees with source identity')
                normalized, watermark_lines = normalize(row['text'])
                record = {**row, 'text': normalized, 'source_review_status': 'human_verified' if kind == 'reviewed' else 'provisional',
                          'normalization': {'version': 'daily-text-normalization-1', 'scanner_footer_lines_removed': watermark_lines,
                                            'input_text_sha256': row['text_sha256']},
                          'input_manifest_sha256': sha, 'quality_flags': row.get('quality_flags', row.get('original_quality_flags', []))}
                record['text_sha256'] = digest(record['text'].encode('utf-8'))
                if kind == 'reviewed': record['inherited_split'] = row['split']
                current = candidates.get(sid)
                if current:
                    if current['source_review_status'] == 'human_verified' and kind == 'provisional': continue
                    if content_key(current['text']) != content_key(record['text']):
                        if kind != 'reviewed' and not replace_existing:
                            raise ValueError('Changed text for an existing page requires explicit --replace-existing')
                        replacements.append({'record_id': sid, 'previous_text_sha256': current['text_sha256'], 'text_sha256': record['text_sha256']})
                    if current.get('split'): record['split'] = current['split']
                    if current.get('inherited_split') and record.get('inherited_split', current['inherited_split']) != current['inherited_split']:
                        raise ValueError('Conflicting reviewed splits')
                candidates[sid] = record
    if not candidates: raise ValueError('No daily text candidates')
    if len(candidates) > policy['max_candidates']: raise ValueError('Candidate limit exceeded; raise the explicit limit or use a separate lineage')
    accepted, excluded = [], []
    for sid, record in sorted(candidates.items()):
        issues = reasons(record, policy)
        if issues:
            excluded.append({'record_id': sid, 'reasons': issues, 'source_identity': record['source_identity']})
        else: accepted.append(record)
    if not accepted: raise ValueError('All candidates quarantined; no training release written')
    parents = list(range(len(accepted)))
    def find(i):
        while parents[i] != i: parents[i] = parents[parents[i]]; i = parents[i]
        return i
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parents[max(a, b)] = min(a, b)
    aliases = {}
    for i, record in enumerate(accepted):
        identity = record['source_identity']
        for key in (('doc', identity['doc_id']), ('raw', identity['raw_sha256']), ('url', record['source_url'])):
            if not key[1]: raise ValueError('Missing source identity/URL')
            if key in aliases: union(i, aliases[key])
            aliases[key] = i
    duplicates = group([{**record, 'split': 'all'} for record in accepted])
    for members in duplicates:
        for i in members[1:]: union(members[0], i)
    families = {}
    for i in range(len(accepted)): families.setdefault(find(i), []).append(i)
    for members in families.values():
        inherited = {accepted[i][key] for i in members for key in ('split', 'inherited_split') if accepted[i].get(key)}
        if len(inherited) > 1: raise ValueError('New source/duplicate links bridge inherited splits; release blocked')
        canonical = min(accepted[i]['source_identity']['doc_id'] for i in members)
        bucket = int(digest(f"{policy['split_seed']}:{canonical}".encode())[:16], 16) % 100
        split = next(iter(inherited)) if inherited else 'validation' if bucket < policy['validation_percent'] else 'train'
        if split == 'test':
            for i in members: accepted[i]['split'] = 'test'
        elif split in {'train', 'validation'}:
            for i in members: accepted[i]['split'] = split
        else: raise ValueError('Invalid inherited split')
    retained, duplicate_rows = [], []
    for members in duplicates:
        winner = min(members, key=lambda i: (accepted[i]['source_review_status'] != 'human_verified',
                                            accepted[i]['record_id'] not in prior_ids, accepted[i]['record_id']))
        record = accepted[winner]
        if record['split'] != 'test': retained.append(record)
        for i in members:
            if i != winner: duplicate_rows.append({'record_id': accepted[i]['record_id'], 'duplicate_of': record['record_id']})
    def training_record(record):
        return {**record, 'schema_version': 'daily-text-candidate-1', 'experimental_training_eligible': record['split'] == 'train',
                'training_approved': record['source_review_status'] == 'human_verified' and record['split'] == 'train',
                'review_required': record['source_review_status'] != 'human_verified'}
    retained = [training_record(record) for record in sorted(retained, key=lambda row: row['record_id'])]
    train = [record for record in retained if record['split'] == 'train']
    validation = [record for record in retained if record['split'] == 'validation']
    added = [record for record in train if content_key(record['text']) not in prior_train]
    changes = {'added_train_records': len(added), 'cumulative_train_records': len(train),
               'added_record_ids': [record['record_id'] for record in added],
               'replacements': replacements,
               'removed_train_record_ids': sorted(prior_train_ids - {record['record_id'] for record in train}),
               'previous_train_content_sha256': sorted(prior_train),
               'previous_release_id': previous_id, 'reserved_test_pages': sum(record['split'] == 'test' for record in accepted)}
    files = {'train.jsonl': b''.join(encode(record) for record in train),
             'validation.jsonl': b''.join(encode(record) for record in validation),
             'added_train.jsonl': b''.join(encode(record) for record in added),
             'candidates.jsonl': b''.join(encode(record) for record in accepted),
             'excluded.jsonl': b''.join(encode(record) for record in excluded),
             'duplicates.jsonl': b''.join(encode(record) for record in duplicate_rows), 'changes.json': encode(changes)}
    release_id = digest(encode({'policy': policy, 'previous': previous_id, 'files': {name: digest(data) for name, data in files.items()}}))
    files['handoff.json'] = encode({'schema_version': 'daily-training-handoff-1', 'release_id': release_id,
        'task': 'text_domain_adaptation', 'data_status': 'experimental_candidates_with_review_status',
        'fresh_base_input': 'train.jsonl', 'continual_input': 'added_train.jsonl',
        'continual_checkpoint_must_have_consumed_release': previous_id,
        'validation_input': 'validation.jsonl', 'input_sha256': {name: digest(files[name]) for name in ('train.jsonl', 'added_train.jsonl', 'validation.jsonl')},
        'new_training_records': len(added), 'training_run_required_fields': ['base_model_id', 'base_model_revision',
        'loaded_parameter_count', 'dataset_release_id', 'dataset_input_sha256', 'training_config_sha256',
        'parent_checkpoint_sha256', 'output_checkpoint_sha256', 'evaluation_run_id'],
        'note': 'No model was trained. Text candidates do not supply MCQ answers. Zero delta means no novel training text.'})
    manifest = {'schema_version': 'daily-text-release-1', 'release_id': release_id, 'previous_release_id': previous_id,
                'policy': policy, 'inputs': sorted(inputs, key=lambda row: (row['kind'], row['manifest_sha256'])),
                'counts': {'train': len(train), 'validation': len(validation), 'added_train': len(added), 'quarantined': len(excluded)},
                'review_status': dict(Counter(record['source_review_status'] for record in retained)),
                'missing_metadata': {field: sum(not record.get('metadata_hints', {}).get(field) for record in retained)
                                     for field in ('subject', 'domain', 'grade', 'language', 'license')},
                'code_sha256': file_hash(Path(__file__)), 'output_sha256': {name: digest(data) for name, data in files.items()},
                'accuracy_note': 'Automatic filtering is not measured accuracy or human verification. Hidden benchmark questions must never be supplied.'}
    for root, kind, sha in snapshots:
        if file_hash(root / 'manifest.json') != sha: raise ValueError('Input release changed while building')
        if kind == 'reviewed': reviewed.verify_release(root)
        elif kind == 'previous': verify(root)
        else: verify(root, 'provisional-corpus-1')
    publish(output, {**files, 'manifest.json': encode(manifest)})
    verify(output)
    return {'output': str(output), **manifest}
