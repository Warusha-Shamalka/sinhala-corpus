import json
import shutil
from pathlib import Path
import unittest

from pipeline.dataset import provisional
from pipeline.dataset.native import digest, encode
from tests import test_corpus_quality as fixtures


class ProvisionalExportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CorpusQualityTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.run = self.root / 'run.json'
        self.output = self.root / 'provisional'

    def report(self, **updates):
        value = {'schema_version': 'corpus-batch-run-1', 'active_phase': 'finished',
                 'processed_bundles': [str(path) for path in self.fixture.processed.iterdir()]}
        value.update(updates); self.run.write_text(json.dumps(value))

    def test_unreviewed_text_keeps_flags_and_never_grants_training_approval(self):
        self.fixture.add_page(1, 'partial Sinhala text', outcome='truncated', completion='region_incomplete')
        self.fixture.add_page(2, '', outcome='failed', completion='failed')
        self.report()
        result = provisional.export(self.run, self.output)
        self.assertEqual(result['pages'], 1)
        self.assertEqual(result['empty_pages_excluded'], 1)
        record = json.loads((self.output / 'provisional_text.jsonl').read_text())
        self.assertFalse(record['training_approved'])
        self.assertTrue(record['review_required'])
        self.assertEqual(record['completion_status'], 'region_incomplete')
        self.assertIn('incomplete_or_failed_prediction', record['quality_flags'])
        self.assertEqual(len((self.output / 'source_bundles.jsonl').read_text().splitlines()), 2)

    def test_running_or_empty_run_is_not_exported(self):
        self.fixture.add_page(1, 'text'); self.report(active_phase='process')
        with self.assertRaisesRegex(ValueError, 'finished'): provisional.export(self.run, self.output)
        self.report(processed_bundles=[])
        with self.assertRaisesRegex(ValueError, 'no processed'): provisional.export(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_corrupt_source_and_all_empty_text_are_rejected(self):
        self.fixture.add_page(1, ''); self.report()
        with self.assertRaisesRegex(ValueError, 'No nonempty'): provisional.export(self.run, self.output)
        bundle = Path(json.loads(self.run.read_text())['processed_bundles'][0])
        (bundle / 'text.txt').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'Corrupt'): provisional.export(self.run, self.output)

    def test_existing_provisional_snapshot_is_not_overwritten(self):
        self.fixture.add_page(1, 'text'); self.report()
        provisional.export(self.run, self.output)
        original = (self.output / 'manifest.json').read_bytes()
        with self.assertRaises(Exception): provisional.export(self.run, self.output)
        self.assertEqual((self.output / 'manifest.json').read_bytes(), original)

    def test_multiple_processing_versions_of_one_page_are_rejected(self):
        self.fixture.add_page(1, 'text')
        original = next(self.fixture.processed.iterdir())
        alternate = self.fixture.processed / 'alternate'
        shutil.copytree(original, alternate)
        record = json.loads((alternate / 'page.json').read_text())
        record['identity']['processing_config_sha256'] = 'b' * 64
        (alternate / 'page.json').write_bytes(encode(record))
        manifest = json.loads((alternate / 'manifest.json').read_text())
        manifest['identity'] = record['identity']
        manifest['output_sha256']['page.json'] = digest((alternate / 'page.json').read_bytes())
        (alternate / 'manifest.json').write_bytes(encode(manifest))
        self.report()
        with self.assertRaisesRegex(ValueError, 'Multiple processing versions'):
            provisional.export(self.run, self.output)
