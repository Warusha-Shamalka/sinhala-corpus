"""Route verified PDF pages to native text or replaceable OCR; preserve every result."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import time
from contextlib import redirect_stdout
import sys
import platform
import unicodedata
from uuid import uuid4

import yaml

from pipeline.cleaning.native import clean, reasons
from pipeline.dataset.native import encode, publish, visible_manifests
from pipeline.discovery.crawler import ROOT, _catalog_lock, read_catalog
from pipeline.download.downloader import file_hash, recover
from pipeline.extraction.extractor import load_settings as extraction_settings, extract_document, PopplerBackend, command
from pipeline.extraction.html import extract as extract_html
from pipeline.ocr import backends
from pipeline.ocr import images
from pipeline.ocr.ocr import png_dimensions
from pipeline.progress import ProgressReporter
from pipeline.quality.text import flags as text_flags


def fingerprint(value):
    return hashlib.sha256(encode(value)).hexdigest()


def load_settings(path):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 'pipeline-1' or not isinstance(data.get('processing'), dict):
        raise ValueError('Expected pipeline-1 with processing settings')
    settings = dict(data['processing'])
    settings.setdefault('preprocessing', {})
    settings.setdefault('max_input_pixels', 40_000_000)
    images.validate_options(settings['preprocessing'])
    for key in ('catalog_path', 'raw_root', 'output_root', 'log_root'):
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise ValueError(f'Missing path: {key}')
        settings[key] = (ROOT / settings[key]).resolve()
    for key in ('max_documents', 'max_pages', 'dpi', 'max_image_side', 'render_timeout_seconds', 'max_image_bytes', 'max_input_pixels'):
        if type(settings.get(key)) is not int or settings[key] < 1:
            raise ValueError(f'Invalid setting: {key}')
    if settings.get('ocr_mode') not in {'auto', 'all'}:
        raise ValueError('ocr_mode must be auto or all')
    if settings.get('ocr', {}).get('backend') not in backends.MODELS:
        raise ValueError('Unknown OCR backend')
    if settings['ocr'].get('revision'):
        backends.validate(settings['ocr'])
    settings['ocr'] = {**settings['ocr'], 'model_path': str((ROOT / settings['ocr']['model_path']).resolve())}
    return settings


def verify_page(folder, expected):
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'corpus-page-bundle-1' or manifest.get('identity') != expected:
        raise ValueError('Page bundle identity mismatch')
    hashes = manifest.get('output_sha256', {})
    if set(hashes) not in ({'page.json', 'page.png', 'text.txt'}, {'page.json', 'page.png', 'ocr_input.png', 'text.txt'},
                           {'page.json', 'source.html', 'text.txt'}):
        raise ValueError('Invalid page artifact list')
    for name, sha in hashes.items():
        if file_hash(folder / name) != sha:
            raise ValueError(f'Corrupt page artifact: {name}')
    record = json.loads((folder / 'page.json').read_text(encoding='utf-8'))
    if record.get('identity') != expected or record.get('schema_version') != 'corpus-page-1' or record.get('training_approved') is not False:
        raise ValueError('Invalid source page record')
    return record


def incomplete(record):
    prediction = record.get('prediction', {})
    return record.get('method') == 'ocr' and (prediction.get('outcome') != 'predicted'
            or prediction.get('completion_status') != 'complete' or not record.get('text', '').strip())


def current_pages(root):
    """Latest immutable attempt per exact source/config identity, excluding staging."""
    latest = {}
    for path in sorted(visible_manifests(root)):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('schema_version') != 'corpus-page-bundle-1': continue
        record = verify_page(path.parent, manifest['identity'])
        key = fingerprint(manifest['identity'])
        attempt = record.get('attempt', 1)
        if type(attempt) is not int or attempt < 1: raise ValueError('Invalid page attempt number')
        if key in latest and latest[key][0] == attempt:
            raise ValueError('Duplicate page attempt identity')
        if key not in latest or attempt > latest[key][0]: latest[key] = (attempt, path, record)
    return [(path, record) for _, path, record in sorted(latest.values(), key=lambda item: str(item[1]))]


def saved_attempt(folder, identity):
    candidates = ([folder] if folder.exists() else []) + sorted(folder.parent.glob(folder.name + '_attempt_*'))
    latest = None
    for path in candidates:
        record = verify_page(path, identity)
        attempt = record.get('attempt', 1)
        if type(attempt) is not int or attempt < 1: raise ValueError('Invalid page attempt number')
        if latest is None or attempt > latest[0]: latest = (attempt, path, record)
    return latest


def has_failures(report):
    return bool(report.get('errors') or any(row.get('outcome') in {'failed', 'existing_incomplete', 'truncated', 'completion_unverified', 'empty'}
                                          for row in report.get('results', [])))


def run(settings, extract_settings, *, doc_ids=None, page_numbers=None, dry_run=False, progress_mode='auto',
        engine=None, pdf_backend=None, retry_incomplete=False):
    if page_numbers and any(type(n) is not int or n < 1 for n in page_numbers):
        raise ValueError('Page numbers must be positive integers')
    rows = read_catalog(settings['catalog_path'])
    if doc_ids and set(doc_ids) - {r['doc_id'] for r in rows}:
        raise ValueError('Unknown selected document')
    jobs = [r for r in rows if (not doc_ids or r['doc_id'] in doc_ids) and r['status'] in {'DOWNLOADED', 'EXTRACTED'}
            and r['sha256'] and r['local_filename'].lower().endswith(('.pdf', '.html', '.png', '.jpg'))]
    report = {'schema_version': 'page-processing-run-1', 'planned': [r['doc_id'] for r in jobs],
              'dry_run': dry_run, 'retry_incomplete': retry_incomplete, 'results': [], 'errors': [], 'stop_reason': 'queue_finished'}
    if dry_run or not jobs:
        return report
    # Both stages must be scoped to the same verified raw source tree.
    if settings['raw_root'].resolve() != extract_settings['raw_root'].resolve():
        raise ValueError('Extraction and processing raw roots disagree')
    config = {k: v for k, v in settings.items() if not isinstance(v, Path) and k not in {'max_pages', 'max_documents'}}
    renderer = shutil.which('pdftoppm')
    if not renderer and any(r['local_filename'].lower().endswith('.pdf') for r in jobs):
        raise ValueError('pdftoppm is required')
    config['renderer_version'] = command([renderer, '-v'], timeout=settings['render_timeout_seconds'], maximum=65536).decode('utf-8', 'replace') if renderer else None
    config['schema_version'] = 'page-processing-config-1'
    config['processing_code_sha256'] = file_hash(Path(__file__))
    config['html_code_sha256'] = file_hash(Path(__file__).parents[1] / 'extraction/html.py')
    config['cleaning_code_sha256'] = file_hash(Path(__file__).parents[1] / 'cleaning/native.py')
    config['component_code_sha256'] = {name: file_hash(Path(__file__).parents[1] / name) for name in
                                       ('ocr/backends.py', 'ocr/surya_backend.py', 'ocr/neural.py', 'ocr/images.py', 'quality/text.py')}
    if settings.get('preprocessing') or any(r['local_filename'].endswith(('.png', '.jpg')) for r in jobs):
        import importlib.metadata
        config['pillow_version'] = importlib.metadata.version('Pillow')
    config['python_version'] = platform.python_version()
    config['unicode_version'] = unicodedata.unidata_version
    config['pyyaml_version'] = yaml.__version__
    config_hash = fingerprint(config)
    report['processing_config_sha256'] = config_hash
    settings['log_root'].mkdir(parents=True, exist_ok=True)
    log = settings['log_root'] / f'pages_{uuid4().hex}.json'
    progress = ProgressReporter('processing', path=log.with_suffix('.progress.json'), mode=progress_mode)
    report['progress_path'] = str(progress.path)
    report['report_path'] = str(log)
    used = 0
    new_documents = set()
    seen = {}
    try:
        with _catalog_lock(settings['catalog_path'].with_name('page-worker'), 0):
            backend = pdf_backend
            for row in jobs:
                progress.update(force=True, phase='verifying_source', item={'doc_id': row['doc_id'], 'title': row['title']})
                try:
                    receipt = recover({**row, 'status': 'DOWNLOADED'}, settings['raw_root'])
                    if receipt is None:
                        raise ValueError('Missing raw receipt')
                    if row['sha256'] in seen:
                        report['results'].append({'doc_id': row['doc_id'], 'outcome': 'duplicate_source', 'duplicate_of': seen[row['sha256']]})
                        continue
                    seen[row['sha256']] = row['doc_id']
                    if receipt.get('format', 'pdf') == 'html':
                        if page_numbers and set(page_numbers) != {1}:
                            raise ValueError('An HTML document has only page 1')
                        raw = settings['raw_root'] / receipt['artifact_path']
                        identity = {'doc_id': row['doc_id'], 'raw_sha256': row['sha256'], 'page_number': 1,
                                    'html_extraction_version': 'html-main-1', 'processing_config_sha256': config_hash}
                        folder = settings['output_root'] / row['doc_id'] / row['sha256'] / fingerprint(identity) / 'page_000001'
                        if folder.exists():
                            verify_page(folder, identity)
                            report['results'].append({'doc_id': row['doc_id'], 'page_number': 1, 'outcome': 'verified_existing', 'bundle': str(folder)})
                            continue
                        if used >= settings['max_pages'] or len(new_documents) >= settings['max_documents']:
                            report['stop_reason'] = 'batch_page_limit' if used >= settings['max_pages'] else 'batch_document_limit'
                            break
                        new_documents.add(row['doc_id']); used += 1
                        progress.update(force=True, phase='extracting_html', item={'doc_id': row['doc_id'], 'page_number': 1})
                        content = raw.read_bytes()
                        selection = settings.get('html_main_ids', {}).get(row['source'], None)
                        extracted = extract_html(content, receipt.get('charset') or 'utf-8', selection)
                        text = clean(extracted['text'])
                        quality_flags = extracted['quality_flags'] + reasons({'extraction_method': 'poppler-bbox-layout', 'ocr_required': False}, text) + text_flags(text)
                        record = {'schema_version': 'corpus-page-1', 'identity': identity, 'method': 'html',
                                  'source_url': row['source_url'], 'title': row['title'], 'source': row['source'],
                                  'metadata_hints': {k: row[k] for k in ('subject', 'domain', 'grade', 'language', 'license')},
                                  'text': text, 'quality_flags': quality_flags, 'html_extraction': extracted,
                                  'processing_config': config, 'source_artifact_sha256': row['sha256'],
                                  'review_required': True, 'training_approved': False}
                        if file_hash(raw) != row['sha256']:
                            raise ValueError('Raw HTML changed during extraction')
                        files = {'page.json': encode(record), 'source.html': content, 'text.txt': text.encode('utf-8')}
                        publish(folder, {**files, 'manifest.json': encode({'schema_version': 'corpus-page-bundle-1', 'identity': identity,
                                                                         'output_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}})})
                        report['results'].append({'doc_id': row['doc_id'], 'page_number': 1, 'outcome': 'predicted', 'bundle': str(folder), 'quality_flags': quality_flags})
                        progress.update(force=True, counts={'pages_completed': used})
                        continue
                    is_image = receipt.get('format') in {'png', 'jpg'}
                    if is_image:
                        native_pages = [{'page_number': 1, 'text': '', 'backend': None, 'ocr_required': True}]
                        source_manifest_hash = file_hash(settings['raw_root'] / receipt['artifact_path'])
                    else:
                        if backend is None:
                            backend = PopplerBackend(extract_settings)
                        progress.update(force=True, phase='native_extraction')
                        manifest, native_folder, _ = extract_document(row, extract_settings, backend)
                        native_pages = [json.loads(line) for line in (native_folder / 'pages.jsonl').read_text(encoding='utf-8').splitlines()]
                        source_manifest_hash = file_hash(native_folder / 'manifest.json')
                    if page_numbers and max(page_numbers) > len(native_pages):
                        raise ValueError('Selected page exceeds document page count')
                    for page in native_pages:
                        if page_numbers and page['page_number'] not in page_numbers:
                            continue
                        identity = {'doc_id': row['doc_id'], 'raw_sha256': row['sha256'], 'page_number': page['page_number'],
                                    ('image_source_sha256' if is_image else 'native_manifest_sha256'): source_manifest_hash,
                                    'processing_config_sha256': config_hash}
                        folder = settings['output_root'] / row['doc_id'] / row['sha256'] / fingerprint(identity) / f"page_{page['page_number']:06d}"
                        previous = saved_attempt(folder, identity)
                        attempt = 1
                        if previous:
                            number, prior_folder, record = previous
                            if not incomplete(record) or not retry_incomplete:
                                needs_retry = incomplete(record)
                                report['results'].append({'doc_id': row['doc_id'], 'page_number': page['page_number'],
                                    'outcome': 'existing_incomplete' if needs_retry else 'verified_existing',
                                    'reused': True, 'bundle': str(prior_folder), 'retry_required': needs_retry,
                                    'prediction_outcome': record.get('prediction', {}).get('outcome')})
                                continue
                            attempt = number + 1
                            folder = folder.with_name(folder.name + f'_attempt_{attempt:06d}')
                        if used >= settings['max_pages']:
                            report['stop_reason'] = 'batch_page_limit'
                            break
                        if row['doc_id'] not in new_documents and len(new_documents) >= settings['max_documents']:
                            report['stop_reason'] = 'batch_document_limit'
                            break
                        new_documents.add(row['doc_id'])
                        used += 1
                        progress.update(force=True, phase='rendering_page', item={'doc_id': row['doc_id'], 'page_number': page['page_number']},
                                        counts={'pages_completed': used - 1, 'page_limit': settings['max_pages'], 'document_pages_total': len(native_pages)})
                        start = time.monotonic()
                        raw_path = settings['raw_root'] / receipt['artifact_path']
                        if is_image:
                            if raw_path.stat().st_size > settings['max_image_bytes']: raise ValueError('Image exceeds byte limit')
                            image, _ = images.prepare(raw_path.read_bytes(), settings['max_image_side'],
                                                      maximum_pixels=settings.get('max_input_pixels', 40_000_000))
                        else:
                            image = command([renderer, '-f', str(page['page_number']), '-l', str(page['page_number']), '-singlefile',
                                         '-r', str(settings['dpi']), '-scale-to', str(settings['max_image_side']), '-png',
                                         str(raw_path)],
                                        timeout=settings['render_timeout_seconds'], maximum=settings['max_image_bytes'])
                        if len(image) > settings['max_image_bytes']: raise ValueError('Rendered image exceeds byte limit')
                        width, height = png_dimensions(image)
                        if max(width, height) > settings['max_image_side']:
                            raise ValueError('Renderer dimension limit')
                        route_flags = reasons(page, clean(page['text']))
                        use_ocr = is_image or settings['ocr_mode'] == 'all' or bool(route_flags)
                        ocr_image, transform = image, None
                        if use_ocr and settings.get('preprocessing'):
                            ocr_image, transform = images.prepare(image, settings['max_image_side'], settings['preprocessing'],
                                                                 settings.get('max_input_pixels', 40_000_000))
                            if len(ocr_image) > settings['max_image_bytes']: raise ValueError('OCR image exceeds byte limit')
                        prediction = {'text': page['text'], 'outcome': 'predicted', 'completion_status': 'complete'}
                        engine_identity = page['backend']
                        if use_ocr:
                            if engine is None:
                                progress.update(force=True, phase='loading_ocr_model')
                                with redirect_stdout(sys.stderr):
                                    engine = backends.create(settings['ocr'])
                            progress.update(force=True, phase='ocr_page')
                            import tempfile
                            with tempfile.TemporaryDirectory(prefix='corpus-ocr-') as temporary:
                                path = Path(temporary) / 'page.png'; path.write_bytes(ocr_image)
                                try:
                                    with redirect_stdout(sys.stderr):
                                        prediction = engine.recognize(path)
                                except Exception as exc:
                                    prediction = {'text': '', 'outcome': 'failed', 'completion_status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
                            engine_identity = engine.identity
                            if not prediction.get('text', '').strip() and prediction.get('outcome') == 'predicted':
                                prediction['outcome'] = 'empty'
                        if file_hash(settings['raw_root'] / receipt['artifact_path']) != row['sha256']:
                            raise ValueError('Raw source changed during processing')
                        text = clean(prediction['text'])
                        quality_flags = reasons({'extraction_method': 'poppler-bbox-layout', 'ocr_required': False}, text) + text_flags(text)
                        if prediction['completion_status'] != 'complete' or prediction['outcome'] != 'predicted':
                            quality_flags.append('incomplete_or_failed_prediction')
                        record = {'schema_version': 'corpus-page-1', 'identity': identity, 'source_url': row['source_url'],
                                  'attempt': attempt, 'previous_attempt_bundle': str(previous[1]) if previous else None,
                                  'preprocessing': transform, 'ocr_input_sha256': hashlib.sha256(ocr_image).hexdigest() if use_ocr else None,
                                  'title': row['title'], 'source': row['source'], 'metadata_hints': {k: row[k] for k in ('subject', 'domain', 'grade', 'language', 'license')},
                                  'method': 'ocr' if use_ocr else 'native', 'ocr_backend': settings['ocr']['backend'] if use_ocr else None,
                                  'model_id': backends.MODELS[settings['ocr']['backend']] if use_ocr else None,
                                  'model_revision': settings['ocr']['revision'] if use_ocr else None, 'runtime': engine_identity,
                                  'processing_config': config, 'native_text': page['text'], 'routing_flags': route_flags,
                                  'prediction': prediction, 'text': text, 'quality_flags': quality_flags,
                                  'image_sha256': hashlib.sha256(image).hexdigest(), 'image_dimensions': [width, height],
                                  'seconds': round(time.monotonic() - start, 3), 'review_required': True, 'training_approved': False}
                        files = {'page.json': encode(record), 'page.png': image, 'text.txt': text.encode('utf-8')}
                        if transform is not None: files['ocr_input.png'] = ocr_image
                        publish(folder, {**files, 'manifest.json': encode({'schema_version': 'corpus-page-bundle-1', 'identity': identity,
                                         'output_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}})})
                        report['results'].append({'doc_id': row['doc_id'], 'page_number': page['page_number'],
                                                  'outcome': prediction['outcome'], 'bundle': str(folder), 'quality_flags': quality_flags})
                        progress.update(force=True, counts={'pages_completed': used})
                    if report['stop_reason'].startswith('batch_'):
                        break
                except Exception as exc:
                    report['errors'].append({'doc_id': row['doc_id'], 'error': f'{type(exc).__name__}: {exc}'})
            report['outcomes'] = dict(Counter(r['outcome'] for r in report['results']))
            progress.finish('failed' if has_failures(report) else 'partial' if report['stop_reason'].startswith('batch_') else 'completed')
    except BaseException as exc:
        progress.finish('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
        raise
    finally:
        log.write_bytes(encode(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/pipeline.yaml')
    parser.add_argument('--doc-id', action='append', dest='doc_ids')
    parser.add_argument('--page-number', action='append', type=int, dest='page_numbers')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--retry-incomplete', action='store_true', help='Save new attempts for failed/incomplete OCR pages')
    parser.add_argument('--progress', choices=['auto', 'plain', 'off'], default='auto')
    args = parser.parse_args()
    try:
        report = run(load_settings(args.config), extraction_settings(args.config), doc_ids=args.doc_ids, page_numbers=args.page_numbers, dry_run=args.dry_run, progress_mode=args.progress, retry_incomplete=args.retry_incomplete)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(has_failures(report))
    except Exception as exc:
        parser.exit(2, f'Page processing error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
