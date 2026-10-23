import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from pipeline import collection
from pipeline.discovery import crawler
from pipeline.discovery.parser import Link, evaluate_link
from pipeline.download import downloader
from pipeline.quality import mcq
import test_download as transport


SUBJECTS = yaml.safe_load(crawler.SUBJECTS_PATH.read_text())
POLICY = yaml.safe_load((crawler.ROOT / 'configs/collection.yaml').read_text())
SOURCES = [{**transport.SOURCE, 'id': key, 'name': key, 'base_url': f'https://{key}.test/'} for key in ('a', 'b')]


def row(number, kind='past_paper', source='a', title=None, **extra):
    value = dict.fromkeys(crawler.CATALOG_COLUMNS, '')
    title = title or ('2026 A/L Physics Sinhala medium MCQ Past Paper' + (' Marking Scheme' if kind == 'marking_scheme' else ''))
    value.update(doc_id=f'LK-EDU-{number:06d}', title=title, document_type=kind,
                 source=source, source_url=f'https://{source}.test/files/{number}.pdf', status='DISCOVERED')
    value.update(extra)
    return value


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.policy = copy.deepcopy(POLICY)
        self.policy.update(source_ids=['a', 'b'], source_preference=['a', 'b'])

    def plan(self, rows): return collection.plan(rows, SOURCES, SUBJECTS, self.policy)

    def test_one_preferred_pair_across_mirrors_stable_across_input_order(self):
        rows = [row(1), row(2, 'marking_scheme'), row(3, source='b'), row(4, 'marking_scheme', 'b')]
        selected = self.plan(rows)
        self.assertEqual(set(selected['selected_doc_ids']), {'LK-EDU-000001', 'LK-EDU-000002'})
        self.assertEqual(selected['counts']['pairs'], 1)
        self.assertEqual(selected['exclusion_reasons']['duplicate_exam_mirror'], 2)
        self.assertEqual(selected['selected_doc_ids'], self.plan(list(reversed(rows)))['selected_doc_ids'])

    def test_existing_complete_pair_is_preferred_to_new_mirrors(self):
        rows = [row(1), row(2, 'marking_scheme'),
                row(3, source='b', status='DOWNLOADED', sha256='a'*64),
                row(4, 'marking_scheme', 'b', status='DOWNLOADED', sha256='b'*64)]
        self.assertEqual(set(self.plan(rows)['selected_doc_ids']), {'LK-EDU-000003', 'LK-EDU-000004'})

    def test_missing_counterpart_is_deferred(self):
        plan = self.plan([row(1)])
        self.assertEqual(plan['selected_doc_ids'], [])
        self.assertEqual(plan['deferred_reasons'], {'matching_mcq_counterpart_missing': 1})

    def test_all_study_categories_accept_only_sinhala(self):
        rows = [row(i + 1, kind, title=f'Grade 11 Physics {kind} Sinhala medium')
                for i, kind in enumerate(self.policy['study_types'])]
        rows += [row(10, 'textbook', title='Grade 11 Physics textbook English medium'),
                 row(11, 'lesson', title='Grade 11 Physics notes')]
        plan = self.plan(rows)
        self.assertEqual(len(plan['selected']), 4)
        self.assertEqual(plan['exclusion_reasons']['not_sinhala'], 1)
        self.assertEqual(plan['deferred_reasons']['medium_unknown'], 1)

    def test_essay_mixed_unknown_and_paper_i_alone_are_not_collected(self):
        rows = [row(1, title='2026 A/L Physics Sinhala medium Essay Past Paper'),
                row(2, title='2026 A/L Physics Sinhala medium Full Paper MCQ and Essay Past Paper'),
                row(3, title='2026 A/L Physics Sinhala medium Past Paper I')]
        plan = self.plan(rows)
        self.assertEqual(plan['selected_doc_ids'], [])
        self.assertIn('exam_essay', plan['exclusion_reasons'])
        self.assertIn('exam_mixed', plan['deferred_reasons'])
        self.assertIn('exam_unknown', plan['deferred_reasons'])

    def test_different_subjects_years_media_and_paper_parts_are_never_paired(self):
        for old, new in (('2026', '2025'), ('Physics', 'Biology'), ('Sinhala medium', 'Tamil medium')):
            with self.subTest(new=new):
                scheme = row(2, 'marking_scheme'); scheme['title'] = scheme['title'].replace(old, new)
                self.assertEqual(self.plan([row(1), scheme])['pairs'], [])
        self.assertEqual(self.plan([row(1, title='2026 A/L Physics Sinhala medium MCQ Past Paper I'),
                                   row(2, 'marking_scheme', title='2026 A/L Physics Sinhala medium MCQ Past Paper II Marking Scheme')])['pairs'], [])

    def test_term_tests_keep_distinct_province_and_term_identities(self):
        rows = []
        for index, province in enumerate(('Western', 'Northern')):
            title = f'2026 A/L Physics Grade 13 Sinhala medium First Term Test MCQ Past Paper {province} Province'
            rows.extend([row(index*2+1, title=title), row(index*2+2, 'marking_scheme', title=title+' Marking Scheme')])
        self.assertEqual(self.plan(rows)['counts']['pairs'], 2)

    def test_same_raw_file_is_not_a_paper_answer_pair(self):
        self.assertEqual(self.plan([row(1, sha256='a'*64), row(2, 'marking_scheme', sha256='a'*64)])['pairs'], [])
        studies = [row(1, 'textbook', title='Physics textbook Sinhala medium', sha256='a'*64),
                   row(2, 'textbook', 'b', title='Physics textbook Sinhala medium', sha256='a'*64)]
        self.assertEqual(len(self.plan(studies)['selected']), 1)

    def test_metadata_review_requires_evidence_and_cannot_relabel_mixed_as_mcq(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'policy.yaml'
            bad = copy.deepcopy(self.policy); bad['overrides'] = {'LK-EDU-000001': {'medium': 'si'}}
            path.write_text(yaml.safe_dump(bad))
            with self.assertRaisesRegex(ValueError, 'reviewed overrides'): collection.load_policy(path)
            self.policy['overrides'] = {'LK-EDU-000001': {'medium': 'si', 'question_format': 'mcq',
                    'reviewer': 'Alice', 'source_evidence': 'Compared source PDF'}}
            mixed = row(1, title='2026 A/L Physics Sinhala medium Full Paper MCQ Essay Past Paper')
            self.assertEqual(self.plan([mixed, row(2, 'marking_scheme')])['pairs'], [])

    def test_discovery_rejects_explicit_other_medium_but_retains_unknown_for_review(self):
        source = {'id': 'school', 'name': 'School', 'base_url': 'https://school.test/', 'required_medium': 'si'}
        candidate, decision = evaluate_link(Link('/physics.pdf', '2026 Physics Past Paper MCQ English medium'),
                    'Resources', source['base_url'], source, SUBJECTS)
        self.assertIsNone(candidate)
        self.assertEqual(decision.rejection_reason, 'resource medium not selected')
        candidate, _ = evaluate_link(Link('/physics.pdf', '2026 Physics Past Paper MCQ'),
                    'Resources', source['base_url'], source, SUBJECTS)
        self.assertIsNotNone(candidate)

    def test_pastpapers_wiki_pdf_inherits_only_specific_article_identity(self):
        source = {'id': 'pastpapers_wiki', 'name': 'Wiki', 'base_url': 'https://pastpapers.wiki/'}
        candidate, _ = evaluate_link(Link('/files/file.pdf', 'Download MCQ Paper'),
                '2026 A/L Biology Past Paper | Sinhala Medium',
                'https://pastpapers.wiki/2026-a-l-biology-past-paper-sinhala-medium/', source, SUBJECTS)
        self.assertEqual(candidate['exam_year'], '2026')
        self.assertIn('Sinhala', candidate['title'])
        self.assertEqual(candidate['subject'], 'Biology')
        english, _ = evaluate_link(Link('/files/file.pdf', 'Download English'),
                '2026 A/L Biology Past Paper | Sinhala Medium',
                'https://pastpapers.wiki/2026-a-l-biology-past-paper-sinhala-medium/',
                {**source, 'required_medium': 'si'}, SUBJECTS)
        self.assertIsNone(english)


class ContentDedupTests(unittest.TestCase):
    def test_second_identical_download_is_audited_without_a_second_raw_file(self):
        fixture = transport.DownloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        second = {**fixture.row, 'doc_id': 'LK-EDU-000010', 'source_url': 'https://school.test/mirror.pdf'}
        fixture.write_catalog([fixture.row, second]); fixture.settings['deduplicate_content'] = True
        result = fixture.execute()
        self.assertEqual([r['outcome'] for r in result['results']], ['downloaded', 'duplicate_content'])
        rows = crawler.read_catalog(fixture.settings['catalog_path'])
        self.assertEqual(rows[1]['status'], 'DUPLICATE')
        self.assertEqual(rows[1]['local_filename'], '')
        self.assertEqual(len(list(fixture.settings['raw_root'].rglob('*.pdf'))), 1)
        self.assertEqual(len(list(fixture.settings['raw_root'].rglob('*.json'))), 1)

    def test_empty_policy_selection_dry_run_does_not_fall_back_to_all_documents(self):
        fixture = transport.DownloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        result = fixture.execute(allowed_doc_ids=[], dry_run=True)
        self.assertEqual(result['planned'], [])
        self.assertEqual(transport.Fetcher.calls, [])

    def test_already_ready_artifacts_also_prevent_duplicate_raw_publication(self):
        fixture = transport.DownloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.execute()
        existing = crawler.read_catalog(fixture.settings['catalog_path'])[0]
        existing['status'] = 'READY'
        second = {**fixture.row, 'doc_id': 'LK-EDU-000010', 'source_url': 'https://school.test/mirror.pdf'}
        fixture.write_catalog([existing, second]); fixture.settings['deduplicate_content'] = True
        result = fixture.execute()
        self.assertEqual(result['results'][0]['outcome'], 'duplicate_content')
        self.assertEqual(len(list(fixture.settings['raw_root'].rglob('*.pdf'))), 1)


class MCQParsingTests(unittest.TestCase):
    TEXT = '1. නිවැරදි පිළිතුර තෝරන්න\n(1) පළමු\n(2) දෙවන\n(3) තුන්වන\n(4) හතරවන\n2. අනෙක් ප්‍රශ්නය\n(1) එක\n(2) දෙක\n(3) තුන\n(4) හතර\n'

    def test_questions_options_and_explicit_answer_keys(self):
        questions, issues = mcq.questions(self.TEXT)
        self.assertEqual(issues, [])
        self.assertEqual([q['question_number'] for q in questions], [1, 2])
        self.assertEqual(questions[0]['options']['2'], 'දෙවන')
        answers, issues = mcq.answers('1. (2)\n2 - 4\n')
        self.assertEqual(answers[1]['answer'], '2')
        self.assertEqual(answers[2]['answer'], '4')
        self.assertEqual(issues, [])

    def test_essay_headings_missing_options_and_conflicting_keys_are_not_guessed(self):
        self.assertEqual(mcq.questions('Essay Questions\n'+self.TEXT)[0], [])
        self.assertEqual(mcq.questions('1. Explain this question\nNo options')[0], [])
        answers, issues = mcq.answers('1. 2\n1. 3\n')
        self.assertNotIn(1, answers)
        self.assertIn('answer_1_conflicting', issues)

    def test_identical_mcqs_keep_one_record_and_conflicting_answers_are_deferred(self):
        record = {'stem': 'ප්‍රශ්නය', 'options': {'1': 'පළමු', '2': 'දෙවන'}, 'answer': '2',
                  'provenance': {'doc_id': 'one'}, 'answer_provenance': {'doc_id': 'two'},
                  'question_number': 1, 'pair_key': ['2026']}
        unique, issues = mcq.deduplicate_linked([record, {**record, 'pair_key': ['2025']}])
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(unique[0]['occurrences']), 2)
        self.assertEqual(issues, [])
        unique, issues = mcq.deduplicate_linked([record, {**record, 'answer': '1'}])
        self.assertEqual(unique, [])
        self.assertEqual(issues[0]['issue'], 'identical_question_conflicting_answers')

    def test_policy_selected_raw_pages_to_provisional_linked_mcqs(self):
        from pipeline.dataset.native import publish, encode, digest
        from test_processing_pipeline import PNG
        fixture = transport.DownloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        paper = {**fixture.row, 'title': '2026 A/L Physics Sinhala medium MCQ Past Paper'}
        scheme = {**paper, 'doc_id': 'LK-EDU-000010', 'source_url': 'https://school.test/marking.pdf',
                  'title': paper['title']+' Marking Scheme', 'document_type': 'marking_scheme'}
        fixture.write_catalog([paper, scheme])
        counter = iter(range(10))
        transport.Fetcher.response_factory = staticmethod(lambda: transport.Response(
            transport.PDF.replace(b'fixture', f'fixture{next(counter)}'.encode())))
        fixture.execute()
        root = fixture.root
        config = yaml.safe_load((crawler.ROOT / 'configs/pipeline.yaml').read_text())
        for stage in ('download', 'processing', 'extraction', 'ocr'):
            config[stage].update(catalog_path=str(fixture.settings['catalog_path']), raw_root=str(fixture.settings['raw_root']),
                                 log_root=str(root / 'logs' / stage))
        config['processing']['output_root'] = str(root / 'processed')
        config_path = root / 'pipeline.yaml'; config_path.write_text(yaml.safe_dump(config))
        (root / 'sources.yaml').write_text(yaml.safe_dump({'sources': [transport.SOURCE]}))
        (root / 'subjects.yaml').write_bytes(crawler.SUBJECTS_PATH.read_bytes())
        policy = copy.deepcopy(POLICY); policy.update(source_ids=['school'], source_preference=['school'])
        policy_path = root / 'collection.yaml'; policy_path.write_text(yaml.safe_dump(policy))
        for item in crawler.read_catalog(fixture.settings['catalog_path']):
            text = self.TEXT if item['document_type'] == 'past_paper' else '1. 2\n2. 4\n'
            identity = {'doc_id': item['doc_id'], 'raw_sha256': item['sha256'], 'page_number': 1,
                        'processing_config_sha256': 'c'*64}
            record = {'schema_version': 'corpus-page-1', 'identity': identity, 'method': 'ocr',
                      'training_approved': False, 'text': text,
                      'prediction': {'outcome': 'predicted', 'completion_status': 'complete'}}
            files = {'page.json': encode(record), 'page.png': PNG, 'text.txt': text.encode()}
            publish(root / 'processed' / item['doc_id'], {**files, 'manifest.json': encode({
                'schema_version': 'corpus-page-bundle-1', 'identity': identity,
                'output_sha256': {name: digest(value) for name, value in files.items()}})})
        selection = collection.for_config(config_path, policy_path)
        self.assertEqual(selection['counts']['pairs'], 1)
        plan_path = root / 'plan'
        collection.write(config_path, policy_path, plan_path)
        self.assertTrue((plan_path / 'deferred_review.csv').is_file())
        report = mcq.extract(config_path, policy_path, root / 'mcqs', 'c'*64)
        self.assertEqual(report['linked_mcqs'], 2)
        records = [json.loads(line) for line in (root / 'mcqs/linked_mcqs.jsonl').read_text().splitlines()]
        self.assertEqual(records[0]['answer'], '2')
        self.assertEqual(len({r['record_id'] for r in records}), 2)
        self.assertTrue(all(r['review_required'] and not r['training_approved'] for r in records))
        self.assertEqual(records[0]['answer_provenance']['doc_id'], 'LK-EDU-000010')
