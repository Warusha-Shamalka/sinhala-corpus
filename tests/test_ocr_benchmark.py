import ast
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

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

    def test_notebook_code_cells_parse_without_executing(self):
        path=Path(__file__).resolve().parents[1]/'notebooks/ocr_accuracy_colab.ipynb'
        notebook=json.loads(path.read_text())
        for cell in notebook['cells']:
            if cell['cell_type']=='code':
                ast.parse(''.join(cell['source']))
                self.assertEqual(cell['outputs'],[])


if __name__=='__main__':unittest.main()
