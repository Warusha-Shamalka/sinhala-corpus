import logging
import unittest
from unittest.mock import patch

from pipeline.discovery import crawler
from pipeline.discovery.filters import detect_document_type
from pipeline.discovery.parser import parse_html, evaluate_link


class MarkingDiscoveryTests(unittest.TestCase):
    def test_seeds_reject_other_domains_files_and_bad_types(self):
        for urls in ('https://school.test/keys', ['https://other.test/keys'], ['https://school.test/key.pdf']):
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                crawler.source_start_urls({'base_url':'https://school.test/', 'start_urls':urls})

    def test_seed_listing_is_visited_before_home_with_one_page_budget(self):
        requested=[]
        class Fetcher:
            error_count=0
            def __init__(self,*args,**kwargs): pass
            def robots_allowed(self,url): return True
            def fetch_html(self,url,base):
                requested.append(url)
                return crawler.FetchedPage('<a href="/key.pdf">Physics marking scheme</a>',url)
        source={'id':'school','name':'School','base_url':'https://school.test/', 'start_urls':['https://school.test/keys']}
        with patch.object(crawler,'PoliteFetcher',Fetcher):
            rows,_=crawler.discover_source(source,{'domains':{}},{'max_pages_per_source':1,'request_delay_seconds':0},logging.getLogger('fixture'))
        self.assertEqual(requested,['https://school.test/keys'])
        self.assertEqual(rows[0]['document_type'],'marking_scheme')

    def test_paper_card_supplies_local_full_title_without_neighbor_bleed(self):
        html='<div class="paper-card"><h3>2020 AL Physics marking scheme</h3><a href="/a.pdf">View</a><a href="/a.pdf">Download</a></div><div class="paper-card"><h3>2021 Biology paper</h3><a href="/b.pdf">Download</a></div>'
        source={'name':'School','base_url':'https://school.test/'}
        rows=[evaluate_link(link,'','https://school.test/keys',source,{'domains':{}})[0] for link in parse_html(html).links]
        self.assertIn('Physics',rows[0]['title']); self.assertNotIn('Biology',rows[0]['title'])
        self.assertEqual(rows[0]['document_type'],'marking_scheme')

    def test_answer_key_and_sinhala_marking_labels(self):
        for title in ('Physics answer key','ලකුණු දීමේ පටිපාටිය'):
            self.assertEqual(detect_document_type('https://school.test/key.pdf',title),'marking_scheme')
