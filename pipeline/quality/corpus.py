"""Offline corpus review coverage and correction diagnostics, never auto-approval."""
from collections import Counter, defaultdict
from pathlib import Path
import unicodedata

from pipeline.cleaning.native import clean
from pipeline.dataset import reviewed
from pipeline.dataset.native import digest, encode, publish
from pipeline.deduplication.grouping import group
from pipeline.download.downloader import file_hash
from pipeline.quality.ocr_benchmark import edit_distance
from pipeline.quality.text import flags


UNKNOWN = '(unknown)'


def report(packet, max_metric_cells=1_000_000, total_metric_cells=5_000_000,
           max_dedup_pages=1000):
    """Verify evidence and report blockers without changing decisions or drafts.

    Approved corrections were edited from predictions, so distances measure editing
    burden on this selected set, not independent OCR CER/WER or held-out accuracy.
    """
    packet = Path(packet)
    for limit in (max_metric_cells, total_metric_cells, max_dedup_pages):
        if type(limit) is not int or limit < 1:
            raise ValueError('Quality computation limits must be positive integers')
    initial_csv_sha = file_hash(packet / 'review.csv')
    manifest, records, reviews = reviewed.load(packet, validate_approved=False)
    by_id = {row['record_id']: row for row in reviews}
    inputs = {'review.csv': initial_csv_sha, 'manifest.json': file_hash(packet / 'manifest.json'),
              **manifest['immutable_sha256']}
    rows, valid, invalid, groups = [], [], [], defaultdict(list)
    coverage = {name: Counter() for name in ('subject', 'domain', 'grade', 'language', 'license', 'source', 'method', 'backend')}
    approved_coverage = {name: Counter() for name in coverage}
    original_flags, draft_flags, completions, outcomes = Counter(), Counter(), Counter(), Counter()
    metrics = {name: {'scored_pages': 0, 'skipped_pages': 0, 'edits': 0, 'reference_units': 0}
               for name in ('characters', 'words')}
    remaining = total_metric_cells
    for record in records:
        sid = record['record_id']
        source, review = record['source_record'], by_id[sid]
        text_bytes = (packet / record['text_path']).read_bytes()
        inputs[record['text_path']] = digest(text_bytes)
        draft = text_bytes.decode('utf-8')
        original, corrected = clean(source['text']), clean(draft)
        metadata = source['metadata_hints']
        hint_values = {field: metadata.get(field) or UNKNOWN
                       for field in ('subject', 'domain', 'grade', 'language', 'license')}
        hint_values.update(source=source.get('source') or UNKNOWN, method=source['method'],
                           backend=source.get('ocr_backend') or '(not OCR)')
        for field, value in hint_values.items(): coverage[field][value] += 1
        warnings = list(source['quality_flags'])
        current_flags = flags(corrected)
        if not corrected.strip(): current_flags.append('empty_draft')
        if '[UNREADABLE]' in corrected: current_flags.append('unreadable_draft')
        if '\ufffd' in corrected: current_flags.append('replacement_character')
        if any(unicodedata.category(c) == 'Cc' and c not in '\n\t\r' for c in corrected):
            current_flags.append('control_character')
        original_flags.update(set(warnings)); draft_flags.update(set(current_flags))
        prediction = source.get('prediction', {})
        completion = prediction.get('completion_status') or '(not recorded)'
        if source['method'] == 'ocr':
            completions[completion] += 1
            outcomes[prediction.get('outcome') or '(not recorded)'] += 1
        identity = source['identity']
        document_key = (identity['doc_id'], identity['raw_sha256'])
        groups[document_key].append(identity['page_number'])
        row = {'record_id': sid, 'decision': review['decision'], 'method': source['method'],
               'subject_hint': metadata.get('subject') or UNKNOWN,
               'original_quality_flags': warnings, 'draft_quality_flags': current_flags,
               'completion_status': completion, 'edited': original != corrected,
               'approval_valid': False, 'approval_error': None, 'correction_distances': {}}
        if review['decision'] == 'approve':
            try:
                reviewed.validate_approval(review, draft)
            except ValueError as exc:
                row['approval_error'] = str(exc)
                invalid.append({'record_id': sid, 'error': str(exc)})
            else:
                row['approval_valid'] = True
                for field, value in hint_values.items(): approved_coverage[field][value] += 1
                item = {'record_id': sid, 'text': corrected, 'split': review['split'],
                        'identity': identity, 'source_url': source['source_url']}
                valid.append(item)
                for name, reference, extracted in (
                    ('characters', corrected, original),
                    ('words', corrected.split(), original.split()),
                ):
                    cells = len(reference) * len(extracted)
                    result = {'reference_units': len(reference), 'edits': None, 'edit_rate': None}
                    if not reference:
                        result['skip_reason'] = 'empty_reference'
                        metrics[name]['skipped_pages'] += 1
                    elif reference == extracted or not extracted:
                        result['edits'] = 0 if reference == extracted else len(reference)
                    elif cells > max_metric_cells or cells > remaining:
                        result['skip_reason'] = 'computation_budget'
                        metrics[name]['skipped_pages'] += 1
                    else:
                        result['edits'] = edit_distance(reference, extracted)
                        remaining -= cells
                    if result['edits'] is not None:
                        result['edit_rate'] = result['edits'] / len(reference)
                        metrics[name]['scored_pages'] += 1
                        metrics[name]['edits'] += result['edits']
                        metrics[name]['reference_units'] += len(reference)
                    row['correction_distances'][name] = result
        rows.append(row)

    split_conflicts, source_splits = [], defaultdict(set)
    for item in valid:
        identity = item['identity']
        for kind, value in (('document', identity['doc_id']), ('raw', identity['raw_sha256']), ('url', item['source_url'])):
            source_splits[(kind, value)].add(item['split'])
    for (kind, value), splits in sorted(source_splits.items()):
        if len(splits) > 1:
            split_conflicts.append({'kind': kind, 'value': value, 'splits': sorted(splits)})
    duplicates, duplicate_error = [], None
    dedup_checked = len(valid) <= max_dedup_pages
    if dedup_checked:
        try:
            duplicates = [[valid[i]['record_id'] for i in members] for members in group(valid) if len(members) > 1]
        except ValueError as exc:
            duplicate_error = str(exc)
    blockers = []
    if invalid: blockers.append('invalid_approvals')
    if split_conflicts: blockers.append('source_split_conflicts')
    if duplicate_error: blockers.append('duplicate_split_conflict')
    if not valid: blockers.append('no_valid_approvals')
    if not dedup_checked: blockers.append('deduplication_preflight_deferred')
    for values in metrics.values():
        denominator = values['reference_units']
        values['edit_rate'] = values['edits'] / denominator if denominator else None
    # Reject a changing review snapshot instead of publishing mismatched evidence.
    for name, expected in inputs.items():
        if file_hash(packet / name) != expected:
            raise ValueError('Review packet changed during quality reporting; stop its writer and retry')
    priority = sorted(rows, key=lambda row: (not bool(row['approval_error']), row['decision'] != 'pending',
                      not bool(row['original_quality_flags'] or row['draft_quality_flags']), row['record_id']))
    return {'schema_version': 'corpus-quality-report-1', 'report_code_sha256': file_hash(Path(__file__)),
            'component_code_sha256': {name: file_hash(Path(function.__code__.co_filename)) for name, function in
                                      (('cleaning', clean), ('review_contract', reviewed.validate_approval),
                                       ('edit_distance', edit_distance), ('deduplication', group), ('warnings', flags))},
            'input_sha256': inputs, 'pages': len(records),
            'documents': len({key[0] for key in groups}), 'source_document_versions': len(groups),
            'decisions': dict(Counter(row['decision'] for row in reviews)),
            'valid_approvals': len(valid), 'invalid_approvals': invalid,
            'edited_pending_pages': sum(row['decision'] == 'pending' and row['edited'] for row in rows),
            'coverage_hints': {key: dict(sorted(values.items())) for key, values in coverage.items()},
            'approved_coverage_hints': {key: dict(sorted(values.items())) for key, values in approved_coverage.items()},
            'original_quality_flags': dict(original_flags), 'draft_quality_flags': dict(draft_flags),
            'ocr_completion_statuses': dict(completions), 'ocr_outcomes': dict(outcomes), 'correction_distances': metrics,
            'metric_limits': {'max_cells_per_comparison': max_metric_cells, 'total_cells': total_metric_cells,
                              'used_cells': total_metric_cells - remaining},
            'page_coverage': [{'doc_id': key[0], 'raw_sha256': key[1], 'selected_pages': sorted(numbers),
                               'complete_document_verified': False} for key, numbers in sorted(groups.items())],
            'export_preflight': {'status': 'blocked' if blockers else 'checks_passed', 'blockers': blockers,
                                 'source_split_conflicts': split_conflicts, 'duplicate_groups': duplicates,
                                 'duplicate_split_error': duplicate_error, 'deduplication_checked': dedup_checked,
                                 'max_dedup_pages': max_dedup_pages},
            'review_queue': [row['record_id'] for row in priority if row['decision'] == 'pending' or row['approval_error']],
            'records': rows, 'accuracy_note': 'Correction distances are editing burden on selected approved corrections, '
            'not independent OCR accuracy. No source/style accuracy or automatic acceptance is established. '
            'Character units are NFC Unicode codepoints; words are whitespace tokens. Metadata remains unverified.'}


