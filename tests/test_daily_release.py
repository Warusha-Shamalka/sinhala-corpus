import json
from pathlib import Path
import unittest

from pipeline.dataset import daily, provisional, reviewed
from pipeline.dataset.native import digest, encode
from tests import test_corpus_quality as fixtures


def text(prefix='පාඩම'):
    return ' '.join(f'{prefix}{number}' for number in range(40))


class DailyReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CorpusQualityTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.first, self.second = self.root / 'day1', self.root / 'day2'
        self.policy = {'validation_percent': 0}

    def snapshot(self, name):
        report = self.root / f'{name}.json'
        report.write_text(json.dumps({'schema_version': 'corpus-batch-run-1', 'active_phase': 'finished',
                                     'processed_bundles': [str(path) for path in self.fixture.processed.iterdir()]}))
        root = self.root / name
        provisional.export(report, root)
        return root

    def alter_page(self, number, **changes):
        folder = self.fixture.processed / f'LK-EDU-000001_{number}'
        record = json.loads((folder / 'page.json').read_text()); record.update(changes)
        (folder / 'page.json').write_bytes(encode(record))
        (folder / 'text.txt').write_text(record['text'])
        manifest = json.loads((folder / 'manifest.json').read_text())
        for name in ('page.json', 'text.txt'): manifest['output_sha256'][name] = digest((folder / name).read_bytes())
        (folder / 'manifest.json').write_bytes(encode(manifest))

    def test_daily_candidates_preserve_unreviewed_status_and_handoff(self):
        self.fixture.add_page(1, text()); source = self.snapshot('snapshot1')
        result = daily.build(self.first, provisional_roots=[source], policy=self.policy)
        self.assertEqual(result['counts']['train'], 1)
        record = daily.jsonl(self.first / 'train.jsonl')[0]
        self.assertTrue(record['experimental_training_eligible'])
        self.assertFalse(record['training_approved']); self.assertTrue(record['review_required'])
        handoff = json.loads((self.first / 'handoff.json').read_text())
        self.assertEqual(handoff['release_id'], result['release_id'])
        self.assertEqual(handoff['task'], 'text_domain_adaptation')
        self.assertEqual(daily.verify(self.first)['release_id'], result['release_id'])

    def test_repeat_release_has_zero_delta_and_new_page_has_only_new_delta(self):
        self.fixture.add_page(1, text()); source = self.snapshot('snapshot1')
        daily.build(self.first, provisional_roots=[source], policy=self.policy)
        result = daily.build(self.second, provisional_roots=[source], previous=self.first, policy=self.policy)
        self.assertEqual(result['counts']['added_train'], 0)
        self.fixture.add_page(2, text('විද්‍යාව'))
        updated = self.snapshot('snapshot2')
        result = daily.build(self.root / 'day3', provisional_roots=[updated], previous=self.second, policy=self.policy)
        self.assertEqual(result['counts']['train'], 2)
        self.assertEqual(result['counts']['added_train'], 1)
        self.assertEqual(len(daily.jsonl(self.root / 'day3' / 'candidates.jsonl')), 2)

    def test_bad_ocr_and_short_pages_are_quarantined(self):
        self.fixture.add_page(1, text())
        self.fixture.add_page(2, text('වෙනත්'), outcome='completion_unverified', completion='unverified_upstream')
        self.fixture.add_page(3, 'කෙටි පෙළ')
        result = daily.build(self.first, provisional_roots=[self.snapshot('snapshot1')], policy=self.policy)
        self.assertEqual(result['counts'], {'train': 1, 'validation': 0, 'added_train': 1, 'quarantined': 2})
        excluded = daily.jsonl(self.first / 'excluded.jsonl')
        self.assertTrue(any('incomplete_or_unverified_ocr' in row['reasons'] for row in excluded))

    def test_document_pages_and_duplicate_sources_share_stable_split(self):
        self.fixture.add_page(1, text()); self.fixture.add_page(2, text('විද්‍යාව'))
        self.fixture.add_page(1, text(), doc='LK-EDU-000002')
        result = daily.build(self.first, provisional_roots=[self.snapshot('snapshot1')])
        ledger = daily.jsonl(self.first / 'candidates.jsonl')
        self.assertEqual(len({record['split'] for record in ledger}), 1)
        self.assertEqual(result['counts']['train'] + result['counts']['validation'], 2)
        self.assertEqual(len(daily.jsonl(self.first / 'duplicates.jsonl')), 1)
        daily.build(self.second, previous=self.first)
        self.assertEqual([record['split'] for record in ledger], [record['split'] for record in daily.jsonl(self.second / 'candidates.jsonl')])

    def test_new_duplicate_of_previous_training_text_does_not_replay(self):
        self.fixture.add_page(1, text()); daily.build(self.first, provisional_roots=[self.snapshot('snapshot1')], policy=self.policy)
        self.fixture.add_page(1, text(), doc='LK-EDU-000002')
        result = daily.build(self.second, previous=self.first, provisional_roots=[self.snapshot('snapshot2')], policy=self.policy)
        self.assertEqual(result['counts']['train'], 1)
        self.assertEqual(result['counts']['added_train'], 0)
        self.assertEqual(len(daily.jsonl(self.second / 'candidates.jsonl')), 2)

    def test_corrupted_snapshot_and_existing_release_are_rejected(self):
        self.fixture.add_page(1, text()); source = self.snapshot('snapshot1')
        daily.build(self.first, provisional_roots=[source], policy=self.policy)
        with self.assertRaises(Exception): daily.build(self.first, previous=self.first, policy=self.policy)
        (source / 'provisional_text.jsonl').write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): daily.build(self.second, provisional_roots=[source])

    def test_policy_changes_and_all_rejected_input_are_explicit_failures(self):
        self.fixture.add_page(1, text()); source = self.snapshot('snapshot1')
        daily.build(self.first, provisional_roots=[source], policy=self.policy)
        with self.assertRaisesRegex(ValueError, 'Policy changed'): daily.build(self.second, previous=self.first)
        with self.assertRaisesRegex(ValueError, 'All candidates quarantined'):
            daily.build(self.second, provisional_roots=[source], policy={**self.policy, 'min_characters': 10000})

    def test_verified_source_is_distinguished_and_reserved_test_is_not_training(self):
        self.fixture.add_page(1, text()); self.fixture.add_page(2, text('විද්‍යාව'), doc='LK-EDU-000002')
        records = self.fixture.prepare()
        for i, record in enumerate(records): self.fixture.approve(record, split='train' if i == 0 else 'test')
        reviewed.export(self.fixture.packet, self.root / 'verified')
        result = daily.build(self.first, reviewed_roots=[self.root / 'verified'], policy=self.policy)
        self.assertEqual(result['counts']['train'], 1)
        self.assertEqual(daily.jsonl(self.first / 'train.jsonl')[0]['source_review_status'], 'human_verified')
        self.assertEqual(json.loads((self.first / 'changes.json').read_text())['reserved_test_pages'], 1)

    def test_changed_provisional_text_needs_explicit_replacement_and_records_delta(self):
        self.fixture.add_page(1, text()); source = self.snapshot('snapshot1')
        daily.build(self.first, provisional_roots=[source], policy=self.policy)
        self.alter_page(1, text=text('සංශෝධනය'))
        updated = self.snapshot('snapshot2')
        with self.assertRaisesRegex(ValueError, 'replace-existing'):
            daily.build(self.second, previous=self.first, provisional_roots=[updated], policy=self.policy)
        result = daily.build(self.second, previous=self.first, provisional_roots=[updated], policy=self.policy, replace_existing=True)
        self.assertEqual(result['counts']['added_train'], 1)
        self.assertEqual(len(json.loads((self.second / 'changes.json').read_text())['replacements']), 1)

    def test_verified_correction_can_replace_provisional_without_downgrading_later(self):
        self.fixture.add_page(1, text()); source = self.snapshot('snapshot1')
        daily.build(self.first, provisional_roots=[source], policy=self.policy)
        record = self.fixture.prepare()[0]
        self.fixture.approve(record, text('නිවැරදි'))
        reviewed.export(self.fixture.packet, self.root / 'verified')
        daily.build(self.second, previous=self.first, reviewed_roots=[self.root / 'verified'], policy=self.policy)
        result = daily.build(self.root / 'day3', previous=self.second, provisional_roots=[source], policy=self.policy)
        self.assertEqual(result['review_status'], {'human_verified': 1})
        self.assertEqual(result['counts']['added_train'], 0)

    def test_known_scanner_footer_is_removed_without_rewriting_lesson(self):
        original = text() + '\nScanned with CamScanner'
        self.fixture.add_page(1, original)
        daily.build(self.first, provisional_roots=[self.snapshot('snapshot1')], policy=self.policy)
        record = daily.jsonl(self.first / 'train.jsonl')[0]
        self.assertEqual(record['text'], text())
        self.assertEqual(record['normalization']['scanner_footer_lines_removed'], 1)

    def test_duplicate_bridge_cannot_move_inherited_train_validation_families(self):
        self.fixture.add_page(1, text()); self.fixture.add_page(2, text('වෙනත්'), doc='LK-EDU-000002')
        for i, record in enumerate(self.fixture.prepare()): self.fixture.approve(record, split='train' if i == 0 else 'validation')
        reviewed.export(self.fixture.packet, self.root / 'verified')
        daily.build(self.first, reviewed_roots=[self.root / 'verified'], policy=self.policy)
        self.fixture.add_page(3, text())
        self.alter_page(3, source_url='https://school.test/LK-EDU-000002.pdf')
        with self.assertRaisesRegex(ValueError, 'bridge inherited splits'):
            daily.build(self.second, previous=self.first, provisional_roots=[self.snapshot('snapshot1')], policy=self.policy)
