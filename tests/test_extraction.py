import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from pipeline.extraction import extractor as e
from pipeline.discovery import crawler
from pipeline.download import downloader as d
from pipeline.progress import read_status
import test_download as fixtures


NATIVE = '''<html xmlns="http://www.w3.org/1999/xhtml"><body><doc><page width="595" height="842"><flow><block xMin="10" yMin="10" xMax="100" yMax="40"><line xMin="10" yMin="10" xMax="100" yMax="25"><word xMin="10" yMin="10" xMax="100" yMax="25">සිංහල පාඩම දසවන ශ්‍රේණිය ඉතිහාසය</word></line></block></flow></page></doc></body></html>'''.encode()
BLANK = b'<html><body><doc><page width="595" height="842"/></doc></body></html>'


class FakeBackend:
    identity = {'name': 'fixture', 'versions': {'pdfinfo': 'fixture-1', 'pdftotext': 'fixture-1'}}
    pages = [NATIVE]
    def page_count(self, path, timeout):
        return len(self.pages)
    def page(self, path, number, timeout):
        return self.pages[number - 1]


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DownloadTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.execute()
        self.row = crawler.read_catalog(self.fixture.settings['catalog_path'])[0]
        self.settings = e.load_settings(d.PIPELINE_PATH)
        self.settings.update(catalog_path=self.fixture.settings['catalog_path'], raw_root=self.fixture.settings['raw_root'], output_root=self.root / 'extracted', log_root=self.root / 'extraction-logs')
        self.backend = FakeBackend()
        self.backend.pages = [NATIVE]
        self.raw = Path(self.row['local_filename'])
        self.original_raw = self.raw.read_bytes()

    def run_stage(self, **kwargs):
        return e.run(self.settings, backend=self.backend, **kwargs)

    def test_native_pages_preserve_sinhala_layout_and_provenance(self):
        report = self.run_stage(progress_mode='off')
        result = report['results'][0]
        self.assertEqual(result['outcome'], 'extracted')
        page = json.loads((Path(result['bundle_path']) / 'pages.jsonl').read_text())
        self.assertIn('සිංහල', page['text'])
        self.assertEqual(page['page_number'], 1)
        self.assertEqual(page['raw_sha256'], self.row['sha256'])
        self.assertEqual(page['blocks'][0]['lines'][0]['words'][0]['bbox'], [10, 10, 100, 25])
        self.assertFalse(page['ocr_required'])
        self.assertEqual(page['ocr_outcome'], 'not_run')
        self.assertIsNone(page['ocr_confidence'])
        row = crawler.read_catalog(self.settings['catalog_path'])[0]
        self.assertEqual(row['status'], 'EXTRACTED')
        self.assertEqual(row['page_count'], '1')
        self.assertEqual(row['quality_score'], '')
        self.assertEqual(self.raw.read_bytes(), self.original_raw)
        state = read_status(Path(report['progress_path']))
        self.assertEqual(state['counts']['pages_completed'], 1)
        self.assertEqual(state['counts']['extracted'], 1)

    def test_mixed_and_image_only_documents_stay_pending_ocr(self):
        self.backend.pages = [NATIVE, BLANK]
        result = self.run_stage()['results'][0]
        self.assertEqual(result['outcome'], 'ocr_required')
        self.assertEqual(result['page_count'], 2)
        self.assertEqual(result['ocr_pages'], 1)
        row = crawler.read_catalog(self.settings['catalog_path'])[0]
        self.assertEqual(row['status'], 'DOWNLOADED')
        self.assertEqual(row['ocr_required'], 'true')
        pages = [json.loads(x) for x in (Path(result['bundle_path']) / 'pages.jsonl').read_text().splitlines()]
        self.assertEqual([p['ocr_required'] for p in pages], [False, True])
        self.assertIn('\f', (Path(result['bundle_path']) / 'text.txt').read_text())

    def test_replacement_characters_route_to_visual_review(self):
        broken = NATIVE.replace('සිංහල පාඩම දසවන ශ්‍රේණිය ඉතිහාසය'.encode(), ('\ufffd' * 40).encode())
        page = e.parse_page(broken, row=self.row, number=1, config_hash='fixture', settings=self.settings, backend=self.backend.identity)
        self.assertTrue(page['ocr_required'])
        self.assertIn('replacement_characters', page['ocr_reasons'])

    def test_dry_run_has_no_writes_or_backend_calls(self):
        before = self.settings['catalog_path'].read_bytes()
        with patch.object(e, 'PopplerBackend', side_effect=AssertionError('backend invoked')):
            report = e.run(self.settings, dry_run=True, progress_mode='plain')
        self.assertEqual(report['planned'], [self.row['doc_id']])
        self.assertEqual(self.settings['catalog_path'].read_bytes(), before)
        self.assertFalse(self.settings['output_root'].exists())
        self.assertFalse(self.settings['log_root'].exists())

    def test_bad_page_and_limits_leave_no_partial_bundle(self):
        for failure in ('malformed', 'page_limit', 'output_limit'):
            with self.subTest(failure=failure):
                self.backend.pages = [NATIVE, b'invalid'] if failure == 'malformed' else [NATIVE, BLANK]
                settings = dict(self.settings)
                if failure == 'page_limit': settings['max_pages'] = 1
                if failure == 'output_limit': settings['max_output_bytes'] = 1
                report = e.run(settings, backend=self.backend)
                self.assertEqual(report['results'][0]['outcome'], 'failed')
                self.assertEqual(crawler.read_catalog(settings['catalog_path'])[0]['status'], 'EXTRACTION_FAILED')
                self.assertEqual(list(settings['output_root'].rglob('manifest.json')), [])
                self.assertEqual(list(settings['output_root'].rglob('.extract-*')), [])
                self.assertEqual(self.raw.read_bytes(), self.original_raw)

    def test_corrupted_raw_is_rejected_before_backend(self):
        self.raw.write_bytes(b'corrupted')
        with patch.object(self.backend, 'page_count', side_effect=AssertionError('parsing corrupted input')):
            self.assertEqual(self.run_stage()['results'][0]['outcome'], 'failed')
        self.assertFalse(self.settings['output_root'].exists())

    def test_resume_reuses_bundle_without_overwriting(self):
        first = self.run_stage()['results'][0]
        folder = Path(first['bundle_path'])
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
        with patch.object(self.backend, 'page', side_effect=AssertionError('reparsed')):
            result = self.run_stage()['results'][0]
        self.assertTrue(result['reused'])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()})

    def test_corrupted_bundle_is_not_overwritten(self):
        first = self.run_stage()['results'][0]
        text = Path(first['bundle_path']) / 'text.txt'
        text.write_text('tampered')
        result = self.run_stage()['results'][0]
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(text.read_text(), 'tampered')
        self.assertEqual(crawler.read_catalog(self.settings['catalog_path'])[0]['status'], 'EXTRACTED')

    def test_invalid_manifest_structure_is_a_reported_failure(self):
        first = self.run_stage()['results'][0]
        path = Path(first['bundle_path']) / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['output_sha256'] = ['pages.jsonl', 'text.txt']
        path.write_text(json.dumps(manifest))
        result = self.run_stage()['results'][0]
        self.assertEqual(result['outcome'], 'failed')
        self.assertIn('output list', result['error'])

    def test_recovery_after_catalog_conflict(self):
        with patch.object(e, 'checkpoint', return_value=False):
            report = self.run_stage()
        self.assertEqual(report['results'][0]['outcome'], 'catalog_conflict')
        self.assertEqual(crawler.read_catalog(self.settings['catalog_path'])[0]['status'], 'DOWNLOADED')
        with patch.object(self.backend, 'page', side_effect=AssertionError('reparsed')):
            self.assertTrue(self.run_stage()['results'][0]['reused'])

    def test_interrupt_cleans_temporary_files_and_snapshot(self):
        with patch.object(self.backend, 'page', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_stage(progress_mode='off')
        self.assertEqual(list(self.settings['output_root'].rglob('.extract-*')), [])
        self.assertEqual(read_status(next(self.settings['log_root'].glob('*.progress.json')))['status'], 'interrupted')
        self.assertEqual(crawler.read_catalog(self.settings['catalog_path'])[0]['status'], 'DOWNLOADED')

    def test_config_change_produces_distinct_bundle(self):
        first = self.run_stage()['results'][0]
        self.settings['min_text_chars'] = 1000
        second = self.run_stage()['results'][0]
        self.assertNotEqual(first['bundle_path'], second['bundle_path'])
        self.assertEqual(second['outcome'], 'ocr_required')
        self.assertTrue(Path(first['bundle_path']).exists())

    def test_selection_and_validation(self):
        settings = dict(self.settings)
        settings['max_documents'] = 1
        second = {**self.row, 'doc_id': 'LK-EDU-000010'}
        jobs, excluded = e.plan([self.row, second], settings)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(excluded[0]['reason'], 'batch_limit')
        self.assertEqual(e.plan([self.row], settings, doc_ids=['LK-EDU-000099'])[0], [])
        self.assertEqual(e.plan([{**self.row, 'status': 'CLEANED'}], settings)[0], [])
        self.assertEqual(e.plan([self.row], settings, source='Unknown')[0], [])
        data = dict(self.settings)
        data['max_pages'] = 0
        path = self.root / 'bad.yaml'
        import yaml
        data = {k: str(v) if isinstance(v, Path) else v for k, v in data.items()}
        path.write_text(yaml.safe_dump({'schema_version': 'pipeline-1', 'extraction': data}))
        with self.assertRaises(ValueError): e.load_settings(path)


def make_pdf(text=True):
    stream = b'BT /F1 12 Tf 50 750 Td (History lesson grade ten educational resource) Tj ET' if text else b''
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    content = b'%PDF-1.4\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(content)
    content += b'xref\n0 6\n0000000000 65535 f \n'
    content += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    content += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'
    return content


@unittest.skipUnless(shutil.which('pdfinfo') and shutil.which('pdftotext'), 'Install poppler-utils for backend integration')
class PopplerTests(unittest.TestCase):
    def test_real_native_and_blank_pdf(self):
        settings = e.load_settings(d.PIPELINE_PATH)
        backend = e.PopplerBackend(settings)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.pdf'
            for native in (True, False):
                path.write_bytes(make_pdf(native))
                self.assertEqual(backend.page_count(path, 5), 1)
                page = e.parse_page(backend.page(path, 1, 5), row={'doc_id': 'fixture', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, number=1, config_hash='fixture', settings=settings, backend=backend.identity)
                self.assertEqual(page['ocr_required'], not native)
                if native: self.assertIn('History lesson', page['text'])

    def test_invalid_pdf_is_backend_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'broken.pdf'
            path.write_bytes(b'%PDF-1.4\n%%EOF')
            with self.assertRaises(e.ExtractionError):
                e.PopplerBackend(e.load_settings(d.PIPELINE_PATH)).page_count(path, 5)


class CommandTests(unittest.TestCase):
    def test_command_timeout_and_output_limit(self):
        import sys
        with self.assertRaises(e.ExtractionError):
            e.command([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=0.05, maximum=4096)
        with self.assertRaises(e.ExtractionError):
            e.command([sys.executable, '-c', 'import os; os.write(1, b"x" * 10000)'], timeout=5, maximum=4096)

    def test_missing_backend_has_clear_error(self):
        with patch.object(e.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(e.ExtractionError, 'poppler-utils'):
                e.PopplerBackend(e.load_settings(d.PIPELINE_PATH))

    def test_encrypted_pdf_is_rejected(self):
        backend = object.__new__(e.PopplerBackend)
        backend.info_tool = 'fixture'
        backend.warnings = []
        with patch.object(e, 'command', return_value=b'Pages: 1\nEncrypted: yes\n'):
            with self.assertRaisesRegex(e.ExtractionError, 'Encrypted'):
                backend.page_count(Path('fixture.pdf'), 5)

    def test_malformed_layout_and_unsafe_entities_are_rejected(self):
        settings = e.load_settings(d.PIPELINE_PATH)
        for content in (b'bad XML', BLANK.replace(b'595', b'nan'), b'<!ENTITY x "y"><page/>'):
            with self.subTest(content=content):
                with self.assertRaises(e.ExtractionError):
                    e.parse_page(content, row={'doc_id':'fixture','sha256':'fixture'}, number=1, config_hash='fixture', settings=settings, backend={})
