import json
import logging
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from pipeline import workflow
from pipeline.discovery import crawler, pairs
from pipeline.discovery.exams import metadata
from pipeline.discovery.filters import detect_document_type
from pipeline.discovery.parser import Link, evaluate_link, parse_html
import test_download as transport


SUBJECTS = yaml.safe_load(crawler.SUBJECTS_PATH.read_text())


def row(number, title, kind='past_paper', **extra):
    value = dict.fromkeys(crawler.CATALOG_COLUMNS, '')
    value.update(doc_id=f'LK-EDU-{number:06d}', title=title, document_type=kind,
                 source='School', source_url=f'https://school.test/{number}.pdf', status='DISCOVERED')
    value.update(extra)
    return value


class ExamMetadataTests(unittest.TestCase):
    def test_identifiers_and_sinhala_aliases(self):
        result = metadata('2023 GCE A/L Physics Past Paper II Sinhala medium new syllabus', '', SUBJECTS)
        self.assertEqual([result[k] for k in ('exam', 'subject', 'exam_year', 'paper_number', 'medium', 'paper_kind', 'syllabus')],
                         ['A-Level', 'Physics', '2023', '2', 'si', 'past', 'new'])
        self.assertFalse(result['verified'])
        self.assertEqual(detect_document_type('', '2023 භෞතික විද්‍යාව ලකුණු දීමේ පටිපාටිය'), 'marking_scheme')
        ranged = metadata('Grades 12-13 Physics past papers', '', SUBJECTS, {'grade': '12-13'})
        self.assertEqual(ranged['grade'], '12-13')
        self.assertNotIn('grade', ranged['conflicts'])

    def test_conflicting_years_parts_and_media_are_unknown(self):
        result = metadata('2023 (2024) A/L Physics Paper I and II Sinhala medium English medium', '', SUBJECTS)
        for field in ('exam_year', 'paper_number', 'medium'):
            self.assertEqual(result[field], '')
            self.assertIn(field, result['conflicts'])

    def test_no_source_language_or_missing_part_is_invented(self):
        result = metadata('2023 Physics marking scheme', '', SUBJECTS)
        self.assertEqual(result['exam_year'], '2023')
        for field in ('medium', 'paper_number', 'exam', 'paper_kind'): self.assertEqual(result[field], '')
        self.assertEqual(metadata('Physics marking scheme', 'https://school.test/downloadFile/2023?id=2024', SUBJECTS)['exam_year'], '')

    def test_govdoc_preserves_link_medium_and_marking_identity(self):
        source = {'id': 'govdoc', 'name': 'GovDoc', 'base_url': 'https://govdoc.lk/', 'language': 'si'}
        title = 'G.C.E. Advance Level Exam 2023 Physics Past Papers'
        paper, _ = evaluate_link(Link('/downloadFile/123', 'Sinhala Paper I'), title, source['base_url'], source, SUBJECTS)
        scheme, _ = evaluate_link(Link('/downloadFile/124', 'Sinhala medium Paper I Marking Scheme'), title,
                                  source['base_url'], source, SUBJECTS)
        self.assertEqual(paper['exam_year'], '2023')
        self.assertEqual(scheme['document_type'], 'marking_scheme')
        self.assertIn('Marking Scheme', scheme['title'])
        self.assertEqual(scheme['language'], '')
        english, _ = evaluate_link(Link('/downloadFile/125', 'English'), title, source['base_url'], source, SUBJECTS)
        self.assertEqual(english['_medium_hint'], 'en')
        self.assertIn('English medium', english['title'])
        wrapped, _ = evaluate_link(Link('/view?fid=65aa423ac98f8&id=8205', 'Sinhala'), title,
                                   source['base_url'], source, SUBJECTS)
        self.assertEqual(wrapped['source_url'], 'https://govdoc.lk/downloadFile/8205')
        for bad in ('/category?id=8205', '/view?id=8205', '/view?fid=65aa423ac98f8&id=8205&id=9999'):
            candidate, _ = evaluate_link(Link(bad, 'Sinhala'), title, source['base_url'], source, SUBJECTS)
            self.assertIsNone(candidate)

    def test_alapiedu_marking_hub_classifies_direct_pdfs_without_global_title_inference(self):
        source = {'id': 'alapiedu', 'name': 'AlApiEdu', 'base_url': 'https://alapiedu.com/'}
        link = Link('/files/2023-physics-paper-1.pdf', '2023 Physics Paper I Sinhala medium')
        scheme, _ = evaluate_link(link, 'Marking Hub', 'https://alapiedu.com/Marking?subject=Physics', source, SUBJECTS)
        self.assertEqual(scheme['document_type'], 'marking_scheme')
        self.assertIn('marking scheme', scheme['title'])
        actual, _ = evaluate_link(link, 'Marking — Physics',
                                 'https://alapiedu.com/Category/marking_hub/MarkingSubject?subject=physics', source, SUBJECTS)
        self.assertEqual(actual['document_type'], 'marking_scheme')
        other, _ = evaluate_link(link, 'Marking Hub', 'https://school.test/resources',
                                 {**source, 'id': 'sample'}, SUBJECTS)
        self.assertEqual(other['document_type'], 'past_paper')

    def test_real_listing_card_shape_preserves_title_and_subject_with_opaque_filename(self):
        html = ('<div class="paper-card"><div class="paper-body"><h3>2023 A/L Paper I Marking Scheme Sinhala medium</h3>'
                '<div class="paper-meta">2023 PDF</div><div class="paper-actions">'
                '<a href="uploads/1788259157_output.pdf">View</a>'
                '<a href="uploads/1788259157_output.pdf">Download</a></div></div></div>')
        page = parse_html(html)
        source = {'id': 'alapiedu', 'name': 'AlApiEdu', 'base_url': 'https://alapiedu.com/'}
        for link in page.links:
            candidate, _ = evaluate_link(link, 'Marking — Physics',
                'https://alapiedu.com/Category/marking_hub/MarkingSubject?subject=physics', source, SUBJECTS)
            self.assertEqual(candidate['document_type'], 'marking_scheme')
            self.assertEqual(candidate['subject'], 'Physics')
            self.assertEqual(candidate['exam_year'], '2023')
            self.assertIn('Paper I', candidate['title'])
            self.assertEqual(candidate['language'], '')


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.paper = row(9, '2023 A/L Physics Past Paper I Sinhala medium new syllabus')
        self.scheme = row(10, '2023 A/L Physics Past Paper I Marking Scheme Sinhala medium new syllabus', 'marking_scheme')

    def test_unique_pair_is_proposed_with_evidence_and_never_approved(self):
        report = pairs.build([self.paper, self.scheme], SUBJECTS)
        self.assertEqual(len(report['proposals']), 1)
        proposal = report['proposals'][0]
        self.assertEqual(proposal['match_status'], 'unique_candidate')
        self.assertTrue(proposal['review_required'])
        self.assertFalse(proposal['training_approved'])
        self.assertEqual(proposal['paper_evidence']['title'], self.paper['title'])

    def test_known_conflicts_never_produce_a_pair(self):
        for before, after in (('2023', '2022'), ('Physics', 'Chemistry'), ('Paper I', 'Paper II'),
                              ('Sinhala medium', 'English medium'), ('new syllabus', 'old syllabus'),
                              ('Past Paper', 'Model Paper')):
            with self.subTest(after=after):
                scheme = {**self.scheme, 'title': self.scheme['title'].replace(before, after)}
                self.assertEqual(pairs.build([self.paper, scheme], SUBJECTS)['proposals'], [])

    def test_missing_identifiers_produce_pending_metadata_not_a_unique_match(self):
        scheme = {**self.scheme, 'title': '2023 Physics Marking Scheme'}
        proposal = pairs.build([self.paper, scheme], SUBJECTS)['proposals'][0]
        self.assertEqual(proposal['match_status'], 'needs_metadata')
        self.assertIn('paper_number', proposal['missing_fields'])

    def test_multiple_schemes_or_multiple_papers_remain_ambiguous(self):
        for rows in ([self.paper, self.scheme, {**self.scheme, 'doc_id': 'LK-EDU-000011'}],
                     [self.paper, {**self.paper, 'doc_id': 'LK-EDU-000011'}, self.scheme]):
            report = pairs.build(rows, SUBJECTS)
            self.assertEqual({p['match_status'] for p in report['proposals']}, {'ambiguous'})

    def test_combined_parts_conflicts_and_term_test_issuers_are_not_guessed(self):
        bad = {**self.paper, 'title': self.paper['title'].replace('Paper I', 'Paper I and II')}
        self.assertEqual(pairs.build([bad, self.scheme], SUBJECTS)['proposals'], [])
        paper = row(9, '2023 Grade 11 Physics First Term Test Paper I Sinhala medium')
        scheme = row(10, '2023 Grade 11 Physics First Term Test Paper I Marking Scheme Sinhala medium', 'marking_scheme')
        proposal = pairs.build([paper, scheme], SUBJECTS)['proposals'][0]
        self.assertEqual(proposal['match_status'], 'needs_metadata')
        self.assertIn('issuer', proposal['missing_fields'])

    def test_paper_candidate_budget_is_explicit(self):
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            pairs.build([self.paper, self.scheme, {**self.scheme, 'doc_id': 'LK-EDU-000011'}], SUBJECTS, max_candidates=1)
        self.assertEqual(pairs.build([self.paper, self.scheme], SUBJECTS, subject='Chemistry')['records'], [])

    def test_packet_is_immutable_dry_run_is_read_only_and_catalog_is_preserved(self):
        fixture = transport.DownloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.write_catalog([self.paper, self.scheme])
        catalog = fixture.settings['catalog_path']; original = catalog.read_bytes()
        output = fixture.root / 'pairs'
        before = set(fixture.root.rglob('*'))
        preview = pairs.prepare(catalog, crawler.SUBJECTS_PATH, output, dry_run=True)
        self.assertEqual(preview['proposals'], 1)
        self.assertEqual(set(fixture.root.rglob('*')), before)
        pairs.prepare(catalog, crawler.SUBJECTS_PATH, output)
        manifest = json.loads((output / 'manifest.json').read_text())
        for name, sha in manifest['output_sha256'].items():
            self.assertEqual(pairs.digest((output / name).read_bytes()), sha)
        self.assertIn('pending', (output / 'review.csv').read_text())
        self.assertEqual(catalog.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            pairs.prepare(catalog, crawler.SUBJECTS_PATH, output)


class DiscoveryEntryTests(unittest.TestCase):
    def test_category_seeds_share_budgets_and_classify_resources_without_individual_urls(self):
        source = {**transport.SOURCE, 'start_urls': ['https://school.test/papers', 'https://school.test/markings', 'https://school.test/books']}
        documents = {
            'https://school.test/': '<title>School</title>',
            source['start_urls'][0]: '<title>Papers</title><a href="/p.pdf">2023 A/L Physics Paper I Sinhala medium past paper</a>',
            source['start_urls'][1]: '<title>Markings</title><a href="/m.pdf">2023 A/L Physics Paper I Sinhala medium past paper marking scheme</a>',
            source['start_urls'][2]: '<title>Books</title><a href="/b.pdf">Grade 10 History textbook</a>'}
        class Fetcher:
            error_count = 0
            requested = []
            def __init__(self, *args, **kwargs): pass
            def robots_allowed(self, url): return True
            def fetch_html(self, url, base):
                self.requested.append(url)
                return crawler.FetchedPage(documents[url], url)
        with patch.object(crawler, 'PoliteFetcher', Fetcher):
            rows, stats = crawler.discover_source(source, SUBJECTS, {'max_depth': 0}, logging.getLogger(__name__))
        self.assertEqual(len(Fetcher.requested), 4)
        self.assertEqual({r['document_type'] for r in rows}, {'past_paper', 'marking_scheme', 'textbook'})
        self.assertEqual(stats['pages_visited'], 4)
        self.assertTrue(any(r.get('exam_year') == '2023' for r in rows))
        # End-to-end: category discovery -> catalog -> typed download -> pair proposal.
        fixture = transport.DownloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.write_catalog([])
        committed = crawler.append_catalog(fixture.settings['catalog_path'], rows)
        self.assertEqual(len(committed), 3)
        from pipeline.download import downloader
        counter = iter(range(100))
        transport.Fetcher.response_factory = staticmethod(lambda: transport.Response(
            transport.PDF.replace(b'fixture', f'fixture{next(counter)}'.encode())))
        with patch.object(downloader, 'PoliteFetcher', transport.Fetcher):
            result = downloader.run(fixture.settings, [transport.SOURCE],
                     document_types=['textbook', 'past_paper', 'marking_scheme'])
        self.assertEqual([r['outcome'] for r in result['results']], ['downloaded'] * 3)
        proposal = pairs.prepare(fixture.settings['catalog_path'], crawler.SUBJECTS_PATH, dry_run=True)
        self.assertEqual(proposal['match_statuses'], {'unique_candidate': 1})

    def test_external_invalid_and_excessive_start_urls_are_rejected(self):
        for urls in (['https://evil.test/'], ['ftp://school.test/'], 'https://school.test/', ['https://school.test/'] * 33):
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                crawler.starting_urls({**transport.SOURCE, 'start_urls': urls})

    def test_download_selection_uses_automatic_categories(self):
        from pipeline.download import downloader
        rows = [row(9, 'History textbook', 'textbook'), row(10, 'Physics notes', 'lesson'),
                row(11, '2023 Physics past paper'), row(12, '2023 Physics marking scheme', 'marking_scheme')]
        jobs, excluded = downloader.plan_downloads(rows, [transport.SOURCE], maximum=10,
                                   document_types=['textbook', 'past_paper', 'marking_scheme'])
        self.assertEqual([r['doc_id'] for r, _ in jobs], ['LK-EDU-000009', 'LK-EDU-000011', 'LK-EDU-000012'])
        self.assertEqual(excluded, [{'doc_id': 'LK-EDU-000010', 'reason': 'document_type_not_selected'}])

    def test_workflow_discovery_uses_persistent_catalog_and_configs(self):
        settings = {'catalog_path': Path('/store/catalog.csv'), 'log_root': Path('/store/logs/download')}
        with patch('sys.argv', ['workflow', 'discover', '--config', '/store/configs/pipeline.yaml', '--source', 'school', '--dry-run']), \
             patch.object(workflow.downloader, 'load_settings', return_value=settings), patch.object(crawler, 'run', return_value=0) as run:
            self.assertEqual(workflow.main(), 0)
        args = run.call_args.args[0]
        self.assertEqual(args.catalog, Path('/store/catalog.csv'))
        self.assertEqual(args.sources, Path('/store/configs/sources.yaml'))
        self.assertTrue(args.dry_run)
        self.assertEqual(args.source, 'school')
