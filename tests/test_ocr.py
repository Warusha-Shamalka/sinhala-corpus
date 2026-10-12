import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from pipeline.ocr import ocr
from pipeline.extraction import extractor
from pipeline.progress import read_status
import test_extraction as fixtures


HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
TSV = (HEADER + '5\t1\t1\t1\t1\t1\t10\t10\t100\t20\t85\tසිංහල පාඩම ඉතිහාසය දසවන ශ්‍රේණිය\n').encode()
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + struct.pack('>II', 600, 800)


class FakeBackend:
    identity = {'engine': 'fixture', 'renderer': 'fixture', 'traineddata_sha256': {'sin':'fixture'}}
    calls = []
    def recognize(self, pdf, number, timeout):
        self.calls.append(number)
        return PNG, TSV


class OCRTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExtractionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.backend.pages = [fixtures.NATIVE, fixtures.BLANK, fixtures.BLANK, fixtures.BLANK]
        result = self.fixture.run_stage()['results'][0]
        self.bundle = Path(result['bundle_path'])
        self.settings = ocr.load_settings(extractor.PIPELINE_PATH)
        self.settings.update(catalog_path=self.fixture.settings['catalog_path'], raw_root=self.fixture.settings['raw_root'],
                             extraction_root=self.fixture.settings['output_root'], output_root=self.fixture.root/'ocr', log_root=self.fixture.root/'ocr-logs')
        self.backend = FakeBackend()
        self.backend.calls = []
        self.doc_id = self.fixture.row['doc_id']
        self.before_catalog = self.settings['catalog_path'].read_bytes()
        self.before_native = {p.name:p.read_bytes() for p in self.bundle.iterdir()}

    def execute(self, **kwargs):
        return ocr.run(self.settings, self.doc_id, backend=self.backend, **kwargs)

    def test_selective_ocr_preserves_native_and_catalog(self):
        report = self.execute(progress_mode='off')
        self.assertEqual(report['selected_pages'], [2,3,4])
        self.assertEqual(self.backend.calls, [2,3,4])
        self.assertFalse(report['catalog_updated'])
        self.assertEqual(self.settings['catalog_path'].read_bytes(), self.before_catalog)
        self.assertEqual(self.before_native, {p.name:p.read_bytes() for p in self.bundle.iterdir()})
        record = json.loads((Path(report['results'][0]['bundle_path'])/'page.json').read_text())
        self.assertIn('සිංහල', record['text'])
        self.assertEqual(record['page_number'], 2)
        self.assertEqual(record['coordinate_system'], 'rendered_image_pixels')
        self.assertEqual(record['words'][0]['confidence'],85)
        self.assertEqual(record['quality_review'], 'pending')
        self.assertTrue(record['review_required'])
        self.assertEqual(read_status(Path(report['progress_path']))['counts']['pages_completed'],3)

    def test_page_cap_and_requested_page_safety(self):
        self.settings['max_pages']=1
        report=self.execute()
        self.assertEqual(report['selected_pages'],[2])
        self.assertEqual(report['unselected_flagged_pages'],2)
        self.assertEqual(self.execute(page_numbers=[4])['selected_pages'],[4])
        for pages in ([1],[5],[2,2],[0]):
            with self.assertRaises(ocr.OCRError): self.execute(page_numbers=pages)

    def test_dry_run_has_no_engine_or_writes(self):
        with patch.object(ocr,'TesseractBackend',side_effect=AssertionError('engine')):
            report=ocr.run(self.settings,self.doc_id,dry_run=True,progress_mode='plain')
        self.assertEqual(report['results'],[])
        self.assertFalse(self.settings['output_root'].exists())
        self.assertFalse(self.settings['log_root'].exists())
        self.assertEqual(self.settings['catalog_path'].read_bytes(),self.before_catalog)

    def test_resume_does_not_rewrite_or_recognize(self):
        report=self.execute(page_numbers=[2])
        folder=Path(report['results'][0]['bundle_path'])
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in folder.iterdir()}
        with patch.object(self.backend,'recognize',side_effect=AssertionError('recognize')):
            self.assertTrue(self.execute(page_numbers=[2])['results'][0]['reused'])
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in folder.iterdir()})

    def test_corrupt_output_is_not_overwritten(self):
        report=self.execute(page_numbers=[2])
        text=Path(report['results'][0]['bundle_path'])/'text.txt'
        text.write_text('tampered')
        report=self.execute(page_numbers=[2])
        self.assertEqual(report['results'][0]['outcome'],'failed')
        self.assertEqual(text.read_text(),'tampered')

    def test_input_integrity_and_ambiguity(self):
        self.fixture.raw.write_bytes(b'bad raw')
        with self.assertRaises(ocr.DownloadError): self.execute()
        self.assertEqual(self.backend.calls,[])
        self.fixture.raw.write_bytes(self.fixture.original_raw)
        shutil.copytree(self.bundle,self.bundle.parent/'another')
        with self.assertRaisesRegex(ocr.OCRError,'one native'): self.execute()
        self.assertEqual(self.execute(bundle=self.bundle,page_numbers=[2])['results'][0]['outcome'],'review_required')

    def test_empty_or_low_confidence_text_stays_pending(self):
        blank=ocr.parse_tsv(HEADER.encode(),(600,800),self.settings)
        self.assertIsNone(blank['mean_word_confidence'])
        self.assertIn('little_or_no_ocr_text',blank['quality_flags'])
        self.assertIn('low_engine_confidence',blank['quality_flags'])
        low=ocr.parse_tsv(TSV.replace(b'\t85\t',b'\t10\t'),(600,800),self.settings)
        self.assertIn('low_engine_confidence',low['quality_flags'])
        self.assertTrue(low['review_required'])

    def test_literal_quotes_do_not_merge_tsv_rows(self):
        data = (HEADER + '5\t1\t1\t1\t1\t1\t10\t10\t10\t20\t85\t"\n'
                + '5\t1\t1\t1\t1\t2\t30\t10\t100\t20\t90\tlesson\n').encode()
        record=ocr.parse_tsv(data,(600,800),self.settings)
        self.assertEqual(len(record['words']),2)
        self.assertEqual(record['text'],'" lesson')
        self.assertNotIn('\t',record['text'])

    def test_config_and_models_change_cache_identity(self):
        first=self.execute(page_numbers=[2])['results'][0]['bundle_path']
        self.backend.identity={**self.backend.identity,'engine':'changed'}
        second=self.execute(page_numbers=[2])['results'][0]['bundle_path']
        self.assertNotEqual(first,second)

    def test_page_failure_and_interrupt_are_resumable(self):
        with patch.object(self.backend,'recognize',side_effect=ocr.OCRError('failed backend')):
            report=self.execute(page_numbers=[2],progress_mode='off')
        self.assertEqual(report['results'][0]['outcome'],'failed')
        self.assertEqual(read_status(Path(report['progress_path']))['status'],'failed')
        with patch.object(self.backend,'recognize',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.execute(page_numbers=[2],progress_mode='off')
        snapshots=[read_status(p) for p in self.settings['log_root'].glob('*.progress.json')]
        self.assertIn('interrupted',[s['status'] for s in snapshots])
        self.assertEqual(list(self.settings['output_root'].rglob('.ocr-*')),[])

    def test_invalid_tsv_png_and_limits_fail_cleanly(self):
        for tsv in (b'bad header',TSV.replace(b'\t85\t',b'\tnan\t'),TSV.replace(b'\t100\t20\t',b'\t9999\t20\t')):
            with self.assertRaises(ocr.OCRError): ocr.parse_tsv(tsv,(600,800),self.settings)
        with self.assertRaises(ocr.OCRError): ocr.png_dimensions(b'not png')
        self.settings['max_command_bytes']=1
        self.assertEqual(self.execute(page_numbers=[2])['results'][0]['outcome'],'failed')


@unittest.skipUnless(shutil.which('tesseract') and shutil.which('pdftoppm'),'Install Tesseract for real backend test')
class RealOCRTests(unittest.TestCase):
    def test_real_printed_pdf_render_and_recognition(self):
        settings=ocr.load_settings(extractor.PIPELINE_PATH)
        backend=ocr.TesseractBackend(settings)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.pdf'
            path.write_bytes(fixtures.make_pdf())
            png,tsv=backend.recognize(path,1,60)
            record=ocr.parse_tsv(tsv,ocr.png_dimensions(png),settings)
            self.assertIn('History',record['text'])
            self.assertTrue(record['review_required'])
            self.assertEqual(set(backend.identity['traineddata_sha256']),{'sin','eng'})
