"""Invented metadata fixtures; no benchmark content."""
import csv
import json
import subprocess
import sys
import unittest

from pipeline.dataset import pair_index
from pipeline.metadata import paper_identity
from tests import test_daily_release as fixtures


class PaperIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DailyReleaseTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.index = self.root / 'index.csv'; self.output = self.root / 'metadata'

    def write_index(self, **changes):
        row = {f: '' for f in pair_index.FIELDS}
        row.update(doc_id='LK-EDU-000001', source_url='https://school.test/uploads/2026/2011_AL_Chemistry_Paper_I_Sinhala_medium.pdf',
                   role='paper', metadata_status='unverified', **changes)
        with self.index.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=pair_index.FIELDS); writer.writeheader(); writer.writerow(row)

    def result(self):
        with (self.output / 'documents.csv').open() as stream: row = next(csv.DictReader(stream))
        evidence = json.loads((self.output / 'metadata_evidence.jsonl').read_text())
        return row, evidence

    def test_filename_ignores_upload_directory_and_records_evidence(self):
        self.write_index()
        before = self.index.read_bytes()
        paper_identity.enrich(self.index, self.output)
        row, report = self.result()
        self.assertEqual((row['year'], row['subject'], row['exam'], row['paper_number'], row['language']),
                         ('2011', 'Chemistry', 'AL', '1', 'si'))
        self.assertEqual(row['variant'], '')
        self.assertEqual(report['fields']['year']['evidence'][0]['origin'], 'filename')
        self.assertEqual(self.index.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'already exists'): paper_identity.enrich(self.index, self.output)

    def test_conflicting_year_and_subject_remain_blank(self):
        self.write_index(title='2012 AL Physics Paper II Tamil medium')
        paper_identity.enrich(self.index, self.output)
        row, report = self.result()
        for field in ('year', 'subject', 'paper_number', 'language'):
            self.assertEqual(row[field], '')
            self.assertEqual(report['fields'][field]['status'], 'conflict')

    def test_publication_year_not_used_as_exam_year(self):
        values = paper_identity.hints('Published 2026', {'domains': {}})
        self.assertEqual(values['year'], set())
        self.assertEqual(paper_identity.hints('2011 2012', {'domains': {}})['year'], {'2011', '2012'})

    def test_model_official_conflict_is_not_hidden(self):
        self.write_index(title='Official model paper')
        paper_identity.enrich(self.index, self.output)
        row, report = self.result()
        self.assertEqual(row['variant'], '')
        self.assertEqual(report['fields']['variant']['status'], 'conflict')

    def test_compilation_does_not_receive_one_exam_year(self):
        self.write_index(collection_id='edition-1')
        paper_identity.enrich(self.index, self.output)
        row, _ = self.result(); self.assertEqual(row['year'], '')

    def make_header(self, **changes):
        f = self.fixture.fixture
        f.add_page(1, 'AL Chemistry\nPaper I\n2011\nSinhala medium', **changes)
        folder = f.processed / 'LK-EDU-000001_1'
        page = json.loads((folder / 'page.json').read_text())
        self.write_index()
        with self.index.open() as stream: row = next(csv.DictReader(stream))
        row['source_url'] = page['source_url']
        with self.index.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=pair_index.FIELDS); writer.writeheader(); writer.writerow(row)
        return folder

    def test_header_has_page_line_and_raw_hash_evidence(self):
        folder = self.make_header()
        paper_identity.enrich(self.index, self.output, page_bundles=[folder])
        row, report = self.result()
        self.assertEqual(row['year'], '2011'); self.assertEqual(len(row['raw_sha256']), 64)
        self.assertEqual(report['fields']['year']['evidence'][0]['line'], 3)
        self.assertEqual(row['metadata_status'], 'unverified')
        self.assertEqual(row['reviewer'], '')

    def test_corrupt_header_is_rejected(self):
        folder = self.make_header(); (folder / 'text.txt').write_text('altered')
        with self.assertRaisesRegex(ValueError, 'Corrupt'): paper_identity.enrich(self.index, self.output, page_bundles=[folder])
        self.assertFalse(self.output.exists())

    def test_incomplete_ocr_rejected(self):
        folder = self.make_header(outcome='truncated', completion='repetition_loop')
        with self.assertRaisesRegex(ValueError, 'Incomplete'): paper_identity.enrich(self.index, self.output, page_bundles=[folder])

    def test_cli(self):
        self.write_index()
        result = subprocess.run([sys.executable, '-B', '-m', 'pipeline.workflow', 'enrich-pair-index',
                                 '--index', str(self.index), '--output', str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['documents'], 1)
