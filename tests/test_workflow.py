import csv
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pipeline import workflow
from pipeline.discovery import crawler
from pipeline.quality.text import flags
import test_download as fixtures


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DownloadTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def test_new_persistent_store_preserves_seed_and_resets_missing_artifacts(self):
        self.fixture.execute()
        seed = self.fixture.settings['catalog_path']
        original = seed.read_bytes()
        store = self.fixture.root / 'store'
        result = workflow.initialize(store, seed)
        self.assertEqual(result['reset_for_new_store'], 1)
        self.assertEqual((store / 'corpus/catalog/seed.csv').read_bytes(), original)
        row = crawler.read_catalog(store / 'corpus/catalog/documents.csv')[0]
        self.assertEqual(row['status'], 'DISCOVERED'); self.assertEqual(row['sha256'], '')
        self.assertEqual(seed.read_bytes(), original)
        settings = workflow.pages.load_settings(Path(result['config']))
        self.assertEqual(settings['raw_root'], store / 'corpus/raw')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            workflow.initialize(store, seed)

    def test_discovery_cli_storage_overrides_do_not_change_defaults(self):
        args = crawler.build_argument_parser().parse_args(['--catalog', '/tmp/catalog.csv', '--log-root', '/tmp/logs'])
        self.assertEqual(args.catalog, Path('/tmp/catalog.csv'))
        sources, subjects = crawler.load_configuration(catalog_path=self.fixture.settings['catalog_path'])
        self.assertTrue(sources); self.assertIn('domains', subjects)
        self.assertEqual(crawler.CATALOG_PATH, workflow.ROOT / 'corpus/catalog/documents.csv')

    def test_script_drift_and_repetition_are_warnings(self):
        self.assertIn('unexpected_script_needs_source_check', flags('विशेष विशेषताएँ'))
        self.assertIn('repeated_text_needs_source_check', flags('The state of the state of ' * 10))
        self.assertEqual(flags('සිංහල පාඩම 10 kg $x^2$'), [])


if __name__ == '__main__': unittest.main()
