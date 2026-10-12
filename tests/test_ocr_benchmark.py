import ast
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import struct
import yaml

from pipeline.quality import ocr_benchmark as benchmark
from pipeline.ocr import neural


class FakeModel:
    identity = {'engine':'fixture-no-model'}
    def recognize(self,image):
        return {'text':'සිංහල පාඩම', 'outcome':'predicted','completion_status':'complete'}


class AccuracyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.packet=self.root/'packet';self.packet.mkdir()
        (self.packet/'images').mkdir();(self.packet/'references').mkdir()
        self.samples=[]
        for i,split in ((1,'calibration'),(2,'holdout')):
            sid=f'LK-EDU-{i:06d}_p000001'
            image=self.packet/'images'/f'{sid}.png';image.write_bytes(b'fixture image')
            (self.packet/'references'/f'{sid}.txt').write_text('',encoding='utf-8')
            self.samples.append({'sample_id':sid,'doc_id':f'LK-EDU-{i:06d}','raw_sha256':str(i)*64,
                'page_number':1,'split':split,'image_path':f'images/{sid}.png','image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                'reference_path':f'references/{sid}.txt'})
        self.manifest={'schema_version':'ocr-reference-packet-1','purpose':'ocr_evaluation','samples':self.samples}
        self.save_manifest()
        self.rows=[{**dict.fromkeys(benchmark.FIELDS,''),'sample_id':s['sample_id'],'status':'pending',
            'content_type':'unknown','equations_present':'unknown','equations_checked':'false'} for s in self.samples]
        self.save_reviews()
        self.model=self.root/'model';self.model.mkdir()

    def save_manifest(self):
        (self.packet/'manifest.json').write_text(json.dumps(self.manifest))

    def save_reviews(self):
        with (self.packet/'review.csv').open('w',newline='') as stream:
            w=csv.DictWriter(stream,fieldnames=benchmark.FIELDS);w.writeheader();w.writerows(self.rows)

    def verify(self,index=0):
        sample=self.samples[index]
        benchmark.relative_file(self.packet,sample['reference_path']).write_text('සිංහල පාඩම',encoding='utf-8')
        benchmark.approve(self.packet,sample['sample_id'],'person-one','person-two','handwritten','no')

    def predict(self,backend='gemma',name='run',engine=None,max_pages=10):
        directory=self.root/name
        neural.run(self.packet,directory,backend,self.model,'a'*40,engine=engine or FakeModel(),max_pages=max_pages)
        return directory

    def test_pending_has_no_accuracy_or_training_approval(self):
        run=self.predict()
        result=benchmark.evaluate(self.packet,[run])
        self.assertEqual(result['status'],'pending_references')
        self.assertIsNone(result['models'][0]['metrics']['holdout']['cer'])
        self.assertFalse(result['training_approved'])

    def test_human_verification_requires_different_people_and_nonempty_text(self):
        sid=self.samples[0]['sample_id']
        for first,second in [('same','same'),('one','two')]:
            with self.assertRaises(ValueError):benchmark.approve(self.packet,sid,first,second,'handwritten','no')
        self.assertEqual(benchmark.read_reviews(self.packet,self.manifest)[sid]['status'],'pending')

    def test_verified_reference_mutation_is_rejected(self):
        self.verify()
        benchmark.relative_file(self.packet,self.samples[0]['reference_path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):benchmark.read_reviews(self.packet,self.manifest)

    def test_raw_document_cannot_cross_splits(self):
        self.samples[1]['raw_sha256']=self.samples[0]['raw_sha256'];self.save_manifest()
        with self.assertRaisesRegex(ValueError,'crosses'):benchmark.load_packet(self.packet)

    def test_paths_and_image_tampering_rejected(self):
        self.samples[0]['reference_path']='../secret';self.save_manifest()
        with self.assertRaisesRegex(ValueError,'escapes'):benchmark.load_packet(self.packet)
        self.samples[0]['reference_path']='references/a.txt';self.save_manifest()
        benchmark.relative_file(self.packet,self.samples[0]['image_path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):benchmark.load_packet(self.packet)

    def test_models_never_read_reference_files(self):
        for sample in self.samples:benchmark.relative_file(self.packet,sample['reference_path']).unlink()
        run=self.predict()
        self.assertEqual(json.loads((run/'run.json').read_text())['status'],'finished')

    def test_metrics_and_document_holdout_coverage(self):
        self.verify(0);self.verify(1)
        runs=[self.predict(),self.predict('deepseek','second')]
        result=benchmark.evaluate(self.packet,runs)
        self.assertTrue(result['comparison_complete'])
        self.assertIsNone(result['winner'])
        for model in result['models']:
            self.assertEqual(model['metrics']['holdout']['cer'],0)
            self.assertEqual(model['metrics']['calibration']['wer'],0)

    def test_same_backend_and_missing_predictions_are_not_complete_comparison(self):
        self.verify(0);self.verify(1)
        first=self.predict();second=self.predict(name='second',max_pages=1)
        self.assertFalse(benchmark.evaluate(self.packet,[first,second])['comparison_complete'])
        with self.assertRaisesRegex(ValueError,'Duplicate'):benchmark.evaluate(self.packet,[first,first])

    def test_failed_and_unverified_completion_are_not_scored(self):
        class Broken(FakeModel):
            def recognize(self,image):raise RuntimeError('out of memory')
        self.verify()
        run=self.predict(engine=Broken())
        self.assertEqual(benchmark.evaluate(self.packet,[run])['models'][0]['metrics']['calibration']['scored_pages'],0)
        class Unverified(FakeModel):
            def recognize(self,image):return {'text':'සිංහල පාඩම','outcome':'completion_unverified'}
        run=self.predict(name='unverified',engine=Unverified())
        self.assertEqual(benchmark.evaluate(self.packet,[run])['models'][0]['metrics']['calibration']['scored_pages'],0)

    def test_repetition_guard_detects_long_loops_without_removing_text(self):
        self.assertTrue(neural.repetition_loop([1, 2, 3, 4, 5, 6, 7] * 25))
        self.assertTrue(neural.repetition_loop([9] * 128))
        self.assertFalse(neural.repetition_loop([1, 2] * 10))
        self.assertFalse(neural.repetition_loop(list(range(256))))
        self.assertFalse(neural.repetition_loop([1, 2] * 100 + list(range(50))))

    def test_generation_guard_excludes_prompt_and_reports_soft_deadline(self):
        class Tokens:
            def __init__(self, values):
                self.values = values
                self.shape = (1, len(values))
            def __getitem__(self, key):
                return Tokens(self.values[key[1]])
            def tolist(self):
                return self.values
        now = [0]
        guard = neural.GenerationGuard(128, 120, clock=lambda:now[0])
        self.assertFalse(guard(Tokens([7]*128 + list(range(64))), None))
        self.assertTrue(guard(Tokens([7]*128 + [9]*128), None))
        self.assertEqual(guard.reason, 'repetition_loop')
        guard = neural.GenerationGuard(128, 120, clock=lambda:now[0])
        now[0] = 121
        self.assertTrue(guard(Tokens([7]*129), None))
        self.assertEqual(guard.reason, 'time_limit')

    def test_progress_snapshot_identifies_page_before_recognition(self):
        outer = self
        observed = []
        class InspectingModel(FakeModel):
            def recognize(self, image):
                snapshot = json.loads((outer.root/'progress'/'run.json').read_text())
                outer.assertEqual(snapshot['status'], 'running')
                outer.assertEqual(snapshot['current_sample'], image.stem)
                outer.assertEqual(snapshot['completed_pages'], len(observed))
                observed.append(image.stem)
                return super().recognize(image)
        directory = self.predict(name='progress', engine=InspectingModel())
        final = json.loads((directory/'run.json').read_text())
        self.assertEqual(final['completed_pages'], 2)
        self.assertIsNone(final['current_sample'])
        self.assertEqual(len(observed), 2)

    def test_outputs_immutable_and_manifest_bound(self):
        run=self.predict()
        with self.assertRaisesRegex(ValueError,'existing'):self.predict()
        self.manifest['changed']='x';self.save_manifest()
        with self.assertRaisesRegex(ValueError,'does not match'):benchmark.evaluate(self.packet,[run])

    def test_edit_distance_normalization_preserves_sinhala_joiners(self):
        self.assertEqual(benchmark.edit_distance('abc','axc'),1)
        self.assertEqual(benchmark.edit_distance('', 'abc'),3)
        self.assertEqual(benchmark.normalize(' e\u0301\n  සිංහල '),'é සිංහල')
        self.assertEqual(benchmark.normalize('ක\u200dක'), 'ක\u200dක')
        self.assertEqual(benchmark.edit_distance(['a','b'],['a']),1)

    def test_gemma_response_structure(self):
        self.assertEqual(neural.response_text({'content':[{'type':'text','text':'සිංහල'}]}),'සිංහල')
        with self.assertRaises(ValueError):neural.response_text({'content':[{'type':'thinking','text':'invented'}]})

    def test_qwen_uses_same_packet_guard_and_verified_comparison(self):
        self.verify(0);self.verify(1)
        first=self.predict()
        second=self.predict('qwen','qwen')
        run=json.loads((second/'run.json').read_text())
        self.assertEqual(run['model_id'],'Qwen/Qwen2.5-VL-3B-Instruct')
        self.assertEqual(run['generation_guard']['max_seconds'],120)
        self.assertFalse(run['training_approved'])
        report=benchmark.evaluate(self.packet,[first,second])
        self.assertTrue(report['comparison_complete'])
        self.assertEqual(report['models'][1]['outcomes'],{'predicted':2})
        self.assertEqual(report['models'][1]['breakdowns']['content_type']['handwritten']['scored_pages'],2)

    def test_running_checkpoint_does_not_make_comparison_complete(self):
        self.verify(0);self.verify(1)
        first=self.predict();second=self.predict('qwen','qwen')
        path=second/'run.json';run=json.loads(path.read_text());run['status']='running'
        path.write_text(json.dumps(run))
        self.assertFalse(benchmark.evaluate(self.packet,[first,second])['comparison_complete'])

    def test_pending_prediction_identity_is_checked_without_reference_accuracy(self):
        run=self.predict('qwen','qwen')
        path=run/(self.samples[0]['sample_id']+'.json')
        record=json.loads(path.read_text());record['image_sha256']='f'*64
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            benchmark.evaluate(self.packet,[run])

    def test_notebook_code_cells_parse_without_executing(self):
        path=Path(__file__).resolve().parents[1]/'notebooks/ocr_accuracy_colab.ipynb'
        notebook=json.loads(path.read_text())
        for cell in notebook['cells']:
            if cell['cell_type']=='code':
                tree = ast.parse(''.join(cell['source']))
                # Also validate Python scripts embedded for subprocess -c.
                for node in tree.body:
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == 'selection_code'
                        for target in node.targets
                    ):
                        ast.parse(ast.literal_eval(node.value))
                self.assertEqual(cell['outputs'],[])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.row={'doc_id':'LK-EDU-000001','status':'DOWNLOADED','sha256':'','title':'Printed Sinhala',
                  'source_url':'https://example.org/worksheet.pdf'}
        pdf=self.root/'pdf'/self.row['doc_id'];pdf.mkdir(parents=True)
        content=b'fixture raw PDF';sha=hashlib.sha256(content).hexdigest()
        self.row['sha256']=sha;(pdf/(sha+'.pdf')).write_bytes(content)
        catalog=self.root/'catalog.csv';catalog.write_text('fixture catalog metadata')
        self.settings={'raw_root':self.root,'catalog_path':catalog,'dpi':300,
            'max_image_side':3000,'command_timeout_seconds':10,'max_command_bytes':100000}
        self.plan=self.root/'selection.yaml'
        self.entry={'doc_id':self.row['doc_id'],'page_number':1,'split':'calibration',
                    'subject_group':'Sinhala','content_type_hint':'printed'}
        self.png=b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\x0dIHDR'+struct.pack('>II',600,800)

    def prepare(self,entries):
        self.plan.write_text(yaml.safe_dump({'schema_version':'ocr-selection-1','samples':entries}))
        with patch.object(benchmark,'read_catalog',return_value=[self.row]), \
             patch.object(benchmark,'recover',return_value={}), \
             patch.object(benchmark.shutil,'which',return_value='/fixture/pdftoppm'), \
             patch.object(benchmark,'command',return_value=self.png), \
             patch.object(benchmark,'select_input',side_effect=AssertionError('native bundle must not be required')):
            return benchmark.prepare_selection(self.settings,self.root/'output',self.plan)

    def test_explicit_selection_accepts_native_pages_and_keeps_pending(self):
        before=self.settings['catalog_path'].read_bytes()
        result=self.prepare([self.entry]);self.assertEqual(result['sample_count'],1)
        manifest=benchmark.load_packet(self.root/'output')
        self.assertEqual(manifest['samples'][0]['content_type_hint'],'printed')
        self.assertEqual(benchmark.read_reviews(self.root/'output',manifest)[self.row['doc_id']+'_p000001']['status'],'pending')
        self.assertEqual(before,self.settings['catalog_path'].read_bytes())
        with self.assertRaisesRegex(ValueError,'overwrite'):self.prepare([self.entry])

    def test_duplicate_page_and_cross_split_rejected_before_output(self):
        for second in (self.entry,{**self.entry,'page_number':2,'split':'holdout'}):
            with self.assertRaisesRegex(ValueError,'Duplicate source page or document crossing splits'):
                self.prepare([self.entry,second])
            self.assertFalse((self.root/'output').exists())

    def test_invalid_source_page_and_style_rejected(self):
        for entry in ({**self.entry,'doc_id':'LK-EDU-999999'},
                      {**self.entry,'page_number':True},
                      {**self.entry,'content_type_hint':'guessed'}):
            with self.assertRaises(ValueError):self.prepare([entry])
            self.assertFalse((self.root/'output').exists())


if __name__=='__main__':unittest.main()
