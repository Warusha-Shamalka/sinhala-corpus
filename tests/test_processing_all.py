"""Full-queue processing must tolerate mixed document lengths and partial OCR."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from pipeline import colab, workflow
from pipeline.discovery.crawler import read_catalog
from pipeline.processing import pages
import test_download as downloads
import test_extraction as extraction
import test_processing_pipeline as processing


class ProcessAllTests(unittest.TestCase):
    def setUp(self):
        self.fixture = processing.ProductionPipelineTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.fixture.backend.pages = [extraction.NATIVE] * 5

    def add_short_document(self):
        transport = self.fixture.fixture.fixture
        first = read_catalog(transport.settings['catalog_path'])[0]
        second = {**transport.row, 'doc_id': 'LK-EDU-000010', 'source_url': 'https://school.test/short.pdf'}
        transport.write_catalog([first, second])
        downloads.Fetcher.response_factory = staticmethod(lambda: downloads.Response(downloads.PDF + b'\nsecond document'))
        transport.execute(doc_ids=[second['doc_id']])
        backend = self.fixture.fixture.backend
        def count(path, timeout): return 1 if second['doc_id'] in str(path) else 5
        backend.page_count = count
        backend.page = lambda path, number, timeout: extraction.NATIVE
        return second['doc_id']

    def test_full_queue_exceeds_both_batch_caps_and_native_page_cap_with_one_engine(self):
        second = self.add_short_document()
        self.fixture.settings.update(max_pages=1, max_documents=1)
        self.fixture.fixture.settings['max_pages'] = 2
        report = self.fixture.run_stage(until_done=True)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['stop_reason'], 'queue_finished')
        self.assertEqual(len(report['results']), 6)
        self.assertEqual(report['results'][-1]['doc_id'], second)
        self.assertEqual(self.fixture.engine.calls, 6)
        resumed = self.fixture.run_stage(until_done=True)
        self.assertEqual(resumed['outcomes'], {'verified_existing': 6})
        self.assertEqual(self.fixture.engine.calls, 6)

    def test_shared_range_processes_short_document_and_warns_about_missing_pages(self):
        second = self.add_short_document()
        report = self.fixture.run_stage(page_numbers=[1, 2, 3, 4, 5, 6], until_done=True)
        self.assertEqual(report['errors'], [])
        self.assertEqual(len(report['results']), 6)
        self.assertEqual(report['warnings'][-1], {'doc_id': second,
                         'reason': 'requested_pages_not_available', 'page_count': 1,
                         'skipped_page_numbers': [2, 3, 4, 5, 6]})
        self.assertFalse(pages.has_failures(report))

    def test_truncated_page_does_not_block_remaining_pages_or_next_document(self):
        self.add_short_document()
        healthy = self.fixture.engine.recognize
        calls = []
        def recognize(path):
            calls.append(path)
            if len(calls) == 2:
                return {'text': 'partial text', 'outcome': 'truncated', 'completion_status': 'region_incomplete'}
            return healthy(path)
        self.fixture.engine.recognize = recognize
        report = self.fixture.run_stage(until_done=True)
        self.assertEqual(report['outcomes'], {'predicted': 5, 'truncated': 1})
        self.assertEqual(report['stop_reason'], 'queue_finished')
        self.assertTrue(pages.has_failures(report))
        self.assertEqual(len(calls), 6)

    def test_page_render_error_continues_with_later_pages(self):
        def render(argv, **kwargs):
            if '-v' in argv: return b'fixture-renderer-v1'
            if argv[argv.index('-f') + 1] == '2': raise ValueError('Bad page render')
            return processing.PNG
        with patch.object(pages, 'command', side_effect=render), patch.object(pages.shutil, 'which', return_value='/fixture/pdftoppm'):
            report = pages.run(self.fixture.settings, self.fixture.fixture.settings,
                               engine=self.fixture.engine, pdf_backend=self.fixture.fixture.backend,
                               until_done=True, progress_mode='off')
        self.assertEqual(len(report['results']), 4)
        self.assertEqual(report['errors'][0]['page_number'], 2)
        self.assertEqual(report['results'][-1]['page_number'], 5)

    def test_full_queue_dry_run_does_not_load_model_or_write_outputs(self):
        report = self.fixture.run_stage(until_done=True, dry_run=True)
        self.assertTrue(report['until_done'])
        self.assertFalse(self.fixture.settings['output_root'].exists())
        self.assertEqual(self.fixture.engine.calls, 0)

    def test_empty_collection_scope_does_not_process_unselected_documents(self):
        report = self.fixture.run_stage(until_done=True, allowed_doc_ids=[])
        self.assertEqual(report['planned'], [])
        self.assertEqual(self.fixture.engine.calls, 0)

    def test_registered_image_is_included_with_pdf_pages(self):
        from PIL import Image
        from pipeline.processing.import_image import import_image
        image = self.fixture.root / 'source.png'
        Image.new('RGB', (40, 60), 'white').save(image)
        imported = import_image(self.fixture.settings, [downloads.SOURCE], image, 'school',
                                'https://school.test/source.png', 'Standalone source image')
        self.fixture.settings.update(max_pages=1, max_documents=1)
        report = self.fixture.run_stage(until_done=True)
        self.assertEqual(report['errors'], [])
        self.assertEqual(len(report['results']), 6)
        self.assertEqual(report['results'][-1]['doc_id'], imported['doc_id'])

    def test_notebook_defaults_process_whole_store_without_page_or_document_selection(self):
        notebook = json.loads((workflow.ROOT / 'notebooks/corpus_pipeline_colab.ipynb').read_text())
        cell = next(c for c in notebook['cells'] if c['id'] == 'corpus-production-13')
        calls = []
        def execute(*args, **kwargs):
            calls.append((args, kwargs))
            return {'stop_reason': 'queue_finished', 'outcomes': {'truncated': 1}, 'errors': [], 'warnings': []}
        def no_selection(): raise AssertionError('All-store mode should not select DOC_IDS')
        with contextlib.redirect_stdout(io.StringIO()):
            exec(''.join(cell['source']), {'PAGE_NUMBERS': None, 'PROCESS_ALL_AVAILABLE': True,
                 'RUN_UNTIL_DONE': True, 'selection_args': no_selection, 'CONFIG': Path('/config'),
                 'COLLECTION_POLICY': Path('/policy'), 'execute': execute})
        args, kwargs = calls[0]
        self.assertIn('--until-done', args)
        self.assertNotIn('--doc-id', args)
        self.assertNotIn('--page-number', args)
        self.assertTrue(kwargs['allow_partial'])

    def test_workflow_cli_forwards_full_queue_mode(self):
        result = {'schema_version': 'page-processing-run-1', 'results': [], 'errors': []}
        with patch.object(sys, 'argv', ['workflow', 'process', '--until-done']), \
             patch.object(workflow.pages, 'load_settings', return_value={}), \
             patch.object(workflow.extractor, 'load_settings', return_value={}), \
             patch.object(workflow.pages, 'run', return_value=result) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(), 0)
        self.assertTrue(run.call_args.kwargs['until_done'])


class ColabPartialReportTests(unittest.TestCase):
    def invoke(self, code, stdout, allow_partial):
        result = subprocess.CompletedProcess(['workflow'], code, stdout)
        with patch.object(colab.subprocess, 'run', return_value=result), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return colab.execute('/python', Path('/repo'), 'process', allow_partial=allow_partial)

    def test_valid_partial_report_returns_but_remains_visibly_incomplete(self):
        report = {'schema_version': 'page-processing-run-1',
                  'results': [{'outcome': 'truncated'}], 'errors': []}
        self.assertEqual(self.invoke(1, json.dumps(report), True), report)
        with self.assertRaises(subprocess.CalledProcessError): self.invoke(1, json.dumps(report), False)

    def test_setup_failure_invalid_json_and_other_command_failure_are_not_suppressed(self):
        for code, stdout in ((2, ''), (1, 'not JSON'), (1, '{"schema_version":"download-run-1"}')):
            with self.subTest(code=code, stdout=stdout), self.assertRaises(subprocess.CalledProcessError):
                self.invoke(code, stdout, True)
