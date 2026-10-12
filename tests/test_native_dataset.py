import csv
import json
from pathlib import Path
import unittest

from pipeline.cleaning.native import clean, reasons
from pipeline.dataset.native import prepare, export
from pipeline.extraction import extractor
import test_extraction as fixtures
from test_extraction import FakeBackend, NATIVE, BLANK


class NativeDatasetTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ExtractionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        backend = FakeBackend()
        backend.pages = [NATIVE, BLANK]
        fixture.backend = backend
        fixture.run_stage(progress_mode='off')
        self.packet = fixture.root / 'native-review'
        self.output = fixture.root / 'dataset'

    def prepare(self, **kwargs):
        return prepare(self.fixture.settings['output_root'], self.fixture.settings['catalog_path'],
                       self.packet, min_chars=10, **kwargs)

    def approve(self, split='train'):
        path = self.packet / 'review.csv'
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            row.update(decision='approve', reviewer='reviewer', review_notes='Compared full page with PDF',
                       rights_evidence='Fixture material created for this test', split=split)
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_mixed_pdf_keeps_native_page_and_quarantines_blank(self):
        catalog = self.fixture.settings['catalog_path'].read_bytes()
        report = self.prepare()
        self.assertEqual((report['candidates'], report['rejected']), (1, 1))
        self.assertFalse(report['training_approved'])
        self.assertEqual(catalog, self.fixture.settings['catalog_path'].read_bytes())
        record = json.loads((self.packet / 'candidates.jsonl').read_text())
        self.assertEqual(record['raw_sha256'], self.fixture.row['sha256'])
        self.assertIn('සිංහල', record['text'])

    def test_dry_run_and_pending_export_never_write_dataset(self):
        self.prepare(dry_run=True)
        self.assertFalse(self.packet.exists())
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'No approved'):
            export(self.packet, self.output)
        self.assertFalse(self.output.exists())

    def test_approved_release_snapshots_evidence_and_refuses_overwrite(self):
        self.prepare()
        self.approve()
        report = export(self.packet, self.output)
        self.assertEqual(report['counts'], {'train': 1})
        record = json.loads((self.output / 'train.jsonl').read_text())
        self.assertTrue(record['training_approved'])
        self.assertEqual((self.packet / 'review.csv').read_bytes(), (self.output / 'review.csv').read_bytes())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            export(self.packet, self.output)

    def test_tampered_candidate_or_missing_review_fails(self):
        self.prepare()
        self.approve()
        path = self.packet / 'candidates.jsonl'
        path.write_text(path.read_text().replace('සිංහල', 'changed'))
        with self.assertRaisesRegex(ValueError, 'Packet changed'):
            export(self.packet, self.output)

    def test_incomplete_approval_and_missing_review_fail(self):
        self.prepare()
        self.approve()
        path = self.packet / 'review.csv'
        original = path.read_text()
        path.write_text(original.replace('Fixture material created for this test', ''))
        with self.assertRaisesRegex(ValueError, 'rights evidence'):
            export(self.packet, self.output)
        path.write_text(original.splitlines()[0] + '\n')
        with self.assertRaisesRegex(ValueError, 'review IDs'):
            export(self.packet, self.output)

    def test_extraction_hash_corruption_fails_before_packet(self):
        path = next(self.fixture.settings['output_root'].rglob('pages.jsonl'))
        path.write_text('tampered')
        with self.assertRaises(extractor.ExtractionError):
            self.prepare()
        self.assertFalse(self.packet.exists())

    def test_split_and_exact_duplicate_rules(self):
        backend = FakeBackend()
        backend.pages = [NATIVE, NATIVE]
        settings = {**self.fixture.settings, 'output_root': self.fixture.root / 'new-extraction'}
        extractor.run(settings, backend=backend, progress_mode='off')
        prepare(settings['output_root'], settings['catalog_path'], self.packet, min_chars=10)
        self.approve()
        report = export(self.packet, self.output)
        self.assertEqual(report['counts'], {'train': 1})
        self.assertEqual(len(report['duplicates']), 1)
        path = self.packet / 'review.csv'
        path.write_text(path.read_text().replace(',train', ',validation', 1))
        with self.assertRaisesRegex(ValueError, 'multiple splits'):
            export(self.packet, self.fixture.root / 'bad-split')

    def test_conservative_cleaning_preserves_joiners_units_negation(self):
        text = 'නොවේ\u200d\u200c 10 kg\r\n$x^2$'
        self.assertEqual(clean(text), 'නොවේ\u200d\u200c 10 kg\n$x^2$')
        page = {'extraction_method': 'poppler-bbox-layout', 'ocr_required': False}
        self.assertIn('little_sinhala_or_legacy_font', reasons(page, 'legacy latin font text' * 10))
        self.assertIn('replacement_character', reasons(page, '\ufffd' + text))


if __name__ == '__main__':
    unittest.main()