def markdown(result):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    lines = ['# Corpus quality report', '', result['accuracy_note'], '',
             f"Pages: {result['pages']}; documents: {result['documents']}; valid approvals: {result['valid_approvals']}.",
             f"Export preflight: **{result['export_preflight']['status']}**.", '',
             'Blockers: ' + (', '.join(result['export_preflight']['blockers']) or 'none; exporter still performs its own checks'),
             '', '## Review decisions', '', '| Decision | Pages |', '| --- | ---: |']
    lines += [f'| {cell(key)} | {value} |' for key, value in sorted(result['decisions'].items())]
    lines += ['', '## Subject coverage (unverified hints)', '', '| Subject | Pages |', '| --- | ---: |']
    lines += [f'| {cell(key)} | {value} |' for key, value in result['coverage_hints']['subject'].items()]
    lines += ['', '## Correction burden', '', '| Unit | Scored pages | Skipped pages | Edits | Reference units | Edit rate |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name, metric in result['correction_distances'].items():
        rate = f"{metric['edit_rate']:.4f}" if metric['edit_rate'] is not None else 'unavailable'
        lines.append(f"| {name} | {metric['scored_pages']} | {metric['skipped_pages']} | {metric['edits']} | {metric['reference_units']} | {rate} |")
    lines += ['', 'These rates can exceed 1 for insertion-heavy output. Missing/budget-skipped pages are excluded from the denominator.',
              '', '## Review queue', '', 'Invalid approvals first, then pending pages with warnings. See report.json for all records.', '']
    by_id = {row['record_id']: row for row in result['records']}
    for sid in result['review_queue'][:100]:
        row = by_id[sid]
        reason = row['approval_error'] or ', '.join(row['original_quality_flags'] + row['draft_quality_flags']) or 'pending source review'
        lines.append(f'- {cell(sid)}: {cell(reason)}')
    if len(result['review_queue']) > 100: lines.append('- Remaining queue entries are in report.json.')
    lines += ['', 'Selected pages do not prove whole-document completeness. Source images, equations, numbers, options and reading order still require human checking.', '']
    return '\n'.join(lines)


def write(packet, output, **limits):
    packet, output = Path(packet).resolve(), Path(output).resolve()
    if output == packet or output.is_relative_to(packet):
        raise ValueError('Quality reports must be stored outside the review packet')
    result = report(packet, **limits)
    publish(output, {'report.json': encode(result), 'report.md': markdown(result).encode('utf-8')})
    return result
