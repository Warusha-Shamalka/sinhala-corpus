"""Optional GPU OCR comparison. Reads page images, never reference transcriptions."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import tempfile
import time

from pipeline.download.downloader import file_hash
from pipeline.extraction.extractor import utc_now
from pipeline.quality.ocr_benchmark import load_packet, relative_file

PROMPT = ('Transcribe all visible text from this Sinhala educational page in reading order. '
          'Preserve Sinhala spelling, numbers, punctuation, questions and answer choices. '
          'Represent mathematical expressions using LaTeX. Do not solve questions, summarize, '
          'translate, correct the source, or invent missing text. Use [UNREADABLE] for illegible text. '
          'Output only the transcription.')
MODELS = {'gemma': 'google/gemma-4-E2B-it', 'deepseek': 'deepseek-ai/DeepSeek-OCR-2'}


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def response_text(parsed):
    if not isinstance(parsed, dict):
        raise ValueError('Unexpected Gemma response structure')
    content = parsed.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(x, dict) and x.get('type') == 'text' and isinstance(x.get('text'), str) for x in content):
        return '\n'.join(x['text'] for x in content)
    raise ValueError('Unexpected Gemma transcription content')


class GPUBackend:
    def __init__(self, backend, model_path, max_new_tokens):
        import torch
        if not torch.cuda.is_available():
            raise ValueError('Select a GPU runtime in Colab; CUDA is unavailable')
        self.backend, self.maximum, self.torch = backend, max_new_tokens, torch
        versions = {}
        for package in ('torch', 'transformers', 'accelerate', 'Pillow', 'flash-attn'):
            try: versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: pass
        self.identity = {'gpu': torch.cuda.get_device_name(0), 'python': platform.python_version(), 'packages': versions}
        if backend == 'gemma':
            from transformers import AutoProcessor, AutoModelForMultimodalLM
            self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
            self.model = AutoModelForMultimodalLM.from_pretrained(model_path, local_files_only=True,
                dtype=torch.float16, device_map={'': 0}, attn_implementation='eager').eval()
            self.identity.update(dtype='float16', attention='eager')
        else:
            if torch.cuda.get_device_capability(0)[0] < 8 or not torch.cuda.is_bf16_supported(including_emulation=False):
                raise ValueError('Upstream DeepSeek-OCR-2 uses BF16: select an L4/A100-class GPU; this adapter cannot run on T4')
            if max_new_tokens != 8192:
                raise ValueError('DeepSeek upstream infer fixes max_new_tokens=8192')
            from transformers import AutoModel, AutoTokenizer
            self.processor = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
            self.model = AutoModel.from_pretrained(model_path, trust_remote_code=True, local_files_only=True,
                _attn_implementation='flash_attention_2', use_safetensors=True).eval().cuda().to(torch.bfloat16)
            self.identity.update(dtype='bfloat16', attention='flash_attention_2', upstream_remote_code=True)

    def recognize(self, image):
        torch = self.torch
        with torch.inference_mode():
            if self.backend == 'deepseek':
                with tempfile.TemporaryDirectory(prefix='deepseek-ocr-') as folder:
                    text = self.model.infer(self.processor, prompt='<image>\n'+PROMPT, image_file=str(image),
                        output_path=folder, base_size=1024, image_size=768, crop_mode=True, save_results=False, eval_mode=True)
                if not isinstance(text, str): raise ValueError('DeepSeek returned no transcription')
                # Upstream infer hides token IDs. Length completion cannot be independently verified.
                return {'text':text, 'completion_status':'unverified_upstream', 'outcome':'completion_unverified'}
            from PIL import Image
            with Image.open(image) as source:
                picture = source.convert('RGB')
            messages = [{'role':'user','content':[{'type':'image','image':picture},{'type':'text','text':PROMPT}]}]
            inputs = self.processor.apply_chat_template(messages, tokenize=True, return_dict=True,
                return_tensors='pt', add_generation_prompt=True, enable_thinking=False).to(self.model.device)
            size = inputs['input_ids'].shape[-1]
            output = self.model.generate(**inputs, max_new_tokens=self.maximum, do_sample=False)
            tokens = output[0][size:]
            raw = self.processor.decode(tokens, skip_special_tokens=False)
            text = response_text(self.processor.parse_response(raw, prefix=inputs['input_ids']))
            limited = len(tokens) >= self.maximum
            return {'text':text, 'raw_response':raw, 'generated_tokens':len(tokens),
                    'completion_status':'token_limit' if limited else 'complete', 'outcome':'truncated' if limited else 'predicted'}


def run(packet, output, backend, model_path, revision, *, max_pages=10, max_new_tokens=8192, engine=None):
    packet, output, model_path = Path(packet), Path(output), Path(model_path)
    manifest = load_packet(packet)
    if backend not in MODELS or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use a supported backend and full 40-character model commit revision')
    if not model_path.is_dir(): raise ValueError('Download a local model snapshot first')
    if type(max_pages) is not int or max_pages < 1 or type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 8192:
        raise ValueError('Invalid page/token limit')
    if output.exists(): raise ValueError('Choose a new output directory; existing runs are preserved')
    # Frozen input identities; references and review labels are deliberately not opened here.
    selected = manifest['samples'][:max_pages]
    weights = {str(p.relative_to(model_path)):file_hash(p) for p in sorted(model_path.rglob('*.safetensors'))}
    if engine is None and not weights: raise ValueError('Local snapshot has no safetensors weights')
    metadata = {'schema_version':'neural-ocr-run-1','backend':backend,'model_id':MODELS[backend], 'model_revision':revision,
                'weights_sha256':weights, 'packet_manifest_sha256':file_hash(packet/'manifest.json'), 'prompt':PROMPT,
                'max_new_tokens':max_new_tokens,'max_pages':max_pages,'selected_samples':[s['sample_id'] for s in selected],
                'created_at_utc':utc_now(),'review_required':True,'training_approved':False}
    identity = hashlib.sha256(json.dumps(metadata,sort_keys=True).encode()).hexdigest()
    metadata['run_id'] = identity
    output.mkdir(parents=True)
    metadata['status']='loading';write_json(output/'run.json',metadata)
    try:
        engine = engine or GPUBackend(backend, model_path, max_new_tokens)
        metadata.update(runtime=engine.identity, status='running');write_json(output/'run.json',metadata)
        for index, sample in enumerate(selected,1):
            start=time.monotonic()
            image=relative_file(packet,sample['image_path'])
            record={'schema_version':'neural-ocr-prediction-1','sample_id':sample['sample_id'],
                    'run_id':identity,'image_sha256':sample['image_sha256'],'review_required':True,'training_approved':False}
            try:
                if file_hash(image)!=sample['image_sha256']:raise ValueError('Image changed before inference')
                record.update(engine.recognize(image))
                if file_hash(image)!=sample['image_sha256']:raise ValueError('Image changed during inference')
                if not isinstance(record.get('text'),str) or len(record['text'])>50000:raise ValueError('Invalid/oversized transcription')
                if not record['text'].strip():record['outcome']='empty'
            except Exception as exc:
                record.update(outcome='failed',text='',error=f'{type(exc).__name__}: {exc}')
            record['seconds']=round(time.monotonic()-start,3)
            write_json(output/f"{sample['sample_id']}.json",record)
            print(f"[{index}/{len(selected)}] {sample['sample_id']}: {record['outcome']}",flush=True)
        metadata['status']='finished'
    except Exception as exc:
        metadata.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        metadata['updated_at_utc']=utc_now();write_json(output/'run.json',metadata)
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=MODELS,required=True);parser.add_argument('--model-path',type=Path,required=True)
    parser.add_argument('--revision',required=True);parser.add_argument('--max-pages',type=int,default=10)
    parser.add_argument('--max-new-tokens',type=int,default=8192)
    args=parser.parse_args()
    try:run(args.packet,args.output,args.backend,args.model_path,args.revision,max_pages=args.max_pages,max_new_tokens=args.max_new_tokens)
    except Exception as exc:parser.exit(2,f'Neural OCR comparison error: {exc}\n')

if __name__=='__main__':main()
