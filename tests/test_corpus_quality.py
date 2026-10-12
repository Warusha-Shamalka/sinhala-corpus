import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.dataset import reviewed
from pipeline.dataset.native import digest, encode, publish
from pipeline.quality import corpus
from pipeline import workflow


class CorpusQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.processed, self.packet = self.root / 'processed', self.root / 'review'

    def add_page(self, number, text, doc='LK-EDU-000001', sha=None, method='ocr', outcome='predicted', completion='complete'):
        identity = {'doc_id': doc, 'raw_sha256': sha or digest(doc.encode()), 'page_number': number,
                    'processing_config_sha256': 'a' * 64}
        record = {'schema_version': 'corpus-page-1', 'identity': identity, 'training_approved': False,
                  'text': text, 'source_url': f'https://school.test/{doc}.pdf', 'source': 'Fixture school',
                  'metadata_hints': {'subject': 'Physics', 'domain': 'STEM', 'grade': '12', 'language': '', 'license': ''},
                  'method': method, 'ocr_backend': 'surya' if method == 'ocr' else None,
                  'quality_flags': ['incomplete_or_failed_prediction'] if completion != 'complete' else [],
                  'prediction': {'text': text, 'outcome': outcome, 'completion_status': completion}}
        files = {'page.json': encode(record), 'page.png': b'fixture source image', 'text.txt': text.encode()}
        publish(self.processed / f'{doc}_{number}', {**files, 'manifest.json': encode({
            'schema_version': 'corpus-page-bundle-1', 'identity': identity,
            'output_sha256': {name: digest(data) for name, data in files.items()}})})

    def prepare(self):
        reviewed.prepare(self.processed, self.packet)
        return [json.loads(line) for line in (self.packet / 'records.jsonl').read_text().splitlines()]

    def approve(self, record, text=None, split='train'):
        if text is not None: (self.packet / record['text_path']).write_text(text, encoding='utf-8')
        reviewed.seal(self.packet, record['record_id'], 'Alice', 'Bob', 'Fixture permission', 'Full source verified', split)

    def test_pending_report_has_no_accuracy_or_approval_and_does_not_write(self):
        self.add_page(1, 'සිංහල පෙළ', outcome='truncated', completion='region_incomplete')
        records = self.prepare()
        before = {str(path): path.read_bytes() for path in self.packet.rglob('*') if path.is_file()}
        result = corpus.report(self.packet)
        self.assertEqual(result['decisions'], {'pending': 1})
        self.assertEqual(result['valid_approvals'], 0)
        self.assertIsNone(result['correction_distances']['characters']['edit_rate'])
        self.assertEqual(result['ocr_outcomes'], {'truncated': 1})
        self.assertIn('no_valid_approvals', result['export_preflight']['blockers'])
        self.assertEqual(result['review_queue'], [records[0]['record_id']])
        self.assertFalse(result['page_coverage'][0]['complete_document_verified'])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.packet.rglob('*') if path.is_file()})
        self.assertEqual(result, corpus.report(self.packet))

    def test_approved_correction_distances_and_coverage(self):
        self.add_page(1, 'cat dog'); record = self.prepare()[0]
        self.approve(record, 'cat fog')
        result = corpus.report(self.packet)
        self.assertEqual(result['export_preflight']['status'], 'checks_passed')
        self.assertEqual(result['correction_distances']['characters']['edits'], 1)
        self.assertEqual(result['correction_distances']['words']['edits'], 1)
        self.assertEqual(result['correction_distances']['words']['edit_rate'], 0.5)
        self.assertEqual(result['approved_coverage_hints']['subject'], {'Physics': 1})
        self.assertEqual(result['coverage_hints']['language'], {'(unknown)': 1})
        self.assertTrue(result['records'][0]['edited'])
        self.assertIn('not independent OCR accuracy', result['accuracy_note'])

    def test_post_approval_edit_is_a_visible_blocker_and_export_stays_strict(self):
        self.add_page(1, 'original'); record = self.prepare()[0]
        self.approve(record)
        (self.packet / record['text_path']).write_text('changed', encoding='utf-8')
        result = corpus.report(self.packet)
        self.assertEqual(result['valid_approvals'], 0)
        self.assertIn('invalid_approvals', result['export_preflight']['blockers'])
        self.assertIn('changed since approval', result['invalid_approvals'][0]['error'])
        with self.assertRaisesRegex(ValueError, 'changed since approval'):
            reviewed.export(self.packet, self.root / 'release')

    def test_source_versions_cannot_cross_splits(self):
        self.add_page(1, 'one original'); self.add_page(2, 'two original')
        for index, record in enumerate(self.prepare()):
            self.approve(record, split='train' if index == 0 else 'validation')
        result = corpus.report(self.packet)
        self.assertIn('source_split_conflicts', result['export_preflight']['blockers'])
        self.assertEqual(len(result['export_preflight']['source_split_conflicts']), 3)

    def test_duplicate_groups_and_cross_split_duplicate_blocker(self):
        self.add_page(1, 'same text'); self.add_page(1, 'same   text', doc='LK-EDU-000002')
        records = self.prepare()
        for record in records: self.approve(record)
        result = corpus.report(self.packet)
        self.assertEqual(len(result['export_preflight']['duplicate_groups']), 1)
        self.assertEqual(result['export_preflight']['status'], 'checks_passed')
        self.approve(records[1], split='validation')
        self.assertIn('duplicate_split_conflict', corpus.report(self.packet)['export_preflight']['blockers'])

    def test_metrics_have_explicit_budgets_and_incomplete_denominators(self):
        self.add_page(1, 'cat dog'); record = self.prepare()[0]
        self.approve(record, 'cat fog')
        result = corpus.report(self.packet, max_metric_cells=10, total_metric_cells=10)
        self.assertEqual(result['correction_distances']['characters']['skipped_pages'], 1)
        self.assertIsNone(result['correction_distances']['characters']['edit_rate'])
        self.assertEqual(result['correction_distances']['words']['scored_pages'], 1)
        self.assertEqual(result['metric_limits']['used_cells'], 4)
        with self.assertRaisesRegex(ValueError, 'positive integers'):
            corpus.report(self.packet, total_metric_cells=0)

    def test_failed_empty_ocr_with_full_correction_is_counted_in_editing_burden(self):
        self.add_page(1, '', outcome='failed', completion='failed'); record = self.prepare()[0]
        self.approve(record, 'corrected')
        result = corpus.report(self.packet)
        self.assertEqual(result['ocr_outcomes'], {'failed': 1})
        self.assertEqual(result['correction_distances']['characters']['edit_rate'], 1)
        self.assertEqual(result['metric_limits']['used_cells'], 0)

    def test_large_dedup_preflight_is_deferred_explicitly(self):
        self.add_page(1, 'one'); self.add_page(2, 'two')
        for record in self.prepare(): self.approve(record)
        result = corpus.report(self.packet, max_dedup_pages=1)
        self.assertFalse(result['export_preflight']['deduplication_checked'])
        self.assertIn('deduplication_preflight_deferred', result['export_preflight']['blockers'])

    def test_report_publication_is_immutable_and_outside_packet(self):
        self.add_page(1, 'text'); self.prepare()
        output = self.root / 'quality'
        result = corpus.write(self.packet, output)
        self.assertEqual(json.loads((output / 'report.json').read_text()), result)
        self.assertIn('pending source review', (output / 'report.md').read_text())
        with self.assertRaises(Exception): corpus.write(self.packet, output)
        with self.assertRaisesRegex(ValueError, 'outside'):
            corpus.write(self.packet, self.packet / 'quality')

    def test_source_corruption_and_concurrent_draft_change_are_rejected(self):
        self.add_page(1, 'text'); record = self.prepare()[0]
        draft = self.packet / record['text_path']
        def changing_flags(text):
            draft.write_text('another text', encoding='utf-8')
            return []
        with patch.object(corpus, 'flags', side_effect=changing_flags), self.assertRaisesRegex(ValueError, 'changed during'):
            corpus.report(self.packet)
        (self.packet / record['image_path']).write_bytes(b'corrupt image')
        with self.assertRaisesRegex(ValueError, 'source artifact changed'):
            corpus.report(self.packet)

    def test_workflow_cli_reports_pending_and_optional_gate_requires_exportability(self):
        self.add_page(1, 'text'); record = self.prepare()[0]
        args = ['workflow', 'quality', '--packet', str(self.packet)]
        with patch('sys.argv', args), redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(workflow.main(), 0)
        self.assertEqual(json.loads(stream.getvalue())['valid_approvals'], 0)
        with patch('sys.argv', args + ['--require-exportable']), redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(), 1)
        self.approve(record)
        with patch('sys.argv', args + ['--require-exportable']), redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(), 0)
