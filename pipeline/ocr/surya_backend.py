"""Pinned, local-weight Surya trial. Heavy dependencies are optional (Colab only)."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import time

from pipeline.download.downloader import file_hash

VERSION = '0.17.1'
MODEL_ID = 'datalab/surya-ocr-0.17.1'
CHECKPOINTS = {'recognition':'text_recognition/2025_09_23',
               'detection':'text_detection/2025_05_07'}


def require_version():
    if importlib.metadata.version('surya-ocr') != VERSION:
        raise ValueError(f'This adapter requires surya-ocr=={VERSION}')


def local_file(root, value):
    if not isinstance(value,str) or Path(value).is_absolute():
        raise ValueError('Checkpoint file paths must be relative')
    path=(root/value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Missing checkpoint file or path escape')
    return path


def prepare_models(root):
    """Explicit network setup phase; freeze every component file before inference."""
    require_version()
    from surya.common.s3 import download_directory
    root=Path(root).resolve()
    if root.exists():
        raise ValueError('Choose a new model folder; existing snapshots are preserved')
    root.mkdir(parents=True)
    components={}
    for name,checkpoint in CHECKPOINTS.items():
        destination=root/name;destination.mkdir()
        print(f'Downloading Surya {name}: {checkpoint}',flush=True)
        download_directory(checkpoint,str(destination))
        upstream=json.loads((destination/'manifest.json').read_text())
        files=upstream.get('files')
        if not isinstance(files,list) or not files or len(set(files))!=len(files):
            raise ValueError('Invalid upstream checkpoint manifest')
        hashes={}
        for value in ['manifest.json',*files]:
            path=local_file(destination,value)
            hashes[str(path.relative_to(root))]=file_hash(path)
        if not any(key.endswith('.safetensors') for key in hashes):
            raise ValueError('Checkpoint has no safetensors weights')
        components[name]={'checkpoint':checkpoint,'files_sha256':hashes}
    manifest={'schema_version':'surya-local-models-1','model_id':MODEL_ID,
              'surya_version':VERSION,'components':components}
    (root/'selection.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return {**manifest,'path':str(root),'revision':file_hash(root/'selection.json'),
            'revision_kind':'local_components_manifest_sha256'}


def verify_models(root,revision):
    root=Path(root).resolve()
    manifest_path=root/'selection.json'
    if file_hash(manifest_path)!=revision:
        raise ValueError('Surya component manifest checksum mismatch')
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('schema_version')!='surya-local-models-1' or manifest.get('surya_version')!=VERSION or manifest.get('model_id')!=MODEL_ID:
        raise ValueError('Unexpected Surya model manifest')
    components=manifest.get('components')
    if not isinstance(components,dict) or set(components)!=set(CHECKPOINTS):
        raise ValueError('Both Surya recognition and detection components are required')
    for name,checkpoint in CHECKPOINTS.items():
        component=components[name]
        if component.get('checkpoint')!=checkpoint:
            raise ValueError('Unexpected Surya checkpoint')
        hashes=component.get('files_sha256')
        if not isinstance(hashes,dict) or not hashes or not any(p.endswith('.safetensors') for p in hashes):
            raise ValueError('Missing Surya checkpoint hashes')
        for value,expected in hashes.items():
            if not value.startswith(name+'/') or file_hash(local_file(root,value))!=expected:
                raise ValueError('Surya component file checksum mismatch')
        # Reject new/unrecorded files, including changed processor configuration.
        actual={str(p.relative_to(root)) for p in (root/name).rglob('*') if p.is_file()}
        if actual!=set(hashes):
            raise ValueError('Unrecorded Surya component files')
    return manifest


def token_completion(sequences,eos,no_output):
    if not isinstance(sequences,list) or not sequences:
        return 'unverified_upstream'
    if any(not seq or seq[-1] not in {eos,no_output} for seq in sequences):
        return 'region_incomplete'
    return 'complete'


class SuryaBackend:
    def __init__(self,model_path,revision,max_generation_seconds=120):
        require_version()
        manifest=verify_models(model_path,revision)
        import torch
        if not torch.cuda.is_available():
            raise ValueError('Select a T4 GPU runtime in Colab; CUDA is unavailable')
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        from surya.detection import DetectionPredictor
        root=Path(model_path).resolve()
        # Leave dtype=None: this pinned loader chooses float16 on T4. Explicit
        # float16 is converted to BF16 by upstream, so do not pass it here.
        self.foundation=FoundationPredictor(checkpoint=str(root/'recognition'),device='cuda',
                                            attention_implementation='eager')
        self.recognition=RecognitionPredictor(self.foundation)
        self.detection=DetectionPredictor(checkpoint=str(root/'detection'),device='cuda')
        self.maximum_seconds=max_generation_seconds
        self.deadline=None
        self.completion='unverified_upstream'
        self.tokens=[]
        original=self.foundation.prediction_loop
        def capture(*args,**kwargs):
            # Avoid silent removal of repeated tokens; bounded regional decoding
            # and EOS checks expose incomplete regions for review instead.
            kwargs['drop_repeated_tokens']=False
            result=original(*args,**kwargs)
            self.tokens=result[0]
            self.completion=token_completion(self.tokens,self.foundation.processor.eos_token_id,
                                             self.foundation.processor.no_output_token)
            return result
        self.foundation.prediction_loop=capture
        for method in ('prefill','decode'):
            setattr(self.foundation,method,self.deadline_checked(getattr(self.foundation,method)))
        self.identity={'gpu':torch.cuda.get_device_name(0),'python':platform.python_version(),
            'packages':{p:importlib.metadata.version(p) for p in ('surya-ocr','torch','transformers','Pillow')},
            'model_components':manifest['components'],'dtype':str(self.foundation.model.dtype),
            'detection_dtype':str(self.detection.model.dtype),'attention':'eager',
            'recognition_batch_size':4,'detection_batch_size':1,'region_max_tokens':256,
            'math_mode':True,'sort_lines':True,'max_page_seconds':max_generation_seconds,
            'completion_check':'captured regional EOS/no-output tokens',
            'drop_repeated_tokens':False,'network':'blocked during model loading and inference'}

    def deadline_checked(self,method):
        def checked(*args,**kwargs):
            if self.deadline is not None and time.monotonic()>=self.deadline:
                raise TimeoutError('Surya page deadline reached between decoding steps')
            return method(*args,**kwargs)
        return checked

    def recognize(self,image):
        from PIL import Image
        self.completion='unverified_upstream';self.tokens=[]
        self.deadline=time.monotonic()+self.maximum_seconds
        try:
            with Image.open(image) as source:
                page=source.convert('RGB')
            results=self.recognition([page],det_predictor=self.detection,
                detection_batch_size=1,recognition_batch_size=4,sort_lines=True,
                math_mode=True,return_words=True,drop_repeated_text=False,max_tokens=256)
            if len(results)!=1:
                raise ValueError('Surya returned an unexpected page count')
            raw=results[0].model_dump(mode='json')
            text='\n'.join(line['text'] for line in raw['text_lines'])
            complete=self.completion
            if time.monotonic()>=self.deadline:
                complete='time_limit'
            return {'text':text,'raw_result':raw,'region_generated_tokens':[len(seq) for seq in self.tokens],
                'completion_status':complete,
                'outcome':'predicted' if complete=='complete' else ('completion_unverified' if complete=='unverified_upstream' else 'truncated')}
        finally:
            self.deadline=None


def block_network():
    """S3 downloads ignore HF offline flags; block sockets during the trial."""
    import sys
    def guard(event,args):
        if event in {'socket.connect','socket.getaddrinfo','socket.sendto'}:
            raise RuntimeError('Network disabled during Surya inference; prepare weights first')
    sys.addaudithook(guard)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare-models');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('run');p.add_argument('--packet',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--model-path',type=Path,required=True)
    p.add_argument('--revision',required=True);p.add_argument('--max-pages',type=int,default=1)
    p.add_argument('--max-page-seconds',type=int,default=120)
    args=parser.parse_args()
    if args.action=='prepare-models':
        result=prepare_models(args.output)
    else:
        block_network()
        from pipeline.ocr.neural import run
        result=run(args.packet,args.output,'surya',args.model_path,args.revision,
                   max_pages=args.max_pages,max_generation_seconds=args.max_page_seconds)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
