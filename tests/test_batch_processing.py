import json
from pathlib import Path
import unittest

import yaml

from pipeline import workflow
from pipeline.discovery.crawler import read_catalog
from pipeline.download import downloader
from pipeline.processing import batch, pages
from tests import test_download as fixtures


class BatchProcessingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DownloadTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.store = self.root / 'store'
        workflow.initialize(self.store, self.fixture.settings['catalog_path'])
        self.config = self.store / 'configs/pipeline.yaml'
        self.sources = self.store / 'configs/sources.yaml'
        self.sources.write_text(yaml.safe_dump({'sources': [fixtures.SOURCE]}))
        self.settings = yaml.safe_load(self.config.read_text())
        self.settings['download']['max_documents'] = 1
        self.settings['processing']['max_pages'] = 2
        self.config.write_text(yaml.safe_dump(self.settings))
        self.calls, self.done = [], set()
        self.doc = self.fixture.row['doc_id']

    def stage(self, command, config, doc_ids, sources_path, progress):
        self.calls.append((command, list(doc_ids), yaml.safe_load(config.read_text())))
        if command == 'collect':
            self.fixture.settings = downloader.load_settings(config)
            return self.fixture.execute(doc_ids=doc_ids)
        settings = pages.load_settings(config)
        results, used = [], 0
        for doc_id in doc_ids:
            for number in range(1, 5):
                key = (doc_id, number)
                if key not in self.done and used >= settings['max_pages']:
                    return {'results': results, 'errors': [], 'stop_reason': 'batch_page_limit'}
                outcome = 'verified_existing' if key in self.done else 'predicted'
                if key not in self.done: self.done.add(key); used += 1
                results.append({'doc_id': doc_id, 'page_number': number, 'outcome': outcome,
                                'bundle': str(self.root / doc_id / str(number))})
        return {'results': results, 'errors': [], 'stop_reason': 'queue_finished'}

    def run_batch(self, **kwargs):
        return batch.run(self.config, stage_runner=self.stage, progress_mode='off', **kwargs)

    def test_collect_process_resume_and_total_page_cap(self):
        result = self.run_batch(max_download_jobs=1, max_new_pages=3, max_batches=4)
        self.assertEqual(result['new_pages'], 3)
        self.assertEqual(result['download_jobs_reserved'], 1)
        self.assertEqual(result['stop_reason'], 'new_page_limit')
        self.assertEqual([call[0] for call in self.calls], ['collect', 'process', 'process'])
        self.assertEqual(self.calls[-1][2]['processing']['max_pages'], 1)
        self.assertFalse(result['training_approved'])
        self.assertEqual(json.loads(Path(result['report_path']).read_text()), result)
        self.calls.clear()
        resumed = self.run_batch(max_new_pages=2)
        self.assertEqual(resumed['new_pages'], 1)
        self.assertEqual([call[0] for call in self.calls], ['process'])
        self.assertEqual(resumed['outcomes']['verified_existing'], 3)

    def test_dry_run_has_no_children_network_or_writes(self):
        before = {str(path): path.read_bytes() for path in self.store.rglob('*') if path.is_file()}
        result = self.run_batch(dry_run=True)
        self.assertEqual(result['download_planned'], [self.doc])
        self.assertEqual(result['processing_planned'], [])
        self.assertEqual(self.calls, [])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.store.rglob('*') if path.is_file()})

    def test_completion_unverified_bundle_consumes_new_page_budget(self):
        def unverified(command, config, ids, sources, progress):
            result = self.stage(command, config, ids, sources, progress)
            if command == 'process':
                for row in result['results']:
                    if row['outcome'] == 'predicted': row['outcome'] = 'completion_unverified'
            return result
        result = batch.run(self.config, stage_runner=unverified, max_batches=5, max_new_pages=3)
        self.assertEqual(result['new_pages'], 3)
        self.assertEqual(result['stop_reason'], 'new_page_limit')
        self.assertEqual(result['outcomes']['completion_unverified'], 3)
        self.assertEqual(len(result['batches']), 2)
        self.assertEqual(self.calls[-1][2]['processing']['max_pages'], 1)

    def test_source_and_document_selection_and_invalid_limits(self):
        self.assertEqual(self.run_batch(source_id='school', doc_ids=[self.doc], dry_run=True)['download_planned'], [self.doc])
        for kwargs in ({'source_id': 'unknown'}, {'doc_ids': ['missing']}, {'max_batches': 0}, {'max_new_pages': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.run_batch(**kwargs)

    def test_failure_is_attempted_once_per_run_without_blocking_other_resources(self):
        second = {**self.fixture.row, 'doc_id': 'LK-EDU-000010', 'source_url': 'https://school.test/second.pdf'}
        self.fixture.settings = downloader.load_settings(self.config)
        self.fixture.write_catalog([self.fixture.row, second])
        attempted = []
        def failing_collect(command, config, ids, sources, progress):
            if command == 'collect' and self.doc in ids:
                attempted.append(self.doc)
                return {'results': [{'doc_id': self.doc, 'outcome': 'failed', 'error': 'fixture failure'}]}
            return self.stage(command, config, ids, sources, progress)
        result = batch.run(self.config, stage_runner=failing_collect, max_batches=4, max_download_jobs=2, max_new_pages=10, progress_mode='off')
        self.assertEqual(attempted, [self.doc])
        self.assertEqual(result['download_jobs_reserved'], 2)
        self.assertEqual(result['new_pages'], 4)
        self.assertEqual(len(result['errors']), 1)

    def test_stage_setup_failure_saves_journal(self):
        def broken(*args): raise RuntimeError('GPU setup failed')
        with self.assertRaisesRegex(RuntimeError, 'GPU setup failed'):
            batch.run(self.config, stage_runner=broken)
        log = next((self.store / 'corpus/logs/batch').glob('*/run.json'))
        result = json.loads(log.read_text())
        self.assertEqual(result['stop_reason'], 'stage_failed')
        self.assertEqual(result['active_phase'], 'finished')
        self.assertIn('GPU setup failed', result['errors'][0]['error'])

    def test_processing_errors_are_not_retried_in_the_same_run(self):
        self.fixture.settings = downloader.load_settings(self.config)
        self.fixture.execute()
        calls = []
        def failed(command, config, ids, sources, progress):
            calls.append(ids)
            return {'results': [], 'errors': [{'doc_id': self.doc, 'error': 'bad PDF'}], 'stop_reason': 'queue_finished'}
        result = batch.run(self.config, stage_runner=failed, max_batches=3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['errors'][0]['stage'], 'process')

    def test_catalog_and_raw_root_mismatches_are_rejected_before_writes(self):
        self.settings['extraction']['raw_root'] = str(self.root / 'different-raw')
        self.config.write_text(yaml.safe_dump(self.settings))
        with self.assertRaisesRegex(ValueError, 'same catalog and raw root'): self.run_batch()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.store / 'corpus/logs/batch').exists())

    def test_source_scope_never_collects_another_sources_document(self):
        other = {**fixtures.SOURCE, 'id': 'other', 'name': 'Other', 'base_url': 'https://other.test/'}
        self.sources.write_text(yaml.safe_dump({'sources': [fixtures.SOURCE, other]}))
        second = {**self.fixture.row, 'doc_id': 'LK-EDU-000010', 'source': 'Other', 'source_url': 'https://other.test/file.pdf'}
        self.fixture.settings = downloader.load_settings(self.config)
        self.fixture.write_catalog([self.fixture.row, second])
        result = self.run_batch(source_id='school', max_new_pages=1)
        self.assertEqual(result['new_pages'], 1)
        self.assertTrue(all(call[1] == [self.doc] for call in self.calls))
        other_row = read_catalog(self.fixture.settings['catalog_path'])[1]
        self.assertEqual(other_row['status'], 'DISCOVERED')

    def test_real_isolated_child_processes_static_html_without_gpu(self):
        self.fixture.settings = downloader.load_settings(self.config)
        html = b'<!doctype html><html><main><h1>School lesson</h1><p>Source text for review.</p></main></html>'
        fixtures.Fetcher.response_factory = staticmethod(lambda: fixtures.Response(html, mime='text/html'))
        self.fixture.execute()
        report = batch.child('process', self.config, [self.doc], self.sources, 'off')
        self.assertEqual(report['child_exit_code'], 0)
        source = json.loads((Path(report['results'][0]['bundle']) / 'page.json').read_text())
        self.assertEqual(source['method'], 'html')
        self.assertFalse(source['training_approved'])
        self.assertEqual(read_catalog(self.fixture.settings['catalog_path'])[0]['status'], 'DOWNLOADED')
