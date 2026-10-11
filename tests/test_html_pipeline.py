import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pipeline.extraction.html import extract
from pipeline.download import downloader as download
from pipeline.processing import pages
from pipeline.dataset import reviewed
from pipeline.deduplication.grouping import group
import test_download as fixtures

HTML = ('<!doctype html><html><head><title>පාඩම</title></head><body><nav>Home</nav><main>'
        '<h1>ඉතිහාසය පාඩම</h1><p>' + 'සිංහල අධ්‍යාපන පාඩම ' * 20 + '</p>'
        '<script>bad code</script><nav>Menu</nav><table><tr><td>10 kg</td><td>20 kg</td></tr></table>'
        '</main><footer>Contact</footer></body></html>').encode()


class HtmlPipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DownloadTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.settings['accepted_formats'] = ['pdf', 'html']
        self.root = self.fixture.root

    def download(self):
        fixtures.Fetcher.response_factory = staticmethod(lambda: fixtures.Response(HTML, mime='text/html; charset=utf-8'))
        return self.fixture.execute()

    def test_html_download_receipt_restart_and_main_text(self):
        result = self.download()
        self.assertEqual(result['results'][0]['outcome'], 'downloaded')
        row = download.read_catalog(self.fixture.settings['catalog_path'])[0]
        self.assertTrue(row['local_filename'].endswith('.html'))
        self.assertEqual(self.fixture.execute()['results'][0]['outcome'], 'verified_existing')
        receipt = download.recover(row, self.fixture.settings['raw_root'])
        self.assertEqual(receipt['charset'], 'utf-8')
        text = extract(HTML)['text']
        self.assertIn('සිංහල', text); self.assertIn('10 kg\t20 kg', text)
        for bad in ('bad code', 'Home', 'Contact', 'Menu'):
            self.assertNotIn(bad, text)

    def test_html_to_review_to_training_does_not_load_ocr(self):
        self.download()
        settings = {'catalog_path': self.fixture.settings['catalog_path'], 'raw_root': self.fixture.settings['raw_root'],
                    'output_root': self.root / 'processed', 'log_root': self.root / 'processing-logs', 'max_documents': 2,
                    'max_pages': 2, 'dpi': 300, 'max_image_side': 3000, 'render_timeout_seconds': 60,
                    'max_image_bytes': 52428800, 'ocr_mode': 'all', 'ocr': {'backend': 'surya', 'revision': '', 'model_path': '/no/models'}}
        with patch.object(pages, 'command', return_value=b'fixture renderer'), \
             patch.object(pages.shutil, 'which', return_value='/fixture/renderer'), \
             patch.object(pages.backends, 'create', side_effect=AssertionError('OCR loaded')):
            report = pages.run(settings, {'raw_root': settings['raw_root']}, progress_mode='off')
        self.assertEqual(report['outcomes'], {'predicted': 1})
        packet, output = self.root / 'review', self.root / 'dataset'
        reviewed.prepare(settings['output_root'], packet)
        record = json.loads((packet / 'records.jsonl').read_text())
        self.assertTrue((packet / record['image_path']).read_bytes().startswith(b'<!doctype'))
        reviewed.seal(packet, record['record_id'], 'Reviewer 1', 'Reviewer 2', 'Fixture source rights', 'Static source checked', 'train')
        reviewed.export(packet, output)
        self.assertEqual(json.loads((output / 'train.jsonl').read_text())['method'], 'html')

    def test_ambiguous_or_javascript_content_needs_explicit_selection(self):
        with self.assertRaisesRegex(ValueError, 'one main/article'):
            extract(b'<html><body><div>Navigation</div></body></html>')
        text = extract(b'<html><div id="lesson"><p>Content</p></div></html>', main_id='lesson')['text']
        self.assertEqual(text, 'Content')
        with self.assertRaisesRegex(ValueError, 'no text'):
            extract(b'<html><main><script>render()</script></main></html>')
        with self.assertRaises(UnicodeDecodeError): extract(b'<html><main>\xff</main></html>')
        with self.assertRaisesRegex(ValueError, 'byte limit'): extract(HTML, max_bytes=10)

    def test_visual_assets_and_mathml_are_flagged_not_invented(self):
        data = b'<html><article><p>Text</p><img src="diagram.png"><math><mi>x</mi><mn>2</mn></math></article></html>'
        record = extract(data)
        self.assertIn('visual_assets_need_review', record['quality_flags'])
        self.assertEqual(record['assets'][0]['src'], 'diagram.png')
        self.assertEqual(extract(b'<html><div hidden><main>Hidden text</main></div><article>Visible text</article></html>')['text'], 'Visible text')

    def test_near_duplicate_and_whitespace_split_leakage(self):
        words = [f'word{i}' for i in range(100)]
        first = ' '.join(words); second = ' '.join(words[:-1] + ['changed'])
        groups = group([{'text': first, 'split': 'train'}, {'text': second, 'split': 'train'}])
        self.assertEqual(groups, [[0, 1]])
        with self.assertRaisesRegex(ValueError, 'crosses splits'):
            group([{'text': first, 'split': 'train'}, {'text': second, 'split': 'test'}])
        with self.assertRaises(ValueError):
            group([{'text': 'short text', 'split': 'train'}, {'text': 'short\ntext', 'split': 'validation'}])
        self.assertEqual(group([{'text': first, 'split': 'train'}, {'text': 'unrelated different page', 'split': 'test'}]), [[0], [1]])


if __name__ == '__main__': unittest.main()
