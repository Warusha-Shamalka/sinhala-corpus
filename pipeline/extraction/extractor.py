"""Extract verified local PDFs into immutable page/text bundles; never run OCR."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

import yaml

from pipeline.discovery.crawler import ROOT, CatalogError, _catalog_lock, read_catalog
from pipeline.download.downloader import (
    PIPELINE_PATH, SOURCES_PATH, DownloadError, checkpoint, file_hash, recover, sync_directory, load_sources,
)
from pipeline.progress import ProgressReporter

VERSION = 'extraction-0.1'
SCHEMA = 'pdf-pages-1'


class ExtractionError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_settings(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 'pipeline-1' or not isinstance(data.get('extraction'), dict):
        raise ValueError('Expected pipeline-1 configuration with extraction settings')
    settings = dict(data['extraction'])
    for name in ('catalog_path', 'raw_root', 'output_root', 'log_root'):
        value = settings.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'Missing path: {name}')
        settings[name] = (ROOT / value).resolve()
    for name in ('max_documents', 'max_pages', 'max_raw_bytes', 'max_page_bytes', 'max_output_bytes', 'min_text_chars'):
        value = settings.get(name)
        if type(value) is not int or value < 1:
            raise ValueError(f'Invalid integer setting: {name}')
    for name in ('max_seconds', 'command_timeout_seconds', 'max_replacement_ratio'):
        value = settings.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid numeric setting: {name}')
    if settings['max_replacement_ratio'] > 1:
        raise ValueError('max_replacement_ratio must be at most 1')
    return settings


def command(argv: list[str], *, timeout: float, maximum: int, warnings=None) -> bytes:
    """Bound child runtime and output files; no shell, network or PDF modification."""
    if timeout <= 0:
        raise ExtractionError('document_time_limit')
    def limit_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
    with tempfile.TemporaryDirectory(prefix='pdf-command-') as folder:
        out, err = Path(folder) / 'stdout', Path(folder) / 'stderr'
        try:
            with out.open('wb') as stdout, err.open('wb') as stderr:
                result = subprocess.run(argv, stdout=stdout, stderr=stderr,
                                        timeout=timeout, check=False, preexec_fn=limit_output,
                                        env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'})
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError('PDF command timed out') from exc
        if out.stat().st_size >= maximum or err.stat().st_size >= maximum:
            raise ExtractionError('PDF command output limit')
        if result.returncode:
            detail = err.read_bytes()[:1000].decode('utf-8', 'replace')
            raise ExtractionError(f'{Path(argv[0]).name} failed ({result.returncode}): {detail}')
        if warnings is not None and err.stat().st_size:
            warnings.append(err.read_bytes()[:4000].decode('utf-8', 'replace'))
        return out.read_bytes() + (err.read_bytes() if '-v' in argv else b'')


class PopplerBackend:
    def __init__(self, settings):
        self.settings = settings
        self.warnings = []
        self.info_tool = shutil.which('pdfinfo')
        self.text_tool = shutil.which('pdftotext')
        if not self.info_tool or not self.text_tool:
            raise ExtractionError('Install poppler-utils: pdfinfo and pdftotext are required')
        versions = {}
        for name, tool in (('pdfinfo', self.info_tool), ('pdftotext', self.text_tool)):
            output = command([tool, '-v'], timeout=settings['command_timeout_seconds'], maximum=65536)
            versions[name] = output.decode('utf-8', 'replace').splitlines()[0]
        self.identity = {'name': 'poppler-bbox-layout', 'versions': versions}

    def page_count(self, path: Path, timeout: float) -> int:
        output = command([self.info_tool, '-enc', 'UTF-8', str(path)], timeout=timeout, maximum=1048576, warnings=self.warnings).decode('utf-8', 'replace')
        if re.search(r'^Encrypted:\s+yes', output, re.M):
            raise ExtractionError('Encrypted PDFs require a separate reviewed workflow')
        match = re.search(r'^Pages:\s+(\d+)\s*$', output, re.M)
        if not match or int(match[1]) < 1:
            raise ExtractionError('Missing or invalid PDF page count')
        return int(match[1])

    def page(self, path: Path, number: int, timeout: float) -> bytes:
        self.warnings = []
        return command([self.text_tool, '-f', str(number), '-l', str(number), '-bbox-layout', '-enc', 'UTF-8', str(path), '-'],
                       timeout=timeout, maximum=self.settings['max_page_bytes'], warnings=self.warnings)


def bbox(element):
    values = [float(element.attrib[key]) for key in ('xMin', 'yMin', 'xMax', 'yMax')]
    if any(not math.isfinite(v) for v in values) or values[0] > values[2] or values[1] > values[3]:
        raise ExtractionError('Invalid layout coordinates')
    return values


def parse_page(content: bytes, *, row, number: int, config_hash: str, settings: dict, backend: dict) -> dict:
    if b'<!ENTITY' in content.upper():
        raise ExtractionError('Unsupported XML entities')
    try:
        root = ET.fromstring(content)
        # Strip XHTML namespaces, retaining Poppler's emitted flow/block order.
        for element in root.iter():
            element.tag = element.tag.rsplit('}', 1)[-1]
        pages = list(root.iter('page'))
        if len(pages) != 1:
            raise ExtractionError('Expected exactly one extracted page')
        page = pages[0]
        width, height = float(page.attrib['width']), float(page.attrib['height'])
        if any(not math.isfinite(v) or v <= 0 for v in (width, height)):
            raise ExtractionError('Invalid page dimensions')
        blocks = []
        for block in page.iter('block'):
            lines = []
            for line in block.iter('line'):
                words = [{'text': word.text or '', 'bbox': bbox(word)} for word in line.iter('word')]
                lines.append({'text': ' '.join(w['text'] for w in words), 'bbox': bbox(line), 'words': words})
            blocks.append({'block_index': len(blocks), 'bbox': bbox(block), 'lines': lines,
                           'text': '\n'.join(line['text'] for line in lines)})
    except (ET.ParseError, KeyError, ValueError) as exc:
        raise ExtractionError(f'Invalid PDF layout output: {exc}') from exc
    text = '\n\n'.join(b['text'] for b in blocks)
    chars = [c for c in text if not c.isspace()]
    replacements = sum(c == '\ufffd' for c in chars)
    ratio = replacements / len(chars) if chars else 0
    reasons = []
    if len(chars) < settings['min_text_chars']:
        reasons.append('little_or_no_native_text')
    if ratio > settings['max_replacement_ratio']:
        reasons.append('replacement_characters')
    return {'schema_version': SCHEMA, 'doc_id': row['doc_id'], 'raw_sha256': row['sha256'],
            'page_number': number, 'page_number_base': 1, 'width_points': width, 'height_points': height,
            'extraction_method': 'poppler-bbox-layout', 'pipeline_version': VERSION,
            'backend': backend, 'config_hash': config_hash, 'reading_order': 'poppler_emitted_block_order',
            'text': text, 'blocks': blocks, 'assets': [], 'assets_status': 'not_extracted',
            'ocr_required': bool(reasons), 'ocr_reasons': reasons, 'ocr_outcome': 'not_run', 'ocr_confidence': None,
            'metrics': {'non_whitespace_chars': len(chars), 'sinhala_chars': sum('\u0d80' <= c <= '\u0dff' for c in chars),
                        'replacement_ratio': ratio}, 'quality_review': 'pending', 'errors': []}


def fingerprint(settings, backend):
    config = {'pipeline_version': VERSION, 'backend': backend,
              **{k: v for k, v in settings.items() if not isinstance(v, Path) and k != 'max_documents'}}
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(), config


def verify_bundle(folder, row, config_hash):
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in
            {'schema_version': 'pdf-extraction-1', 'doc_id': row['doc_id'], 'raw_sha256': row['sha256'], 'config_hash': config_hash}.items()):
        raise ExtractionError('Invalid extraction manifest identity')
    count = manifest.get('page_count')
    ocr_count = manifest.get('ocr_pages')
    if type(count) is not int or count < 1 or type(ocr_count) is not int or not 0 <= ocr_count <= count:
        raise ExtractionError('Invalid extraction manifest page counts')
    if manifest.get('outcome') != ('ocr_required' if ocr_count else 'extracted'):
        raise ExtractionError('Invalid extraction manifest outcome')
    stored_config = manifest.get('config')
    if not isinstance(stored_config, dict) or hashlib.sha256(json.dumps(stored_config, sort_keys=True).encode()).hexdigest() != config_hash:
        raise ExtractionError('Invalid extraction manifest config')
    hashes = manifest.get('output_sha256', {})
    if not isinstance(hashes, dict) or set(hashes) != {'pages.jsonl', 'text.txt'}:
        raise ExtractionError('Invalid extraction output list')
    for filename, digest in hashes.items():
        if file_hash(folder / filename) != digest:
            raise ExtractionError(f'Extraction output hash mismatch: {filename}')
    seen, flagged = 0, 0
    with (folder / 'pages.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            page = json.loads(line)
            seen += 1
            if not isinstance(page, dict) or any(page.get(k) != v for k, v in {'schema_version': SCHEMA, 'doc_id': row['doc_id'], 'raw_sha256': row['sha256'], 'config_hash': config_hash, 'page_number': seen, 'page_number_base': 1}.items()) or type(page.get('ocr_required')) is not bool:
                raise ExtractionError('Invalid extraction page identity')
            flagged += page['ocr_required']
    if seen != count or flagged != ocr_count:
        raise ExtractionError('Incomplete extraction bundle')
    return manifest


def extract_document(row, settings, backend, progress=None):
    raw_root = settings['raw_root']
    receipt = recover({**row, 'status': 'DOWNLOADED'}, raw_root)
    if receipt is None:
        raise ExtractionError('Missing verified raw receipt')
    path = raw_root / receipt['artifact_path']
    if path.stat().st_size > settings['max_raw_bytes']:
        raise ExtractionError('Raw PDF exceeds extraction byte limit')
    config_hash, config = fingerprint(settings, backend.identity)
    folder = settings['output_root'] / row['doc_id'] / row['sha256'] / config_hash
    if folder.exists():
        return verify_bundle(folder, row, config_hash), folder, True
    started = time.monotonic()
    def timeout():
        return min(settings['command_timeout_seconds'], settings['max_seconds'] - (time.monotonic() - started))
    count = backend.page_count(path, timeout())
    metadata_warnings = list(getattr(backend, 'warnings', []))
    if count > settings['max_pages']:
        raise ExtractionError('PDF exceeds page limit; no truncated extraction committed')
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.extract-', dir=folder.parent))
    ocr_pages = 0
    total_size = 0
    try:
        with (temporary / 'pages.jsonl').open('w', encoding='utf-8') as pages, (temporary / 'text.txt').open('w', encoding='utf-8') as text:
            for number in range(1, count + 1):
                if timeout() <= 0:
                    raise ExtractionError('document_time_limit')
                if progress:
                    progress.update(phase='extracting_page', counts={'pages_total': count, 'pages_completed': number - 1}, item={'doc_id': row['doc_id'], 'title': row['title'], 'page_number': number})
                record = parse_page(backend.page(path, number, timeout()), row=row, number=number, config_hash=config_hash, settings=settings, backend=backend.identity)
                record['backend_warnings'] = list(getattr(backend, 'warnings', []))
                serialized = json.dumps(record, ensure_ascii=False) + '\n'
                plain = record['text'] + ('\f\n' if number < count else '')
                total_size += len(serialized.encode()) + len(plain.encode())
                if total_size > settings['max_output_bytes']:
                    raise ExtractionError('Extracted output exceeds byte limit')
                pages.write(serialized)
                text.write(plain)
                ocr_pages += record['ocr_required']
                if progress:
                    progress.update(counts={'pages_completed': number, 'ocr_pages': ocr_pages})
            for stream in (pages, text):
                stream.flush()
                os.fsync(stream.fileno())
        if file_hash(path) != row['sha256']:
            raise ExtractionError('Raw PDF changed during extraction')
        manifest = {'schema_version': 'pdf-extraction-1', 'doc_id': row['doc_id'], 'raw_sha256': row['sha256'],
                    'pipeline_version': VERSION, 'config_hash': config_hash, 'config': config,
                    'page_count': count, 'ocr_pages': ocr_pages, 'metadata_warnings': metadata_warnings, 'outcome': 'ocr_required' if ocr_pages else 'extracted',
                    'created_at_utc': utc_now(), 'quality_review': 'pending',
                    'output_sha256': {name: file_hash(temporary / name) for name in ('pages.jsonl', 'text.txt')}}
        with (temporary / 'manifest.json').open('w', encoding='utf-8') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(temporary)
        os.rename(temporary, folder)
        sync_directory(folder.parent)
        return manifest, folder, False
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def plan(rows, settings, *, doc_ids=None, source=None):
    jobs, excluded = [], []
    for row in rows:
        reason = ''
        if doc_ids and row['doc_id'] not in doc_ids:
            reason = 'document_not_selected'
        elif source and row['source'] != source:
            reason = 'source_not_selected'
        elif row['status'] not in {'DOWNLOADED', 'EXTRACTION_FAILED', 'EXTRACTED'}:
            reason = 'status_not_eligible'
        elif not row['sha256'] or not row['local_filename'] or not row['local_filename'].lower().endswith('.pdf'):
            reason = 'missing_raw_pdf'
        elif len(jobs) >= settings['max_documents']:
            reason = 'batch_limit'
        if reason:
            excluded.append({'doc_id': row['doc_id'], 'reason': reason})
        else:
            jobs.append(row)
    return jobs, excluded


def run(settings, *, doc_ids=None, source=None, dry_run=False, progress_mode=None, backend=None):
    jobs, excluded = plan(read_catalog(settings['catalog_path']), settings, doc_ids=doc_ids, source=source)
    report = {'schema_version': 'extraction-run-1', 'dry_run': dry_run, 'planned': [r['doc_id'] for r in jobs], 'excluded': excluded, 'results': []}
    if dry_run or not jobs:
        return report
    # Separate worker lock; catalog compare-and-set also coordinates with downloader/discovery.
    with _catalog_lock(settings['catalog_path'].with_name('extraction-worker'), 0):
        backend = backend or PopplerBackend(settings)
        settings['log_root'].mkdir(parents=True, exist_ok=True)
        run_id = f'extraction_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}'
        events = settings['log_root'] / f'{run_id}.jsonl'
        report['events_path'] = str(events)
        progress = ProgressReporter('extraction', run_id=run_id, path=events.with_suffix('.progress.json'), mode=progress_mode) if progress_mode else None
        if progress:
            report['progress_path'] = str(progress.path)
            progress.update(force=True, counts={'jobs_total': len(jobs), 'jobs_completed': 0, 'failed': 0, 'ocr_required': 0, 'extracted': 0, 'catalog_conflict': 0})
        try:
            with events.open('x', encoding='utf-8') as audit:
                for row in jobs:
                    if progress:
                        progress.update(force=True, phase='verifying_raw', item={'doc_id': row['doc_id'], 'title': row['title']}, counts={'pages_total': 0, 'pages_completed': 0, 'ocr_pages': 0})
                    result = {'doc_id': row['doc_id'], 'at_utc': utc_now()}
                    try:
                        manifest, folder, reused = extract_document(row, settings, backend, progress)
                        result.update(outcome=manifest['outcome'], bundle_path=str(folder), reused=reused, page_count=manifest['page_count'], ocr_pages=manifest['ocr_pages'])
                        # Native extraction pending OCR remains DOWNLOADED; no partial success promoted.
                        updates = {'status': 'DOWNLOADED' if manifest['ocr_pages'] else 'EXTRACTED',
                                   'extraction_method': 'poppler-bbox-layout', 'ocr_required': 'true' if manifest['ocr_pages'] else 'false',
                                   'page_count': str(manifest['page_count']), 'pipeline_version': VERSION, 'last_processed': utc_now(), 'error': ''}
                        if progress:
                            progress.update(force=True, phase='catalog_checkpoint', counts={'pages_total': manifest['page_count'], 'pages_completed': manifest['page_count'], 'ocr_pages': manifest['ocr_pages']})
                        if not checkpoint(settings['catalog_path'], row, updates):
                            result['outcome'] = 'catalog_conflict'
                    except (ExtractionError, DownloadError, OSError, ValueError, KeyError, TypeError) as exc:
                        result.update(outcome='failed', error=str(exc))
                        # Preserve an already successful extraction if re-verification fails.
                        if row['status'] != 'EXTRACTED':
                            if not checkpoint(settings['catalog_path'], row, {'status': 'EXTRACTION_FAILED', 'last_processed': utc_now(), 'error': str(exc), 'pipeline_version': VERSION}):
                                result['outcome'] = 'catalog_conflict'
                    audit.write(json.dumps(result, ensure_ascii=False) + '\n')
                    audit.flush()
                    os.fsync(audit.fileno())
                    report['results'].append(result)
                    if progress:
                        totals = Counter(r['outcome'] for r in report['results'])
                        progress.update(force=True, phase='job_finished', counts={'jobs_completed': len(report['results']), **totals})
        except BaseException as exc:
            if progress:
                progress.finish('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise
        if progress:
            progress.finish('failed' if any(r['outcome'] in {'failed', 'catalog_conflict'} for r in report['results']) else 'completed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=PIPELINE_PATH)
    parser.add_argument('--doc-id', action='append', dest='doc_ids')
    parser.add_argument('--source', help='Configured source ID or catalog source name')
    parser.add_argument('--sources', type=Path, default=SOURCES_PATH)
    parser.add_argument('--max-documents', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--progress', choices=('auto', 'plain', 'off'), default='auto')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.max_documents is not None:
            if args.max_documents < 1:
                raise ValueError('max-documents must be positive')
            settings['max_documents'] = args.max_documents
        source_name = None
        if args.source:
            matching = [s for s in load_sources(args.sources) if args.source in {s['id'], s['name']}]
            if not matching:
                raise ValueError(f'Unknown source: {args.source}')
            source_name = matching[0]['name']
        report = run(settings, doc_ids=args.doc_ids, source=source_name, dry_run=args.dry_run,
                     progress_mode='off' if args.quiet else args.progress)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(any(r['outcome'] in {'failed', 'catalog_conflict'} for r in report['results']))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, CatalogError, ExtractionError, yaml.YAMLError) as exc:
        parser.exit(2, f'Extraction configuration/backend error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
