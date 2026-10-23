import json
from pathlib import Path
import struct
import shutil
import unittest
from unittest.mock import patch

from pipeline.dataset import reviewed
from pipeline.processing import pages
from pipeline.ocr import backends
import test_extraction as fixtures
import test_download as download_fixtures

PNG = b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 100, 100)


class Engine:
    identity = {'engine': 'fixture-surya', 'model_sha256': 'a' * 64}
    def __init__(self): self.calls = 0
    def recognize(self, path):
        self.calls += 1
        return {'text': 'සිංහල පෙළ ' * 15, 'outcome': 'predicted', 'completion_status': 'complete',
                'raw_result': {'text_lines': [{'text': 'සිංහල පෙළ', 'bbox': [0, 0, 10, 10], 'confidence': 0.9}]}}


class ProductionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExtractionTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.settings = {'catalog_path': self.fixture.settings['catalog_path'], 'raw_root': self.fixture.settings['raw_root'],
                         'output_root': self.root / 'processed', 'log_root': self.root / 'processing-logs',
                         'max_documents': 2, 'max_pages': 2, 'dpi': 300, 'max_image_side': 3000,
                         'render_timeout_seconds': 60, 'max_image_bytes': 52428800, 'ocr_mode': 'all',
                         'ocr': {'backend': 'surya', 'model_path': '/fixture/models', 'revision': 'a' * 64, 'max_page_seconds': 120}}
        self.engine = Engine()
        self.packet = self.root / 'review'
        self.release = self.root / 'release'

    def run_stage(self, **kwargs):
        def command(argv, **kwargs): return b'fixture-renderer-v1' if '-v' in argv else PNG
        with patch.object(pages, 'command', side_effect=command), patch.object(pages.shutil, 'which', return_value='/fixture/pdftoppm'):
            return pages.run(self.settings, self.fixture.settings, engine=self.engine, pdf_backend=self.fixture.backend,
                             progress_mode='off', **kwargs)

    def test_complete_pdf_to_corrected_reviewed_training_release(self):
        catalog = self.settings['catalog_path'].read_bytes()
        report = self.run_stage()
        bundle = Path(report['results'][0]['bundle'])
        original = json.loads((bundle / 'page.json').read_text())
        self.assertEqual(original['ocr_backend'], 'surya')
        self.assertFalse(original['training_approved'])
        self.assertEqual(original['prediction']['raw_result']['text_lines'][0]['confidence'], 0.9)
        reviewed.prepare(self.settings['output_root'], self.packet)
        record = json.loads((self.packet / 'records.jsonl').read_text())
        corrected = 'සිංහල නිවැරදි පාඩම ' * 15
        (self.packet / record['text_path']).write_text(corrected)
        reviewed.seal(self.packet, record['record_id'], 'Transcriber', 'Verifier', 'Fixture rights', 'Full source checked', 'train')
        result = reviewed.export(self.packet, self.release)
        self.assertEqual(result['counts'], {'train': 1})
        exported = json.loads((self.release / 'train.jsonl').read_text())
        self.assertTrue(exported['human_corrected']); self.assertTrue(exported['training_approved'])
        self.assertEqual(exported['source_identity']['raw_sha256'], self.fixture.row['sha256'])
        self.assertEqual(catalog, self.settings['catalog_path'].read_bytes())
        self.assertEqual(original, json.loads((bundle / 'page.json').read_text()))
        self.assertEqual(reviewed.verify_release(self.release)['status'], 'verified_artifacts')
        (self.release / 'train.jsonl').write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'Release artifact changed'):
            reviewed.verify_release(self.release)

    def test_resume_verifies_without_recognition_and_rejects_corruption(self):
        first = self.run_stage()
        report = self.run_stage()
        self.assertEqual(report['outcomes'], {'verified_existing': 1})
        self.assertEqual(self.engine.calls, 1)
        Path(first['results'][0]['bundle'], 'text.txt').write_text('tampered')
        self.assertEqual(len(self.run_stage()['errors']), 1)

    def test_batch_limit_continues_remaining_pages(self):
        self.fixture.backend.pages = [fixtures.NATIVE, fixtures.NATIVE, fixtures.NATIVE]
        first = self.run_stage()
        self.assertEqual(first['stop_reason'], 'batch_page_limit')
        self.assertEqual(self.engine.calls, 2)
        second = self.run_stage()
        self.assertEqual(second['outcomes'], {'verified_existing': 2, 'predicted': 1})
        self.assertEqual(self.engine.calls, 3)

    def test_explicit_pages_save_gpu_work_and_out_of_range_is_skipped(self):
        self.fixture.backend.pages = [fixtures.NATIVE] * 3
        result = self.run_stage(page_numbers=[3])
        self.assertEqual([r['page_number'] for r in result['results']], [3])
        self.assertEqual(self.engine.calls, 1)
        missing = self.run_stage(page_numbers=[4])
        self.assertEqual(missing['errors'], [])
        self.assertEqual(missing['results'], [])
        self.assertEqual(missing['warnings'][0]['skipped_page_numbers'], [4])

    def test_dry_run_never_loads_gpu_or_writes_outputs(self):
        with patch.object(backends, 'create', side_effect=AssertionError('GPU loaded')):
            report = self.run_stage(dry_run=True)
        self.assertTrue(report['dry_run'])
        self.assertFalse(self.settings['output_root'].exists())
        self.assertFalse(self.settings['log_root'].exists())

    def test_incomplete_ocr_never_auto_approved(self):
        self.engine.recognize = lambda _: {'text': 'සිංහල ' * 20, 'outcome': 'truncated', 'completion_status': 'region_incomplete'}
        result = self.run_stage()['results'][0]
        self.assertIn('incomplete_or_failed_prediction', result['quality_flags'])
        reviewed.prepare(self.settings['output_root'], self.packet)
        with self.assertRaisesRegex(ValueError, 'No approved'):
            reviewed.export(self.packet, self.release)
        self.assertFalse(self.release.exists())

    def test_two_reviewers_required_and_post_approval_edits_invalidated(self):
        self.run_stage(); reviewed.prepare(self.settings['output_root'], self.packet)
        record = json.loads((self.packet / 'records.jsonl').read_text())
        sid = record['record_id']
        with self.assertRaisesRegex(ValueError, 'different reviewers'):
            reviewed.seal(self.packet, sid, 'Alice', 'alice', 'Fixture', 'Checked', 'train')
        reviewed.seal(self.packet, sid, 'Alice', 'Bob', 'Fixture', 'Checked', 'train')
        (self.packet / record['text_path']).write_text('වෙනස් කළ පෙළ')
        with self.assertRaisesRegex(ValueError, 'changed since approval'):
            reviewed.export(self.packet, self.release)
        reviewed.seal(self.packet, sid, 'Alice', 'Bob', 'Fixture', 'Rechecked correction', 'train')
        reviewed.export(self.packet, self.release)

    def test_configuration_change_preserves_previous_version(self):
        first = self.run_stage()
        self.settings['ocr']['revision'] = 'b' * 64
        second = self.run_stage()
        self.assertNotEqual(first['results'][0]['bundle'], second['results'][0]['bundle'])
        with self.assertRaisesRegex(ValueError, 'Multiple processing versions'):
            reviewed.prepare(self.settings['output_root'], self.packet)

    def test_revised_source_pdf_cannot_cross_train_validation_splits(self):
        self.run_stage()
        download_fixtures.Fetcher.response_factory = staticmethod(lambda: download_fixtures.Response(download_fixtures.PDF.replace(b'fixture', b'revised fixture')))
        self.fixture.fixture.execute(refresh=True)
        self.run_stage()
        reviewed.prepare(self.settings['output_root'], self.packet)
        records = [json.loads(line) for line in (self.packet / 'records.jsonl').read_text().splitlines()]
        self.assertEqual(len(records), 2)
        for index, record in enumerate(records):
            reviewed.seal(self.packet, record['record_id'], 'Alice', 'Bob', 'Fixture', 'Source checked', 'train' if index == 0 else 'validation')
        with self.assertRaisesRegex(ValueError, 'source version crosses splits'):
            reviewed.export(self.packet, self.release)

    def test_unreadable_correction_cannot_be_approved(self):
        self.run_stage(); reviewed.prepare(self.settings['output_root'], self.packet)
        record = json.loads((self.packet / 'records.jsonl').read_text())
        (self.packet / record['text_path']).write_text('[UNREADABLE]')
        with self.assertRaisesRegex(ValueError, 'unreadable'):
            reviewed.seal(self.packet, record['record_id'], 'Alice', 'Bob', 'Fixture', 'Checked', 'train')

    @unittest.skipUnless(all(shutil.which(name) for name in ('pdfinfo', 'pdftotext', 'pdftoppm')), 'Install Poppler for rendering integration')
    def test_real_pdf_native_extraction_and_source_image_rendering(self):
        download_fixtures.Fetcher.response_factory = staticmethod(lambda: download_fixtures.Response(fixtures.make_pdf()))
        self.fixture.fixture.execute(refresh=True)
        result = pages.run(self.settings, self.fixture.settings, engine=self.engine, progress_mode='off')
        self.assertFalse(result['errors'])
        folder = Path(result['results'][0]['bundle'])
        record = json.loads((folder / 'page.json').read_text())
        self.assertIn('History lesson', record['native_text'])
        self.assertEqual((folder / 'page.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertLessEqual(max(record['image_dimensions']), self.settings['max_image_side'])


if __name__ == '__main__': unittest.main()
