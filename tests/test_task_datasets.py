"""Invented source fixtures only; no benchmark questions are used here."""
import json
import unittest

from pipeline.dataset import daily, tasks
from pipeline.dataset.native import encode
from tests import test_daily_release as fixtures


# Deliberately artificial material, unrelated to benchmark samples.
SOURCE = 'A made-up lesson about boxes.\nA box holds seven tokens.\nHow many tokens are in this box?\nSeven tokens\nNine tokens\nAnswer key: choice 1.'


class TaskDatasetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DailyReleaseTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.fixture.add_page(1, SOURCE)
        self.release, self.packet, self.output = self.root / 'daily', self.root / 'tasks', self.root / 'export'
        daily.build(self.release, provisional_roots=[self.fixture.snapshot('input')],
                    policy={'validation_percent': 0, 'min_sinhala_letter_ratio': 0, 'min_characters': 1})
        tasks.prepare(self.release, self.packet)
        self.row = daily.jsonl(self.packet / 'annotations.jsonl')[0]

    def save(self):
        (self.packet / 'annotations.jsonl').write_bytes(encode(self.row))

    def mcq(self):
        return {'kind': 'mcq', 'lines': [3, 5], 'question_lines': [3, 3],
                'choice_lines': [[4, 4], [5, 5]], 'answer': 1,
                'question_choices_verified': True, 'answer_verified': True, 'reviewer': 'Fixture reviewer',
                'answer_evidence': {'record_id': self.row['record_id'], 'text_sha256': self.row['text_sha256'],
                                    'lines': [6, 6]}}

    def test_prepare_never_assumes_theory_or_generates_mcqs(self):
        self.assertEqual(self.row['segments'], [])
        result = tasks.build(self.packet, self.output)
        self.assertEqual(result['counts']['theory/train.jsonl'], 0)
        self.assertEqual(result['counts']['mcq/train.jsonl'], 0)
        self.assertEqual(result['counts']['unresolved.jsonl'], 1)

    def test_mixed_page_export_is_separate_grounded_and_preserves_status(self):
        self.row['segments'] = [{'kind': 'theory', 'lines': [1, 2]}, self.mcq(),
                                {'kind': 'exclude', 'lines': [6, 6], 'reason': 'answer key'}]
        self.save()
        tasks.build(self.packet, self.output)
        theory = daily.jsonl(self.output / 'theory/train.jsonl')[0]
        mcq = daily.jsonl(self.output / 'mcq/train.jsonl')[0]
        self.assertEqual(theory['text'], '\n'.join(SOURCE.splitlines()[:2]))
        self.assertFalse(theory['training_approved'])
        self.assertTrue(theory['review_required'])
        self.assertEqual(mcq['choices'][mcq['answer'] - 1], 'Seven tokens')
        self.assertEqual(mcq['q_no'], 1)
        self.assertIsNone(mcq['metadata']['difficulty'])
        self.assertTrue(mcq['training_approved'])
        self.assertEqual(mcq['provenance']['answer_evidence']['text'], SOURCE.splitlines()[5])
        self.assertEqual(tasks.verify(self.output)['counts']['unresolved.jsonl'], 0)

    def test_missing_answers_and_unverified_answers_remain_candidates(self):
        for change in ({'answer': None}, {'answer_verified': False}, {'question_choices_verified': False},
                       {'answer_evidence': None}, {'reviewer': ''}):
            with self.subTest(change=change):
                self.row['segments'] = [{**self.mcq(), **change}]
                self.save()
                _, rows = tasks._render(self.packet)
                self.assertEqual(rows['mcq/train.jsonl'], [])
                candidate = rows['mcq_candidates.jsonl'][0]
                self.assertIsNone(candidate['answer'])
                self.assertFalse(candidate['training_approved'])

    def test_invalid_answers_and_overlapping_ranges_are_rejected(self):
        for answer in (0, 3, True, '1'):
            self.row['segments'] = [{**self.mcq(), 'answer': answer}]; self.save()
            with self.assertRaisesRegex(ValueError, 'one-based'):
                tasks.build(self.packet, self.output)
        self.row['segments'] = [{'kind': 'theory', 'lines': [1, 4]}, self.mcq()]; self.save()
        with self.assertRaisesRegex(ValueError, 'overlap'): tasks.build(self.packet, self.output)
        self.row['segments'] = [{**self.mcq(), 'question_lines': [1, 3]}]; self.save()
        with self.assertRaisesRegex(ValueError, 'inside'): tasks.build(self.packet, self.output)

    def test_stale_evidence_and_corrupt_artifacts_fail(self):
        self.row['segments'] = [self.mcq()]
        self.row['segments'][0]['answer_evidence']['text_sha256'] = '0' * 64; self.save()
        with self.assertRaisesRegex(ValueError, 'stale answer'): tasks.build(self.packet, self.output)
        self.row['segments'] = [self.mcq()]; self.save()
        tasks.build(self.packet, self.output)
        (self.output / 'mcq/train.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): tasks.verify(self.output)

    def test_packet_is_bound_to_text_and_publication_cannot_overwrite(self):
        self.row['text_sha256'] = '0' * 64; self.save()
        with self.assertRaisesRegex(ValueError, 'stale'): tasks.build(self.packet, self.output)
        with self.assertRaisesRegex(ValueError, 'outside'): tasks.prepare(self.release, self.release / 'tasks')
        with self.assertRaisesRegex(ValueError, 'exists'): tasks.prepare(self.release, self.packet)

    def test_duplicate_mcqs_with_reordered_choices_are_removed(self):
        source = daily.jsonl(self.packet / 'sources.jsonl')[0]
        # Duplicate source segments within one page, with reordered option lines.
        source['text'] += '\n' + '\n'.join(SOURCE.splitlines()[2:5])
        from pipeline.dataset.native import digest
        source['text_sha256'] = digest(source['text'].encode())
        (self.packet / 'sources.jsonl').write_bytes(encode(source))
        manifest = json.loads((self.packet / 'manifest.json').read_text())
        manifest['output_sha256']['sources.jsonl'] = digest((self.packet / 'sources.jsonl').read_bytes())
        (self.packet / 'manifest.json').write_bytes(encode(manifest))
        self.row['text_sha256'] = source['text_sha256']
        first = self.mcq()
        second = {**self.mcq(), 'lines': [7, 9], 'question_lines': [7, 7],
                  'choice_lines': [[9, 9], [8, 8]], 'answer': 2}
        self.row['segments'] = [first, second]; self.save()
        result = tasks.build(self.packet, self.output)
        self.assertEqual(result['counts']['mcq/train.jsonl'], 1)
        self.assertEqual(result['counts']['duplicates.jsonl'], 1)
        second['answer'] = 1; self.save()
        with self.assertRaisesRegex(ValueError, 'conflicting answer'): tasks._render(self.packet)

    def test_answer_evidence_cannot_cross_splits(self):
        from pipeline.dataset.native import digest
        original = daily.jsonl(self.packet / 'sources.jsonl')[0]
        evidence = {**original, 'record_id': 'fixture-other-page', 'split': 'validation'}
        content = encode(original) + encode(evidence)
        (self.packet / 'sources.jsonl').write_bytes(content)
        manifest = json.loads((self.packet / 'manifest.json').read_text())
        manifest['output_sha256']['sources.jsonl'] = digest(content)
        (self.packet / 'manifest.json').write_bytes(encode(manifest))
        mcq = self.mcq(); mcq['answer_evidence']['record_id'] = evidence['record_id']
        self.row['segments'] = [mcq]; self.save()
        with self.assertRaisesRegex(ValueError, 'crosses source splits'):
            tasks.build(self.packet, self.output)

    def test_cli_prepare_export_and_verify_without_models(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from pipeline import workflow
        other = self.root / 'cli_packet'
        for args in (['prepare-tasks', '--release', str(self.release), '--output', str(other)],
                     ['export-tasks', '--packet', str(other), '--output', str(self.output)],
                     ['verify-task-release', '--root', str(self.output)]):
            with patch('sys.argv', ['workflow', *args]), redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.main(), 0)


if __name__ == '__main__':
    unittest.main()
