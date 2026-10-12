import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from pipeline.ocr import surya_backend as s
from pipeline.ocr import neural
from pipeline.quality import ocr_benchmark as benchmark
import test_ocr_benchmark as fixtures


class SuryaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.models=self.root/'models';self.models.mkdir()
        components={}
        for name,checkpoint in s.CHECKPOINTS.items():
            folder=self.models/name;folder.mkdir()
            hashes={}
            for filename,content in [('model.safetensors',b'fixture weights'),('config.json',b'{}'),
                                      ('manifest.json',b'{"files":["model.safetensors","config.json"]}')]:
                path=folder/filename;path.write_bytes(content)
                hashes[str(path.relative_to(self.models))]=hashlib.sha256(content).hexdigest()
            components[name]={'checkpoint':checkpoint,'files_sha256':hashes}
        self.manifest={'schema_version':'surya-local-models-1','surya_version':s.VERSION,
                       'model_id':s.MODEL_ID,'components':components}
        self.save_manifest()

    def save_manifest(self):
        path=self.models/'selection.json';path.write_text(json.dumps(self.manifest))
        self.revision=hashlib.sha256(path.read_bytes()).hexdigest()

    def test_both_components_and_configs_are_checked(self):
        self.assertEqual(s.verify_models(self.models,self.revision)['model_id'],s.MODEL_ID)
        (self.models/'detection/config.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'checksum'):
            s.verify_models(self.models,self.revision)

    def test_missing_component_foreign_files_and_manifest_changes_rejected(self):
        with self.assertRaisesRegex(ValueError,'manifest checksum'):
            s.verify_models(self.models,'f'*64)
        (self.models/'recognition/unrecorded.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unrecorded'):
            s.verify_models(self.models,self.revision)
        (self.models/'recognition/unrecorded.json').unlink()
        del self.manifest['components']['detection'];self.save_manifest()
        with self.assertRaisesRegex(ValueError,'Both Surya'):
            s.verify_models(self.models,self.revision)

    def test_paths_cannot_escape_snapshot(self):
        with self.assertRaises(ValueError):s.local_file(self.models,'../outside')
        with self.assertRaises(ValueError):s.local_file(self.models,str(self.models/'selection.json'))

    def test_region_cap_or_missing_tokens_do_not_claim_completion(self):
        self.assertEqual(s.token_completion([[1,2,9],[3,8]],9,8),'complete')
        self.assertEqual(s.token_completion([[1,2,9],[3,4]],9,8),'region_incomplete')
        self.assertEqual(s.token_completion([[]],9,8),'region_incomplete')
        self.assertEqual(s.token_completion([],9,8),'unverified_upstream')

    def test_deadline_checked_between_model_steps(self):
        backend=s.SuryaBackend.__new__(s.SuryaBackend);backend.deadline=10
        called=[];method=backend.deadline_checked(lambda:called.append(True))
        with patch.object(s.time,'monotonic',return_value=11):
            with self.assertRaises(TimeoutError):method()
        self.assertEqual(called,[])
        backend.deadline=None;method();self.assertEqual(called,[True])

    def fake_modules(self,finish=True):
        outer=self
        class Foundation:
            def __init__(self,**kwargs):
                outer.assertEqual(kwargs['checkpoint'],str(outer.models/'recognition'))
                outer.assertNotIn('dtype',kwargs)  # explicit fp16 forces BF16 upstream
                self.model=types.SimpleNamespace(dtype='float16')
                self.processor=types.SimpleNamespace(eos_token_id=9,no_output_token=8)
            def prediction_loop(self,*args,**kwargs):
                outer.assertFalse(kwargs['drop_repeated_tokens'])
                return [[1,2,9] if finish else [1,2,3]],None,None,None
            def prefill(self):pass
            def decode(self):pass
        class Detection:
            def __init__(self,**kwargs):
                outer.assertEqual(kwargs['checkpoint'],str(outer.models/'detection'))
                self.model=types.SimpleNamespace(dtype='float16')
        class Recognition:
            def __init__(self,foundation):self.foundation=foundation
            def __call__(self,images,**kwargs):
                outer.assertEqual(kwargs['recognition_batch_size'],4)
                outer.assertEqual(kwargs['detection_batch_size'],1)
                self.foundation.prediction_loop(drop_repeated_tokens=True)
                raw={'text_lines':[{'text':'සිංහල පාඩම','bbox':[0,0,10,10],'confidence':0.9}],
                     'image_bbox':[0,0,600,800]}
                return [types.SimpleNamespace(model_dump=lambda **kw:raw)]
        class Picture:
            def convert(self,mode):return self
            def __enter__(self):return self
            def __exit__(self,*args):pass
        torch=types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda:True,
                                                              get_device_name=lambda n:'fixture T4'))
        return {'torch':torch,'surya.foundation':types.SimpleNamespace(FoundationPredictor=Foundation),
                'surya.recognition':types.SimpleNamespace(RecognitionPredictor=Recognition),
                'surya.detection':types.SimpleNamespace(DetectionPredictor=Detection),
                'PIL':types.SimpleNamespace(Image=types.SimpleNamespace(open=lambda path:Picture()))}

    def test_adapter_preserves_boxes_and_only_scores_region_eos(self):
        for finish in (True,False):
            def version(package):return s.VERSION if package=='surya-ocr' else 'fixture'
            with patch.dict('sys.modules',self.fake_modules(finish)), \
                 patch.object(s.importlib.metadata,'version',side_effect=version):
                backend=s.SuryaBackend(self.models,self.revision)
                record=backend.recognize(self.root/'image.png')
                self.assertEqual(record['text'],'සිංහල පාඩම')
                self.assertEqual(record['raw_result']['text_lines'][0]['bbox'],[0,0,10,10])
                self.assertEqual(record['outcome'],'predicted' if finish else 'truncated')
                self.assertIsNone(backend.deadline)

    def test_surya_runner_reuses_existing_image_provenance_and_evaluator(self):
        fixture=fixtures.AccuracyTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        output=fixture.root/'surya'
        run=neural.run(fixture.packet,output,'surya',self.models,self.revision,
                       max_pages=1,engine=fixtures.FakeModel())
        self.assertEqual(run['model_revision_kind'],'local_components_manifest_sha256')
        self.assertIsNone(run['prompt']);self.assertIsNone(run['max_new_tokens'])
        self.assertEqual(len(run['weights_sha256']),2)
        report=benchmark.evaluate(fixture.packet,[output])
        self.assertEqual(report['models'][0]['outcomes'],{'predicted':1,'missing':1})
        self.assertEqual(report['status'],'pending_references')
        self.assertFalse(report['training_approved'])

    def test_network_guard_blocks_socket_operations_only(self):
        guards=[]
        with patch('sys.addaudithook',side_effect=guards.append):s.block_network()
        for event in ('socket.connect','socket.getaddrinfo','socket.sendto'):
            with self.assertRaisesRegex(RuntimeError,'Network disabled'):guards[0](event,())
        guards[0]('open',('local file',))

    def test_setup_freezes_both_downloads_and_refuses_overwrite(self):
        def download(checkpoint,destination):
            folder=Path(destination)
            (folder/'model.safetensors').write_bytes(checkpoint.encode())
            (folder/'manifest.json').write_text('{"files":["model.safetensors"]}')
        with patch.object(s,'require_version'), \
             patch.dict('sys.modules',{'surya.common.s3':types.SimpleNamespace(download_directory=download)}):
            result=s.prepare_models(self.root/'prepared')
            self.assertEqual(len(result['components']),2)
            s.verify_models(Path(result['path']),result['revision'])
            with self.assertRaisesRegex(ValueError,'existing'):
                s.prepare_models(self.root/'prepared')


if __name__=='__main__':unittest.main()
