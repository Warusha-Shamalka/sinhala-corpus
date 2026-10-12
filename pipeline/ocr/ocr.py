"""Local selective Tesseract OCR baseline; every result requires quality review."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import time
from uuid import uuid4

import yaml

from pipeline.discovery.crawler import ROOT, CatalogError, read_catalog, _catalog_lock
from pipeline.download.downloader import PIPELINE_PATH, DownloadError, recover, file_hash, sync_directory
from pipeline.extraction.extractor import ExtractionError, command, verify_bundle, utc_now
from pipeline.progress import ProgressReporter

VERSION = 'ocr-0.2'


class OCRError(Exception):
    pass


def load_settings(path):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 'pipeline-1' or not isinstance(data.get('ocr'), dict):
        raise ValueError('Expected pipeline-1 configuration with ocr settings')
    settings = dict(data['ocr'])
    for key in ('catalog_path', 'raw_root', 'extraction_root', 'output_root', 'log_root'):
        value = settings.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'Missing path: {key}')
        settings[key] = (ROOT / value).resolve()
    for key in ('dpi', 'max_image_side', 'max_pages', 'max_command_bytes', 'min_text_chars'):
        if type(settings.get(key)) is not int or settings[key] < 1:
            raise ValueError(f'Invalid integer setting: {key}')
    if type(settings.get('psm')) is not int or settings['psm'] not in {3, 6, 11}:
        raise ValueError('Supported psm modes: 3, 6, 11')
    for key in ('max_seconds', 'command_timeout_seconds', 'min_mean_confidence'):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid numeric setting: {key}')
    if settings['min_mean_confidence'] > 100:
        raise ValueError('Confidence threshold must be at most 100')
    if not isinstance(settings.get('languages'), str) or not re.fullmatch(r'[a-z]{3}(?:\+[a-z]{3})*', settings['languages']):
        raise ValueError('Invalid language codes')
    if len(set(settings['languages'].split('+'))) != len(settings['languages'].split('+')):
        raise ValueError('Duplicate language codes')
    for key in ('tesseract_command', 'tessdata_dir'):
        if not isinstance(settings.get(key), str):
            raise ValueError(f'Invalid string setting: {key}')
    if not settings['tesseract_command'].strip():
        raise ValueError('Empty tesseract_command')
    if settings['tessdata_dir']:
        settings['tessdata_dir'] = str((ROOT / settings['tessdata_dir']).resolve())
    return settings


def png_dimensions(content):
    if len(content) < 24 or content[:8] != b'\x89PNG\r\n\x1a\n' or content[12:16] != b'IHDR':
        raise OCRError('Renderer did not produce a PNG')
    width, height = struct.unpack('>II', content[16:24])
    if not width or not height:
        raise OCRError('Invalid rendered dimensions')
    return width, height


class TesseractBackend:
    def __init__(self, settings):
        self.settings = settings
        self.engine = shutil.which(settings['tesseract_command'])
        self.renderer = shutil.which('pdftoppm')
        if not self.engine or not self.renderer:
            raise OCRError('Install tesseract, Sinhala/English language data and poppler-utils')
        maximum = settings['max_command_bytes']
        timeout = settings['command_timeout_seconds']
        version = command([self.engine, '--version'], timeout=timeout, maximum=65536).decode('utf-8', 'replace').splitlines()[0]
        renderer_version = command([self.renderer, '-v'], timeout=timeout, maximum=65536).decode('utf-8', 'replace').splitlines()[0]
        self.data_dir = settings['tessdata_dir']
        if not self.data_dir:
            output = command([self.engine, '--list-langs'], timeout=timeout, maximum=65536).decode('utf-8', 'replace')
            match = re.search(r'"([^"]+)"', output)
            if not match:
                raise OCRError('Cannot locate traineddata; set ocr.tessdata_dir')
            self.data_dir = match[1]
        hashes = {}
        for language in settings['languages'].split('+'):
            path = Path(self.data_dir) / f'{language}.traineddata'
            if not path.is_file():
                raise OCRError(f'Missing language model: {path}')
            hashes[language] = file_hash(path)
        self.identity = {'engine': version, 'renderer': renderer_version, 'traineddata_sha256': hashes,
                         'recognition_scope': 'baseline_requires_review'}
        self.warnings = []

    def recognize(self, pdf, page_number, timeout):
        self.warnings = []
        started = time.monotonic()
        s = self.settings
        png = command([self.renderer, '-f', str(page_number), '-l', str(page_number), '-singlefile', '-r', str(s['dpi']),
                       '-scale-to', str(s['max_image_side']), '-png', str(pdf)], timeout=timeout, maximum=s['max_command_bytes'], warnings=self.warnings)
        width, height = png_dimensions(png)
        if max(width, height) > s['max_image_side']:
            raise OCRError('Rendered image exceeds dimension limit')
        with tempfile.TemporaryDirectory(prefix='ocr-page-') as folder:
            path = Path(folder) / 'page.png'
            path.write_bytes(png)
            remaining = timeout - (time.monotonic() - started)
            tsv = command([self.engine, str(path), 'stdout', '--tessdata-dir', self.data_dir, '-l', s['languages'], '--oem', '1',
                           '--psm', str(s['psm']), 'tsv'], timeout=remaining, maximum=s['max_command_bytes'], warnings=self.warnings)
        return png, tsv


def parse_tsv(content, dimensions, settings):
    width, height = dimensions
    reader = csv.DictReader(io.StringIO(content.decode('utf-8')), delimiter='\t', quoting=csv.QUOTE_NONE)
    required = {'level', 'page_num', 'block_num', 'par_num', 'line_num', 'word_num', 'left', 'top', 'width', 'height', 'conf', 'text'}
    if reader.fieldnames is None or set(reader.fieldnames) != required:
        raise OCRError('Invalid Tesseract TSV header')
    words = []
    lines = {}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise OCRError('Malformed TSV row')
        if int(row['level']) != 5 or not row['text'].strip():
            continue
        left, top, w, h = (int(row[key]) for key in ('left', 'top', 'width', 'height'))
        confidence = float(row['conf'])
        if min(left, top, w, h) < 0 or left + w > width or top + h > height or not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise OCRError('Invalid OCR word coordinates/confidence')
        key = tuple(int(row[k]) for k in ('block_num', 'par_num', 'line_num'))
        if int(row['page_num']) != 1 or min(key) < 1 or int(row['word_num']) < 1:
            raise OCRError('Invalid OCR TSV hierarchy')
        word = {'text': row['text'], 'bbox_pixels': [left, top, left + w, top + h], 'confidence': confidence,
                'block_number': key[0], 'paragraph_number': key[1], 'line_number': key[2]}
        words.append(word)
        lines.setdefault(key, []).append(word['text'])
    text = '\n'.join(' '.join(parts) for parts in lines.values())
    nonspace = sum(not c.isspace() for c in text)
    mean = sum(w['confidence'] for w in words) / len(words) if words else None
    reasons = []
    if nonspace < settings['min_text_chars']:
        reasons.append('little_or_no_ocr_text')
    if mean is None or mean < settings['min_mean_confidence']:
        reasons.append('low_engine_confidence')
    return {'text': text, 'words': words, 'mean_word_confidence': mean, 'non_whitespace_chars': nonspace,
            'sinhala_chars': sum('\u0d80' <= c <= '\u0dff' for c in text), 'quality_flags': reasons,
            'quality_review': 'pending', 'review_required': True}


def select_input(settings, row, bundle=None):
    root = settings['extraction_root'] / row['doc_id'] / row['sha256']
    if bundle is None:
        paths = sorted(p.parent for p in root.glob('*/manifest.json'))
        if len(paths) != 1:
            raise OCRError('Expected one native extraction bundle; use --bundle to select an exact version')
        bundle = paths[0]
    bundle = Path(bundle).resolve()
    if not bundle.is_relative_to(root.resolve()) or bundle.parent != root.resolve():
        raise OCRError('Bundle must be inside the configured document/raw-hash extraction directory')
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    config_hash = manifest.get('config_hash') if isinstance(manifest, dict) else None
    if not isinstance(config_hash, str) or bundle.name != config_hash:
        raise OCRError('Invalid native extraction bundle identity')
    verify_bundle(bundle, row, config_hash)
    pages = [json.loads(line) for line in (bundle / 'pages.jsonl').read_text(encoding='utf-8').splitlines()]
    return bundle, manifest, pages


def verify_ocr(folder, row, config_hash, number):
    record = json.loads((folder / 'page.json').read_text(encoding='utf-8'))
    for key, expected in {'schema_version': 'ocr-page-1', 'doc_id': row['doc_id'], 'raw_sha256': row['sha256'], 'config_hash': config_hash, 'page_number': number, 'quality_review': 'pending', 'review_required': True}.items():
        if not isinstance(record, dict) or record.get(key) != expected:
            raise OCRError('Invalid OCR page identity/review status')
    config = record.get('config')
    if not isinstance(config, dict) or hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest() != config_hash:
        raise OCRError('OCR configuration mismatch')
    hashes = record.get('output_sha256')
    if not isinstance(hashes, dict) or set(hashes) != {'page.png', 'raw.tsv', 'text.txt'}:
        raise OCRError('Invalid OCR output list')
    for name, digest in hashes.items():
        if file_hash(folder / name) != digest:
            raise OCRError(f'OCR output hash mismatch: {name}')
    return record


def process_page(settings, row, native_bundle, page, backend, config, config_hash, timeout):
    number = page['page_number']
    folder = settings['output_root'] / row['doc_id'] / row['sha256'] / config_hash / f'page_{number:06d}'
    if folder.exists():
        return verify_ocr(folder, row, config_hash, number), folder, True
    png, tsv = backend.recognize(settings['raw_root'] / 'pdf' / row['doc_id'] / f"{row['sha256']}.pdf", number, timeout)
    if len(png) > settings['max_command_bytes'] or len(tsv) > settings['max_command_bytes']:
        raise OCRError('OCR backend output limit')
    pdf = settings['raw_root'] / 'pdf' / row['doc_id'] / f"{row['sha256']}.pdf"
    if file_hash(pdf) != row['sha256']:
        raise OCRError('Raw PDF changed during OCR')
    dimensions = png_dimensions(png)
    if max(dimensions) > settings['max_image_side']:
        raise OCRError('Rendered image exceeds dimension limit')
    record = parse_tsv(tsv, dimensions, settings)
    record.update(schema_version='ocr-page-1', doc_id=row['doc_id'], raw_sha256=row['sha256'], page_number=number,
                  page_number_base=1, config_hash=config_hash, config=config, native_bundle=str(native_bundle),
                  native_text=page['text'], native_ocr_reasons=page['ocr_reasons'], backend=backend.identity,
                  image_width=dimensions[0], image_height=dimensions[1], coordinate_system='rendered_image_pixels',
                  pipeline_version=VERSION, created_at_utc=utc_now(), warnings=list(getattr(backend, 'warnings', [])))
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.ocr-', dir=folder.parent))
    try:
        for name, content in {'page.png': png, 'raw.tsv': tsv, 'text.txt': record['text'].encode('utf-8')}.items():
            with (temporary / name).open('wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        record['output_sha256'] = {name: file_hash(temporary / name) for name in ('page.png', 'raw.tsv', 'text.txt')}
        with (temporary / 'page.json').open('w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(temporary)
        os.rename(temporary, folder)
        sync_directory(folder.parent)
        return record, folder, False
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def run(settings, doc_id, *, bundle=None, page_numbers=None, dry_run=False, progress_mode=None, backend=None):
    rows = read_catalog(settings['catalog_path'])
    row = next((r for r in rows if r['doc_id'] == doc_id), None)
    if row is None or row['status'] not in {'DOWNLOADED', 'EXTRACTED', 'OCR_FAILED'} or not row['sha256']:
        raise OCRError('Document is not an eligible downloaded PDF')
    native_bundle, native_manifest, pages = select_input(settings, row, bundle)
    flagged = [p for p in pages if p['ocr_required']]
    if page_numbers:
        if any(type(n) is not int or n < 1 for n in page_numbers) or len(set(page_numbers)) != len(page_numbers):
            raise OCRError('Page numbers must be unique positive integers')
        if set(page_numbers) - {p['page_number'] for p in flagged}:
            raise OCRError('Requested pages must be native-extraction OCR candidates')
        flagged = [p for p in flagged if p['page_number'] in page_numbers]
    selected = flagged[:settings['max_pages']]
    report = {'schema_version': 'ocr-run-1', 'doc_id': doc_id, 'dry_run': dry_run,
              'native_bundle': str(native_bundle), 'document_pages': native_manifest['page_count'],
              'flagged_pages': native_manifest['ocr_pages'], 'selected_pages': [p['page_number'] for p in selected],
              'unselected_flagged_pages': native_manifest['ocr_pages'] - len(selected), 'results': [], 'catalog_updated': False}
    if dry_run or not selected:
        return report
    with _catalog_lock(settings['catalog_path'].with_name('ocr-worker'), 0):
        receipt = recover({**row, 'status': 'DOWNLOADED'}, settings['raw_root'])
        if receipt is None:
            raise OCRError('Missing verified raw receipt')
        backend = backend or TesseractBackend(settings)
        config = {'pipeline_version': VERSION, 'backend': backend.identity,
                  'native_manifest_sha256': file_hash(native_bundle / 'manifest.json'),
                  'languages': settings['languages'], 'dpi': settings['dpi'], 'max_image_side': settings['max_image_side'],
                  'psm': settings['psm'], 'oem': 1, 'min_text_chars': settings['min_text_chars'],
                  'min_mean_confidence': settings['min_mean_confidence']}
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        settings['log_root'].mkdir(parents=True, exist_ok=True)
        events = settings['log_root'] / f'ocr_{uuid4().hex}.jsonl'
        report['events_path'] = str(events)
        progress = ProgressReporter('ocr', run_id=events.stem, path=events.with_suffix('.progress.json'), mode=progress_mode) if progress_mode else None
        if progress:
            report['progress_path'] = str(progress.path)
            progress.update(force=True, counts={'pages_total': len(selected), 'pages_completed': 0, 'failed': 0})
        started = time.monotonic()
        try:
            with events.open('x', encoding='utf-8') as audit:
                for page in selected:
                    number = page['page_number']
                    result = {'page_number': number, 'at_utc': utc_now()}
                    if progress:
                        progress.update(force=True, phase='rendering_and_recognizing', item={'doc_id': doc_id, 'page_number': number})
                    try:
                        remaining = min(settings['command_timeout_seconds'], settings['max_seconds'] - (time.monotonic() - started))
                        if remaining <= 0:
                            raise OCRError('run_time_limit')
                        record, folder, reused = process_page(settings, row, native_bundle, page, backend, config, config_hash, remaining)
                        result.update(outcome='review_required', bundle_path=str(folder), reused=reused,
                                      non_whitespace_chars=record['non_whitespace_chars'], sinhala_chars=record['sinhala_chars'],
                                      mean_word_confidence=record['mean_word_confidence'], quality_flags=record['quality_flags'])
                    except (OCRError, ExtractionError, DownloadError, OSError, ValueError, KeyError, TypeError) as exc:
                        result.update(outcome='failed', error=str(exc))
                    audit.write(json.dumps(result, ensure_ascii=False) + '\n')
                    audit.flush()
                    os.fsync(audit.fileno())
                    report['results'].append(result)
                    if progress:
                        progress.update(force=True, counts={'pages_completed': len(report['results']), 'failed': sum(r['outcome'] == 'failed' for r in report['results'])})
        except BaseException as exc:
            if progress:
                progress.finish('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise
        if progress:
            progress.finish('failed' if any(r['outcome'] == 'failed' for r in report['results']) else 'completed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=PIPELINE_PATH)
    parser.add_argument('--doc-id', required=True)
    parser.add_argument('--bundle', type=Path, help='Exact native extraction bundle when multiple versions exist')
    parser.add_argument('--page', action='append', type=int, dest='page_numbers')
    parser.add_argument('--max-pages', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--progress', choices=('auto', 'plain', 'off'), default='auto')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.max_pages is not None:
            if args.max_pages < 1:
                raise ValueError('max-pages must be positive')
            settings['max_pages'] = args.max_pages
        report = run(settings, args.doc_id, bundle=args.bundle, page_numbers=args.page_numbers, dry_run=args.dry_run,
                     progress_mode='off' if args.quiet else args.progress)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(any(r['outcome'] == 'failed' for r in report['results']))
    except KeyboardInterrupt:
        return 130
    except (OCRError, ExtractionError, DownloadError, CatalogError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        parser.exit(2, f'OCR setup/input error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
