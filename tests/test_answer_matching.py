"""Paper/key fixtures are invented; no benchmark examples or external requests."""
import copy
import json
import unittest

import yaml

from pipeline.dataset import answers, daily, tasks, reviewed
from pipeline.dataset.native import digest, encode
from tests import test_daily_release as fixtures


PAPER = ('1. Which label appears on the imaginary crate?\n(A) Copper\n(B) Indigo\n'
         '2. Which number is printed on its invented label?\n(A) 8\n(B) 11')
KEY = '1 - B\n2 - A'


class AnswerMatchingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DailyReleaseTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.packet, self.output, self.release = self.root / 'packet', self.root / 'matched', self.root / 'daily'
        self.config_path = self.root / 'pairs.yaml'

    def setup_pair(self, paper=PAPER, key=KEY, external=False, key_outcome='predicted', key_completion='complete'):
        f = self.fixture.fixture
        f.add_page(1, paper)
        if not external: f.add_page(1, key, doc='LK-EDU-000002')
        daily.build(self.release, provisional_roots=[self.fixture.snapshot('input')],
                    policy={'min_characters': 1, 'min_sinhala_letter_ratio': 0, 'validation_percent': 0})
        tasks.prepare(self.release, self.packet)
        if external:
            f.add_page(1, key, doc='LK-EDU-000002', outcome=key_outcome, completion=key_completion)
        identity = {'exam': 'Invented exam', 'subject': 'Physics', 'year': 2020,
                    'paper_number': 'I', 'language': 'en', 'variant': 'fixture'}
        paper_doc = {**identity, 'doc_id': 'LK-EDU-000001', 'raw_sha256': digest(b'LK-EDU-000001')}
        key_doc = {**identity, 'doc_id': 'LK-EDU-000002', 'raw_sha256': digest(b'LK-EDU-000002')}
        self.paper_id = f"{paper_doc['doc_id']}_{paper_doc['raw_sha256']}_p000001"
        self.key_id = f"{key_doc['doc_id']}_{key_doc['raw_sha256']}_p000001"
        self.pair = {'pair_id': 'fixture-paper', 'paper': paper_doc, 'marking_scheme': key_doc,
            'choice_labels': ['A', 'B'], 'pairing_verified': True, 'pairing_reviewer': 'Fixture checker',
            'questions': [{'record_id': self.paper_id, 'lines': [1, len(paper.splitlines())], 'section': 'I'}],
            'answers': [{'record_id': self.key_id, 'lines': [1, len(key.splitlines())], 'section': 'I'}]}
        self.save()
        return f.processed / 'LK-EDU-000002_1'

    def save(self):
        self.config_path.write_text(yaml.safe_dump({'schema_version': 'paper-answer-pairs-1', 'pairs': [self.pair]}))

    def run_match(self, **kw):
        return answers.match(self.packet, self.config_path, self.output, **kw)

    def segments(self):
        return next(r['segments'] for r in daily.jsonl(self.output / 'annotations.jsonl') if r['record_id'] == self.paper_id)

    def test_proposals_link_answers_without_approving_training(self):
        self.setup_pair()
        report = self.run_match()
        self.assertEqual(report['counts']['proposed_match'], 2)
        segments = self.segments()
        self.assertEqual([s['answer'] for s in segments], [2, 1])
        self.assertTrue(all(s['answer_verified'] is False for s in segments))
        self.assertEqual(segments[0]['answer_evidence']['record_id'], self.key_id)
        export = tasks.build(self.output, self.root / 'export')
        self.assertEqual(export['counts']['mcq/train.jsonl'], 0)
        self.assertEqual(export['counts']['mcq_candidates.jsonl'], 2)
        self.assertTrue((self.root / 'export/evidence/matching_report.json').is_file())
        tasks.verify(self.root / 'export')

    def test_source_checks_enable_export_and_keep_original_number(self):
        self.setup_pair(); self.run_match()
        annotations = daily.jsonl(self.output / 'annotations.jsonl')
        for row in annotations:
            for s in row['segments']:
                if s['kind'] == 'mcq': s.update(question_choices_verified=True, answer_verified=True, reviewer='Source checker')
        (self.output / 'annotations.jsonl').write_bytes(b''.join(encode(a) for a in annotations))
        tasks.build(self.output, self.root / 'export')
        rows = daily.jsonl(self.root / 'export/mcq/train.jsonl')
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['provenance']['source_question_number'] for r in rows}, {1, 2})
        self.assertTrue(all(r['provenance']['paper_pair_id'] == 'fixture-paper' for r in rows))

    def test_wrong_year_language_variant_or_unknown_identity_rejected(self):
        self.setup_pair()
        original = copy.deepcopy(self.pair)
        for field, value in [('year', 2021), ('language', 'si'), ('variant', 'alternate'), ('subject', ''), ('paper_number', '')]:
            self.pair = copy.deepcopy(original); self.pair['marking_scheme'][field] = value; self.save()
            with self.subTest(field=field), self.assertRaises(ValueError): self.run_match()
        self.assertFalse(self.output.exists())

    def test_unverified_pair_never_proposes_answer(self):
        self.setup_pair(); self.pair['pairing_verified'] = False; self.save()
        self.assertEqual(self.run_match()['counts']['unresolved'], 2)
        self.assertTrue(all(s['answer'] is None for s in self.segments()))

    def test_missing_key_and_duplicate_keys_are_unresolved(self):
        self.setup_pair(key='1 - B\n1 - A')
        self.run_match()
        reasons = [s['matching_reasons'] for s in self.segments()]
        self.assertIn('duplicate_or_conflicting_key_entries', reasons[0])
        self.assertIn('missing_key_entry', reasons[1])
        self.assertTrue(all(s['answer'] is None for s in self.segments()))

    def test_numbering_restarts_are_matched_by_explicit_section(self):
        self.setup_pair(paper=PAPER.replace('2. Which', '1. Which'), key='1 - B\n1 - A')
        self.pair['questions'] = [{'record_id': self.paper_id, 'lines': [1, 3], 'section': 'I'},
                                  {'record_id': self.paper_id, 'lines': [4, 6], 'section': 'II'}]
        self.pair['answers'] = [{'record_id': self.key_id, 'lines': [1, 1], 'section': 'I'},
                                {'record_id': self.key_id, 'lines': [2, 2], 'section': 'II'}]
        self.save(); self.run_match()
        self.assertEqual([s['answer'] for s in self.segments()], [2, 1])
        self.assertEqual([s['source_section'] for s in self.segments()], ['I', 'II'])

    def test_duplicate_question_numbers_in_same_section_are_unresolved(self):
        self.setup_pair(paper=PAPER.replace('2. Which', '1. Which'))
        self.run_match()
        self.assertTrue(all('duplicate_question_number_in_section' in s['matching_reasons'] for s in self.segments()))

    def test_unsupported_key_table_blocks_section_and_reports_line(self):
        self.setup_pair(key='1 - B\n2 - A\n3 - A 4 - B')
        result = self.run_match()
        self.assertEqual(result['counts']['unresolved'], 2)
        issues = json.loads((self.output / 'matching_report.json').read_text())['issues']
        self.assertEqual(issues[0]['reason'], 'unsupported_answer_key_line')
        self.assertEqual(issues[0]['source']['lines'], [3, 3])

    def test_incomplete_choices_and_existing_annotations_are_not_overwritten(self):
        self.setup_pair(paper=PAPER.replace('(B) Indigo', 'Indigo'))
        a = daily.jsonl(self.packet / 'annotations.jsonl')
        for row in a:
            if row['record_id'] == self.paper_id: row['segments'] = [{'kind': 'theory', 'lines': [4, 6]}]
        before = b''.join(encode(r) for r in a)
        (self.packet / 'annotations.jsonl').write_bytes(before)
        result = self.run_match()
        self.assertEqual(result['counts']['unresolved'], 2)
        self.assertEqual(self.segments(), [{'kind': 'theory', 'lines': [4, 6]}])
        self.assertEqual((self.packet / 'annotations.jsonl').read_bytes(), before)

    def test_numeric_key_import_keeps_evidence_out_of_training(self):
        bundle = self.setup_pair(external=True)
        self.run_match(key_bundles=[bundle], release=self.release)
        _, sources = tasks._load(self.output)
        self.assertTrue(sources[self.key_id]['evidence_only'])
        self.assertEqual(self.segments()[0]['answer'], 2)
        rows = daily.jsonl(self.output / 'annotations.jsonl')
        for row in rows:
            if row['record_id'] == self.key_id: row['segments'] = [{'kind': 'theory', 'lines': [1, 2]}]
        (self.output / 'annotations.jsonl').write_bytes(b''.join(encode(r) for r in rows))
        with self.assertRaisesRegex(ValueError, 'evidence-only'): tasks.build(self.output, self.root / 'export')

    def test_incomplete_key_ocr_is_not_used_for_proposals(self):
        bundle = self.setup_pair(external=True, key_outcome='truncated', key_completion='repetition_loop')
        self.run_match(key_bundles=[bundle], release=self.release)
        self.assertTrue(all(s['answer'] is None for s in self.segments()))

    def test_external_keys_require_release_and_corruption_fails(self):
        bundle = self.setup_pair(external=True)
        with self.assertRaisesRegex(ValueError, '--release'): self.run_match(key_bundles=[bundle])
        (bundle / 'text.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Corrupt'): self.run_match(key_bundles=[bundle], release=self.release)

    def test_numeric_labels_map_to_choice_positions(self):
        self.setup_pair(paper=PAPER.replace('(A)', '(1)').replace('(B)', '(2)'), key='01 - (2)\n02: 1')
        self.pair['choice_labels'] = ['1', '2']; self.save()
        self.run_match()
        self.assertEqual([s['answer'] for s in self.segments()], [2, 1])

    def test_overlapping_configuration_rejected_and_output_not_replaced(self):
        self.setup_pair()
        self.pair['questions'].append(copy.deepcopy(self.pair['questions'][0])); self.save()
        with self.assertRaisesRegex(ValueError, 'overlap'): self.run_match()
        self.pair['questions'].pop(); self.save(); self.run_match()
        with self.assertRaisesRegex(ValueError, 'exists'): self.run_match()

    def test_pair_documents_in_different_splits_are_rejected(self):
        self.setup_pair()
        f = self.fixture.fixture
        for record in f.prepare():
            f.approve(record, split='train' if record['record_id'].startswith('LK-EDU-000001_') else 'validation')
        reviewed.export(f.packet, self.root / 'reviewed')
        daily.build(self.root / 'split_daily', reviewed_roots=[self.root / 'reviewed'],
                    policy={'min_characters': 1, 'min_sinhala_letter_ratio': 0})
        tasks.prepare(self.root / 'split_daily', self.root / 'split_packet')
        self.packet = self.root / 'split_packet'
        with self.assertRaisesRegex(ValueError, 'cross inherited splits'): self.run_match()

    def test_import_cannot_move_a_known_validation_document_to_train(self):
        self.setup_pair()
        f = self.fixture.fixture
        for record in f.prepare():
            f.approve(record, split='train' if record['record_id'].startswith('LK-EDU-000001_') else 'validation')
        reviewed.export(f.packet, self.root / 'reviewed')
        daily.build(self.root / 'split_daily', reviewed_roots=[self.root / 'reviewed'],
                    policy={'min_characters': 1, 'min_sinhala_letter_ratio': 0})
        tasks.prepare(self.root / 'split_daily', self.root / 'split_packet')
        self.packet, self.release = self.root / 'split_packet', self.root / 'split_daily'
        f.add_page(2, KEY, doc='LK-EDU-000002')
        self.pair['answers'][0]['record_id'] = self.key_id.replace('p000001', 'p000002'); self.save()
        with self.assertRaisesRegex(ValueError, 'crosses an inherited source split'):
            self.run_match(key_bundles=[f.processed / 'LK-EDU-000002_2'], release=self.release)

    def test_malformed_parentheses_are_not_silently_repaired(self):
        self.setup_pair(key='1 - (B\n2 - A')
        self.run_match()
        self.assertTrue(all(s['answer'] is None for s in self.segments()))

    def test_cli_matching(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from pipeline import workflow
        self.setup_pair()
        with patch('sys.argv', ['workflow', 'match-paper-answers', '--packet', str(self.packet),
                              '--pairs', str(self.config_path), '--output', str(self.output)]), redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(), 0)


    def setup_combined(self, inline=False):
        text = '1. Which fictional label?\n(A) Copper\n(B) Indigo\nAnswer: B' if inline else PAPER + '\n' + KEY
        self.setup_pair(paper=text)
        self.pair['mode'] = 'combined'
        self.pair['marking_scheme'] = copy.deepcopy(self.pair['paper'])
        end = 3 if inline else 6
        self.pair['questions'][0]['lines'] = [1, end]
        self.pair['answers'] = [{'record_id': self.paper_id, 'lines': [end + 1, len(text.splitlines())], 'section': 'I'}]
        if inline: self.pair['answers'][0]['question_number'] = 1
        self.save()

    def test_combined_numbered_key_keeps_answer_evidence_on_same_page(self):
        self.setup_combined()
        self.assertEqual(self.run_match()['counts']['proposed_match'], 2)
        segments = [s for s in self.segments() if s['kind'] == 'mcq']
        self.assertEqual([s['answer'] for s in segments], [2, 1])
        self.assertTrue(all(s['answer_evidence']['record_id'] == self.paper_id for s in segments))
        result = tasks.build(self.output, self.root / 'export')
        self.assertEqual(result['counts']['mcq/train.jsonl'], 0)
        tasks.verify(self.root / 'export')

    def test_combined_inline_answer_excluded_from_choices(self):
        self.setup_combined(inline=True)
        self.assertEqual(self.run_match()['counts']['proposed_match'], 1)
        segment = next(s for s in self.segments() if s['kind'] == 'mcq')
        self.assertEqual(segment['answer'], 2)
        self.assertEqual(segment['choice_lines'], [[2, 2], [3, 3]])
        self.assertEqual(segment['answer_evidence']['lines'], [4, 4])
        self.assertFalse(segment['answer_verified'])

    def test_combined_identity_cannot_reference_different_pdf(self):
        self.setup_pair(); self.pair['mode'] = 'combined'; self.save()
        with self.assertRaisesRegex(ValueError, 'Combined mode'): self.run_match()

    def test_combined_overlap_is_rejected(self):
        self.setup_combined(inline=True)
        self.pair['questions'][0]['lines'] = [1, 4]; self.save()
        with self.assertRaisesRegex(ValueError, 'overlap'): self.run_match()

    def test_inline_answer_binding_must_be_positive_integer(self):
        self.setup_combined(inline=True)
        for value in (True, 0, '1'):
            self.pair['answers'][0]['question_number'] = value; self.save()
            with self.subTest(value=value), self.assertRaises(ValueError): self.run_match()

    def test_missing_inline_question_is_reported_not_assigned(self):
        self.setup_combined(inline=True)
        self.pair['answers'][0]['question_number'] = 2; self.save()
        self.assertEqual(self.run_match()['counts']['unresolved'], 1)
        segment = next(s for s in self.segments() if s['kind'] == 'mcq')
        self.assertIsNone(segment['answer'])
        self.assertIn('missing_key_entry', segment['matching_reasons'])

    def test_question_region_with_answer_line_is_not_exportable(self):
        row = {'record_id': 'fixture', 'text_sha256': 'a' * 64}
        parsed = answers.questions(row, list(enumerate(('1. Fictional question?', '(A) One', '(B) Two', 'Answer: B'), 1)), ['A', 'B'])
        self.assertIn('answer_line_inside_question_region', parsed[0]['reasons'])
        self.assertNotIn('segment', parsed[0])

    def test_unverified_pair_produces_separate_provisional_evidence(self):
        self.setup_pair(); self.pair['pairing_verified'] = False; self.save()
        self.assertEqual(self.run_match()['counts']['provisional_matches'], 2)
        report = json.loads((self.output / 'matching_report.json').read_text())
        self.assertEqual([r['candidate_answer'] for r in report['provisional_matches']], [2, 1])
        self.assertTrue(all(not r['training_approved'] and not r['pairing_verified'] for r in report['provisional_matches']))
        self.assertTrue(all(s['answer'] is None for s in self.segments()))
        exported = tasks.build(self.output, self.root / 'export')
        self.assertEqual(exported['counts']['mcq/train.jsonl'], 0)
        tasks.verify(self.root / 'export')

    def test_ambiguous_keys_do_not_create_provisional_answers(self):
        self.setup_pair(key='1 - A\n1 - B'); self.pair['pairing_verified'] = False; self.save()
        self.assertEqual(self.run_match()['counts']['provisional_matches'], 0)

    def test_verified_pair_uses_existing_route_only(self):
        self.setup_pair()
        self.assertEqual(self.run_match()['counts']['provisional_matches'], 0)


if __name__ == '__main__':
    unittest.main()
