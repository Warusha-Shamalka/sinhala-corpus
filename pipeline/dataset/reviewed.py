"""Source-image review and corrected text releases for native or OCR corpus pages."""
import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path
import unicodedata
from html import escape
from urllib.parse import urlsplit

from pipeline.cleaning.native import clean
from pipeline.dataset.native import digest, encode, publish
from pipeline.processing.pages import verify_page
from pipeline.download.downloader import file_hash
from pipeline.deduplication.grouping import group as dedup_groups

FIELDS = ['record_id', 'decision', 'transcriber', 'verifier', 'source_checked',
          'equations_checked', 'layout_checked', 'rights_evidence', 'notes', 'split', 'reviewed_text_sha256']


def write_reviews(path, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader(); writer.writerows(rows)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(stream.getvalue(), encoding='utf-8')
    temporary.replace(path)


def prepare(root, output, config_hash=None):
    records, files, reviews, identities = [], {}, [], set()
    for manifest_path in sorted(root.rglob('manifest.json')):
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('schema_version') != 'corpus-page-bundle-1':
            continue
        if config_hash and manifest['identity'].get('processing_config_sha256') != config_hash:
            continue
        record = verify_page(manifest_path.parent, manifest['identity'])
        identity = record['identity']
        sid = f"{identity['doc_id']}_{identity['raw_sha256']}_p{identity['page_number']:06d}"
        if sid in identities:
            raise ValueError('Multiple processing versions for a page; choose a single version root')
        identities.add(sid)
        text_path = f'texts/{sid}.txt'
        artifact = 'source.html' if record['method'] == 'html' else 'page.png'
        image_path = f'sources/{sid}.html' if record['method'] == 'html' else f'images/{sid}.png'
        # Native and OCR source images have already been frozen in verified bundles.
        files[text_path] = record['text'].encode('utf-8')
        files[image_path] = manifest_path.parent / artifact
        full_record_sha = digest(encode(record))
        summary = {**record}
        if 'prediction' in summary:
            summary['prediction'] = {k: v for k, v in record['prediction'].items() if k in {'text', 'outcome', 'completion_status', 'error'}}
        records.append({'record_id': sid, 'source_record': summary, 'source_record_full_sha256': full_record_sha,
                        'source_bundle_path': str(manifest_path.parent.resolve()),
                        'text_path': text_path, 'image_path': image_path,
                        'source_bundle_manifest_sha256': digest(manifest_path.read_bytes())})
        reviews.append({**dict.fromkeys(FIELDS, ''), 'record_id': sid, 'decision': 'pending',
                        'source_checked': 'false', 'equations_checked': 'false', 'layout_checked': 'false'})
    if not records:
        raise ValueError('No processed corpus pages')
    # publish() currently accepts top-level names; store nested paths as artifacts too.
    files['records.jsonl'] = b''.join(encode(r) for r in records)
    immutable = {'records.jsonl': digest(files['records.jsonl']),
                 **{r['image_path']: file_hash(files[r['image_path']]) for r in records}}
    sections = []
    for record in records:
        source = record['source_record']
        sid = record['record_id']
        image = f'<a href="{escape(record["image_path"])}"><img loading="lazy" src="{escape(record["image_path"])}" alt="Source page"></a>' if source['method'] != 'html' else '<p>Static HTML source: compare the text with the saved source and original page.</p>'
        url = source['source_url']
        link = f'<a href="{escape(url, quote=True)}" target="_blank" rel="noreferrer">Original public source</a>' if urlsplit(url).scheme in {'http', 'https'} else ''
        sections.append(f'<section><h2>{escape(sid)}</h2><p>{link} · <a href="{escape(record["text_path"])}">Editable text file</a></p>'
                        f'<p>Warnings: {escape(", ".join(source["quality_flags"]) or "none; review still required")}</p>'
                        f'<div class="pair">{image}<pre>{escape(source["text"])}</pre></div></section>')
    index = '<!doctype html><meta charset="utf-8"><title>Corpus page review</title><style>body{font-family:sans-serif;margin:2em}section{border-bottom:1px solid #ccc;padding:1em 0}.pair{display:flex;gap:2em}.pair>*{width:50%}img{max-width:100%}pre{white-space:pre-wrap;line-height:1.7}</style><h1>Source and initial extraction</h1><p>Nothing is training-approved here. Edit the linked text files, then have two people compare the full source, equations and reading order before approval. This view shows the initial extraction, not later edits.</p>' + ''.join(sections)
    files['index.html'] = index.encode('utf-8')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(reviews)
    files['review.csv'] = stream.getvalue().encode()
    files['manifest.json'] = encode({'schema_version': 'corpus-review-1', 'pages': len(records), 'immutable_sha256': immutable,
                                    'training_approved': False})
    publish(output, files)
    return {'packet': str(output), 'pages': len(records), 'approved': 0}


def load(packet, unchecked=None, validate_approved=True):
    manifest = json.loads((packet / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'corpus-review-1':
        raise ValueError('Invalid corpus review manifest')
    records = [json.loads(line) for line in (packet / 'records.jsonl').read_text(encoding='utf-8').splitlines()]
    expected_paths = {'records.jsonl', *(r['image_path'] for r in records)}
    hashes = manifest.get('immutable_sha256', {})
    if set(hashes) != expected_paths:
        raise ValueError('Invalid immutable artifact list')
    for name, sha in hashes.items():
        path = (packet / name).resolve()
        if not path.is_relative_to(packet.resolve()) or digest(path.read_bytes()) != sha:
            raise ValueError('Review source artifact changed or escaped packet')
    with (packet / 'review.csv').open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('Invalid review schema')
        reviews = list(reader)
    by_id = {r['record_id']: r for r in reviews}
    if len(by_id) != len(reviews) or len(by_id) != len(records) or set(by_id) != {r['record_id'] for r in records}:
        raise ValueError('Review IDs must match source pages')
    for record in records:
        path = (packet / record['text_path']).resolve()
        if not path.is_relative_to(packet.resolve()) or not path.is_file():
            raise ValueError('Missing review text or path escape')
        review = by_id[record['record_id']]
        if None in review or any(v is None for v in review.values()) or review['decision'] not in {'pending', 'reject', 'approve'}:
            raise ValueError('Invalid review decision')
        if validate_approved and review['decision'] == 'approve' and record['record_id'] != unchecked:
            text = path.read_text(encoding='utf-8')
            validate_approval(review, text)
    return manifest, records, reviews


def validate_approval(review, text):
    for key in ('transcriber', 'verifier', 'rights_evidence', 'notes'):
        if not review[key].strip():
            raise ValueError(f'Approval requires {key}')
    if review['transcriber'].strip().casefold() == review['verifier'].strip().casefold():
        raise ValueError('Two different reviewers are required')
    if any(review[k] != 'true' for k in ('source_checked', 'equations_checked', 'layout_checked')):
        raise ValueError('Entire source, equations and reading order must be checked')
    if not text.strip() or '[UNREADABLE]' in text or '\ufffd' in text or any(unicodedata.category(c) == 'Cc' and c not in '\n\t\r' for c in text):
        raise ValueError('Reviewed text is empty, unreadable or contains invalid characters')
    if review['split'] not in {'train', 'validation', 'test'}:
        raise ValueError('Approved page needs an explicit split')
    if review['reviewed_text_sha256'] != digest(text.encode()):
        raise ValueError('Reviewed text changed since approval')


def seal(packet, record_id, transcriber, verifier, rights_evidence, notes, split):
    _, records, reviews = load(packet, unchecked=record_id)
    record = next((r for r in records if r['record_id'] == record_id), None)
    if record is None:
        raise ValueError('Unknown record ID')
    text = (packet / record['text_path']).read_text(encoding='utf-8')
    row = next(r for r in reviews if r['record_id'] == record_id)
    row.update(decision='approve', transcriber=transcriber, verifier=verifier, rights_evidence=rights_evidence,
               notes=notes, split=split, source_checked='true', equations_checked='true', layout_checked='true',
               reviewed_text_sha256=digest(text.encode()))
    validate_approval(row, text)
    write_reviews(packet / 'review.csv', reviews)
    return {'record_id': record_id, 'decision': 'approve', 'reviewed_text_sha256': row['reviewed_text_sha256']}


def export(packet, output):
    manifest, records, reviews = load(packet)
    by_id = {r['record_id']: r for r in reviews}
    approved, groups, hashes, duplicates = [], {}, {}, []
    files = {}
    for record in records:
        review = by_id[record['record_id']]
        if review['decision'] != 'approve':
            continue
        source = record['source_record']
        identity = source['identity']
        text = clean((packet / record['text_path']).read_text(encoding='utf-8'))
        sha = digest(text.encode())
        split = review['split']
        for source_key in (('raw', identity['raw_sha256']), ('document', identity['doc_id']), ('url', source['source_url'])):
            if groups.setdefault(source_key, split) != split:
                raise ValueError('Source document or source version crosses splits')
        if sha in hashes:
            if hashes[sha]['split'] != split:
                raise ValueError('Identical text crosses splits')
            duplicates.append({'record_id': record['record_id'], 'duplicate_of': hashes[sha]['record_id']})
            continue
        item = {'schema_version': 'reviewed-training-text-1', 'record_id': record['record_id'], 'text': text,
                'text_sha256': sha, 'source_identity': identity, 'source_url': source['source_url'], 'source': source['source'],
                'metadata_hints': source['metadata_hints'], 'method': source['method'], 'ocr_backend': source.get('ocr_backend'),
                'model_revision': source.get('model_revision'), 'source_image_sha256': source.get('image_sha256'),
                'model_id': source.get('model_id'), 'source_artifact_sha256': source.get('source_artifact_sha256'),
                'source_record_sha256': record['source_record_full_sha256'], 'original_quality_flags': source['quality_flags'],
                'human_corrected': text != clean(source['text']), 'review': review, 'split': split,
                'training_approved': split == 'train'}
        hashes[sha] = item; approved.append(item)
        files[record['text_path']] = (packet / record['text_path']).read_bytes()
    if not approved:
        raise ValueError('No approved pages; no training dataset was written')
    retained = []
    for members in dedup_groups(approved):
        representative = approved[members[0]]
        representative['deduplication_group'] = representative['record_id']
        retained.append(representative)
        for i in members[1:]:
            duplicates.append({'record_id': approved[i]['record_id'], 'duplicate_of': representative['record_id'], 'reason': 'near_or_whitespace_duplicate'})
    approved = retained
    for split in ('train', 'validation', 'test'):
        files[f'{split}.jsonl'] = b''.join(encode(r) for r in approved if r['split'] == split)
    approved_ids = {r['record_id'] for r in records if by_id[r['record_id']]['decision'] == 'approve'}
    for record in records:
        if record['record_id'] in approved_ids:
            files[record['text_path']] = (packet / record['text_path']).read_bytes()
    files['review_evidence/records.jsonl'] = b''.join(encode(r) for r in records if r['record_id'] in approved_ids)
    evidence = io.StringIO(newline='')
    writer = csv.DictWriter(evidence, fieldnames=FIELDS); writer.writeheader()
    writer.writerows(r for r in reviews if r['record_id'] in approved_ids)
    files['review_evidence/review.csv'] = evidence.getvalue().encode()
    files['review_evidence/packet_manifest.json'] = (packet / 'manifest.json').read_bytes()
    report = {'schema_version': 'reviewed-dataset-1', 'counts': dict(Counter(r['split'] for r in approved)),
              'deduplication': {'exact': 'NFC and whitespace folded', 'near': 'word 5-gram Jaccard', 'threshold': 0.9, 'minimum_words': 30},
              'export_code_sha256': file_hash(Path(__file__)),
              'duplicates': duplicates, 'review_packet_manifest_sha256': digest(encode(manifest)),
              'output_sha256': {k: digest(v) for k, v in files.items()}}
    publish(output, {**files, 'manifest.json': encode(report)})
    verify_release(output)
    return report


def verify_release(root):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'reviewed-dataset-1':
        raise ValueError('Invalid reviewed dataset manifest')
    hashes = manifest.get('output_sha256', {})
    if not isinstance(hashes, dict) or not {'train.jsonl', 'validation.jsonl', 'test.jsonl'} <= set(hashes):
        raise ValueError('Missing dataset split hashes')
    for name, sha in hashes.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != sha:
            raise ValueError(f'Release artifact changed or escaped root: {name}')
    records, seen, counts, sources = [], set(), Counter(), {}
    for split in ('train', 'validation', 'test'):
        for line in (root / f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
            record = json.loads(line)
            if record.get('schema_version') != 'reviewed-training-text-1' or record.get('split') != split or record.get('training_approved') is not (split == 'train'):
                raise ValueError('Invalid split/training approval')
            sid = record['record_id']
            if sid in seen or record['text_sha256'] != digest(record['text'].encode()):
                raise ValueError('Duplicate record ID or invalid text hash')
            seen.add(sid)
            reviewed_path = (root / 'texts' / f'{sid}.txt').resolve()
            if not reviewed_path.is_relative_to(root.resolve()):
                raise ValueError('Text path escape')
            text = reviewed_path.read_text(encoding='utf-8')
            if record['review']['decision'] != 'approve' or clean(text) != record['text']:
                raise ValueError('Dataset differs from approved correction')
            validate_approval(record['review'], text)
            identity = record['source_identity']
            for key in (('raw', identity['raw_sha256']), ('document', identity['doc_id']), ('url', record['source_url'])):
                if sources.setdefault(key, split) != split:
                    raise ValueError('Release source versions cross splits')
            records.append(record); counts[split] += 1
    if dict(counts) != manifest['counts']:
        raise ValueError('Dataset counts disagree with manifest')
    if any(len(members) > 1 for members in dedup_groups(records)):
        raise ValueError('Release still contains duplicate groups')
    return {'status': 'verified_artifacts', 'counts': dict(counts),
            'accuracy_note': 'Artifact and review checks passed; this is not an independent accuracy measurement.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('--root', type=Path, required=True); prepare_parser.add_argument('--output', type=Path, required=True)
    prepare_parser.add_argument('--config-hash', help='Choose one processing version when multiple model runs exist')
    for name in ('status', 'export', 'approve'):
        command_parser = commands.add_parser(name)
        command_parser.add_argument('--packet', type=Path, required=True)
        if name == 'export':
            command_parser.add_argument('--output', type=Path, required=True)
        if name == 'approve':
            for field in ('record-id', 'transcriber', 'verifier', 'rights-evidence', 'notes', 'split'):
                command_parser.add_argument('--' + field, required=True)
            command_parser.add_argument('--source-equations-layout-checked', action='store_true', required=True,
                                        help='Attest that both people checked the full page, equations and reading order')
    args = vars(parser.parse_args()); action = args.pop('command')
    try:
        if action == 'status':
            _, records, rows = load(args['packet'])
            result = {'pages': len(records), 'decisions': dict(Counter(r['decision'] for r in rows))}
        else:
            args.pop('source_equations_layout_checked', None)
            result = {'prepare': prepare, 'export': export, 'approve': seal}[action](**args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        parser.exit(2, f'Review/export error: {exc}\n')


if __name__ == '__main__':
    main()
