import ast
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pipeline.dataset import native, reviewed
from pipeline.discovery import crawler
from pipeline.discovery.parser import Link, evaluate_link
from pipeline.download import downloader
from pipeline.ocr import images
from pipeline.processing import pages
from pipeline.processing.import_image import import_image
from scripts.repair_store_paths import repair
import test_download as download_fixtures
import test_processing_pipeline as processing_fixtures


class DownloadReliabilityTests(unittest.TestCase):
    def test_unknown_source_is_excluded_without_crashing(self):
        row = {'doc_id': 'LK-EDU-000001', 'source': '', 'source_url': '', 'status': 'DISCOVERED'}
        jobs, excluded = downloader.plan_downloads([row], [download_fixtures.SOURCE])
        self.assertEqual(jobs, [])
        self.assertEqual(len(excluded), 1)

    def test_explicit_cdn_host_is_accepted_but_unknown_host_is_not_requested(self):
        fetcher = crawler.PoliteFetcher(0, 1, logging.getLogger(__name__),
                                       allowed_hosts={'school.test', 'cdn.test'})
        response = download_fixtures.Response(final='https://cdn.test/a.pdf')
        with patch.object(fetcher, 'robots_allowed', return_value=True), patch.object(fetcher, '_request', return_value=response) as request:
            self.assertIs(fetcher.open_resource('https://cdn.test/a.pdf', 'https://school.test/'), response)
            self.assertIsNone(fetcher.open_resource('https://evil.test/a.pdf', 'https://school.test/'))
            self.assertEqual(request.call_count, 1)

    def test_govdoc_does_not_invent_metadata_or_rewrite_arbitrary_query_ids(self):
        import yaml
        config = yaml.safe_load(crawler.SUBJECTS_PATH.read_text())
        source = {**download_fixtures.SOURCE, 'id': 'govdoc', 'base_url': 'https://govdoc.lk/'}
        candidate, _ = evaluate_link(Link('/downloadFile/123', 'Sinhala'), 'Download Resources',
                                     source['base_url'], source, config)
        self.assertEqual([candidate[k] for k in ('subject', 'domain', 'grade', 'language')], ['', '', '', ''])
        self.assertEqual(candidate['document_type'], 'other')
        candidate, _ = evaluate_link(Link('/category?id=123', 'Sinhala'), 'Download Resources',
                                     source['base_url'], source, config)
        self.assertIsNone(candidate)

    def test_publish_recovers_after_process_dies_and_ignores_staging(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / 'release'
            code = ("import os,sys; from pathlib import Path; from unittest.mock import patch; "
                    "from pipeline.dataset.native import publish; "
                    "patch('pipeline.dataset.native.os.rename', side_effect=lambda *a: os._exit(77)).start(); "
                    "publish(Path(sys.argv[1]), {'manifest.json':b'{}'})")
            result = subprocess.run([sys.executable, '-B', '-c', code, str(output)])
            self.assertEqual(result.returncode, 77)
            self.assertEqual(list(native.visible_manifests(output.parent)), [])
            native.publish(output, {'manifest.json': b'{}'})
            self.assertEqual(list(native.visible_manifests(output.parent)), [output / 'manifest.json'])
            with self.assertRaises(ValueError): native.publish(output, {'manifest.json': b'changed'})


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = processing_fixtures.ProductionPipelineTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def test_failed_ocr_requires_retry_and_preserves_first_attempt(self):
        healthy = self.fixture.engine.recognize
        self.fixture.engine.recognize = lambda _: {'text': '', 'outcome': 'failed', 'completion_status': 'failed'}
        first = self.fixture.run_stage()
        first_folder = Path(first['results'][0]['bundle'])
        before = (first_folder / 'page.json').read_bytes()
        self.assertTrue(pages.has_failures(first))
        self.fixture.engine.recognize = healthy
        reused = self.fixture.run_stage()
        self.assertEqual(reused['results'][0]['outcome'], 'existing_incomplete')
        self.assertTrue(pages.has_failures(reused))
        second = self.fixture.run_stage(retry_incomplete=True)
        self.assertFalse(pages.has_failures(second))
        self.assertNotEqual(second['results'][0]['bundle'], str(first_folder))
        self.assertEqual(before, (first_folder / 'page.json').read_bytes())
        self.assertEqual(self.fixture.run_stage()['results'][0]['bundle'], second['results'][0]['bundle'])
        reviewed.prepare(self.fixture.settings['output_root'], self.fixture.packet)
        self.assertEqual(len((self.fixture.packet / 'records.jsonl').read_text().splitlines()), 1)

    def test_empty_prediction_is_a_failure(self):
        self.fixture.engine.recognize = lambda _: {'text': ' ', 'outcome': 'predicted', 'completion_status': 'complete'}
        result = self.fixture.run_stage()
        self.assertEqual(result['results'][0]['outcome'], 'empty')
        self.assertTrue(pages.has_failures(result))


class PathRepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture = download_fixtures.DownloadTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.execute()
        self.catalog = self.fixture.settings['catalog_path']
        self.raw = self.fixture.settings['raw_root']
        self.row = crawler.read_catalog(self.catalog)[0]
        self.artifact = Path(self.row['local_filename'])
        self.receipt = self.artifact.with_suffix('.json')
        self.row['local_filename'] = '/old-vm/raw/' + self.artifact.name
        self.fixture.write_catalog([self.row])

    def test_real_catalog_mismatch_preview_backup_repair_and_idempotence(self):
        with self.assertRaisesRegex(downloader.DownloadError, 'Catalog and raw artifact path disagree'):
            downloader.recover(self.row, self.raw)
        catalog_before, raw_before = self.catalog.read_bytes(), self.artifact.read_bytes()
        files_before = set(self.fixture.root.rglob('*'))
        preview = repair(self.catalog, self.raw, [self.row['doc_id']])
        self.assertTrue(preview['changed'])
        self.assertEqual(self.catalog.read_bytes(), catalog_before)
        self.assertEqual(set(self.fixture.root.rglob('*')), files_before)
        result = repair(self.catalog, self.raw, [self.row['doc_id']], apply=True)
        self.assertEqual((Path(result['backup']) / 'documents.csv').read_bytes(), catalog_before)
        self.assertEqual(self.artifact.read_bytes(), raw_before)
        self.assertEqual(downloader.recover(crawler.read_catalog(self.catalog)[0], self.raw)['sha256'], self.row['sha256'])
        self.assertFalse(repair(self.catalog, self.raw, [self.row['doc_id']], apply=True)['changed'])

    def test_receipt_path_relocation_is_repaired_and_corruption_refuses_all_writes(self):
        receipt = json.loads(self.receipt.read_text()); receipt['local_filename'] = self.row['local_filename']
        self.receipt.write_text(json.dumps(receipt))
        repair(self.catalog, self.raw, [self.row['doc_id']], apply=True)
        self.assertEqual(json.loads(self.receipt.read_text())['local_filename'], str(self.artifact))
        self.artifact.write_bytes(b'corrupt')
        before = self.catalog.read_bytes(), self.receipt.read_bytes()
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            repair(self.catalog, self.raw, [self.row['doc_id']], apply=True)
        self.assertEqual(before, (self.catalog.read_bytes(), self.receipt.read_bytes()))

    def test_colab_import_updates_an_existing_matching_hash_with_a_stale_vm_path(self):
        import shutil
        import yaml
        from pipeline import workflow
        root = self.fixture.root
        store = root / 'production'
        workflow.initialize(store, self.catalog)
        (store / 'configs/sources.yaml').write_text(yaml.safe_dump({'sources': [download_fixtures.SOURCE]}))
        target_catalog = store / 'corpus/catalog/documents.csv'
        target_catalog.write_bytes(self.catalog.read_bytes())
        stage = root / 'vm-import'
        stage.mkdir()
        shutil.copyfile(self.catalog, stage / 'documents.csv')
        shutil.copytree(self.artifact.parent, stage / 'pdf' / self.row['doc_id'])
        notebook = json.loads((crawler.ROOT / 'notebooks/corpus_pipeline_colab.ipynb').read_text())
        cell = next(c for c in notebook['cells'] if c.get('id') == 'a139d27e')
        namespace = {'STORE': store, 'ROOT': crawler.ROOT, 'DOC_IDS': [self.row['doc_id']],
                     'PYTHON': sys.executable, 'IMPORT_VM_PDFS': True}
        exec(compile(''.join(cell['source']), 'colab_import', 'exec'), namespace)
        row = crawler.read_catalog(target_catalog)[0]
        receipt = downloader.recover(row, store / 'corpus/raw')
        self.assertEqual(row['sha256'], self.row['sha256'])
        self.assertEqual(row['local_filename'], receipt['local_filename'])


class NotebookTests(unittest.TestCase):
    def test_notebook_and_embedded_scripts_parse_and_config_keeps_all_selected_documents(self):
        import yaml
        notebook = json.loads((crawler.ROOT / 'notebooks/corpus_pipeline_colab.ipynb').read_text())
        config_code = None
        for cell in notebook['cells']:
            if cell['cell_type'] != 'code': continue
            tree = ast.parse(''.join(cell['source']))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.endswith('_code'):
                            ast.parse(node.value.value)
                            if target.id == 'configure_code': config_code = node.value.value
        self.assertIsNotNone(config_code)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pipeline.yaml'
            path.write_bytes((crawler.ROOT / 'configs/pipeline.yaml').read_bytes())
            subprocess.run([sys.executable, '-B', '-c', config_code, str(path), '/models', 'a' * 64,
                            '30', '5', '{"grayscale": true}', '2'], check=True)
            config = yaml.safe_load(path.read_text())
            self.assertEqual(config['download']['max_documents'], 5)
            self.assertEqual(config['processing']['max_documents'], 5)
            self.assertEqual(config['processing']['preprocessing'], {'grayscale': True})
            self.assertEqual(config['processing']['ocr']['columns'], 2)


class ImageImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = processing_fixtures.ProductionPipelineTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.image = self.fixture.root / 'input.png'
        from PIL import Image
        Image.new('RGB', (80, 100), 'white').save(self.image)

    def test_import_png_process_preprocess_and_prepare_review_without_pdf_tools(self):
        settings = self.fixture.settings
        args = (settings, [download_fixtures.SOURCE], self.image, 'school',
                'https://school.test/image.png', 'Sinhala scanned page')
        catalog_before = settings['catalog_path'].read_bytes()
        self.assertTrue(import_image(*args, dry_run=True)['dry_run'])
        self.assertEqual(settings['catalog_path'].read_bytes(), catalog_before)
        imported = import_image(*args)
        self.assertEqual(import_image(*args)['outcome'], 'verified_existing')
        settings['preprocessing'] = {'crop': [0, 0, 0.5, 1], 'grayscale': True}
        with patch.object(pages.shutil, 'which', return_value=None), patch.object(pages, 'PopplerBackend', side_effect=AssertionError('PDF tool loaded')):
            report = pages.run(settings, self.fixture.fixture.settings, doc_ids=[imported['doc_id']],
                               engine=self.fixture.engine, progress_mode='off')
        self.assertEqual(report['errors'], [])
        folder = Path(report['results'][0]['bundle'])
        self.assertTrue((folder / 'ocr_input.png').is_file())
        record = json.loads((folder / 'page.json').read_text())
        self.assertEqual(record['preprocessing']['output_dimensions'], [40, 100])
        self.assertEqual((settings['raw_root'] / 'png' / imported['doc_id'] / (imported['sha256'] + '.png')).read_bytes(), self.image.read_bytes())
        reviewed.prepare(settings['output_root'], self.fixture.packet)
        self.assertEqual(len((self.fixture.packet / 'records.jsonl').read_text().splitlines()), 1)

    def test_invalid_images_limits_and_options_are_rejected(self):
        with self.assertRaises(Exception): images.decode(b'not an image')
        with self.assertRaisesRegex(ValueError, 'pixel limit'): images.decode(self.image.read_bytes(), 100)
        for options in ({'rotate_degrees': 90}, {'crop': [0, 1, 0, 1]}, {'automatic': True}):
            with self.subTest(options=options), self.assertRaises(ValueError): images.validate_options(options)

    def test_jpeg_and_explicit_two_column_order(self):
        from PIL import Image
        stream = io.BytesIO(); Image.new('RGB', (30, 40)).save(stream, 'JPEG')
        page, kind = images.decode(stream.getvalue())
        self.assertEqual((page.size, kind), ((30, 40), 'jpg'))
        lines = [{'bbox': [0, 0, 100, 10]}, {'bbox': [60, 20, 90, 30]},
                 {'bbox': [0, 30, 40, 40]}, {'bbox': [0, 20, 40, 30]}]
        self.assertEqual(images.reading_order(lines, 100, 2), [0, 3, 2, 1])
        self.assertEqual(images.reading_order(lines, 100), [0, 1, 2, 3])
