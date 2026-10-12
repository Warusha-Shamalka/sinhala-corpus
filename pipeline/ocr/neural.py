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
MODELS = {'gemma': 'google/gemma-4-E2B-it', 'deepseek': 'deepseek-ai/DeepSeek-OCR-2',
          'qwen': 'Qwen/Qwen2.5-VL-3B-Instruct', 'surya':'datalab/surya-ocr-0.17.1',
          'gemini_api': 'gemini-3.8-flash'}


def repetition_loop(tokens):
    """Conservative exact-token tail heuristic; flagged text always needs review."""
    if len(tokens) < 128:
        return False
    for width in range(1, 65):
        copies = max(4, (128 + width - 1) // width)
        length = width * copies
        if length <= len(tokens):
            block = tokens[-width:]
            if tokens[-length:] == block * copies:
                return True
    return False


class GenerationGuard:
    """Single-image soft deadline/repetition stopping criterion for Gemma/Qwen."""
    def __init__(self, prompt_length, max_seconds, *, clock=time.monotonic):
        self.prompt_length, self.max_seconds, self.clock = prompt_length, max_seconds, clock
        self.started = clock()
        self.reason = None

    def __call__(self, input_ids, scores, **kwargs):
        if self.clock() - self.started >= self.max_seconds:
            self.reason = 'time_limit'
            return True
        count = input_ids.shape[-1] - self.prompt_length
        # Limit device synchronization and ignore prompt tokens entirely.
        if count >= 128 and count % 32 == 0:
            if repetition_loop(input_ids[0, -min(count, 256):].tolist()):
                self.reason = 'repetition_loop'
                return True
        return False


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
    def __init__(self, backend, model_path, max_new_tokens, max_generation_seconds=120):
        import torch
        if not torch.cuda.is_available():
            raise ValueError('Select a GPU runtime in Colab; CUDA is unavailable')
        self.backend, self.maximum, self.torch = backend, max_new_tokens, torch
        self.max_generation_seconds = max_generation_seconds
        versions = {}
        for package in ('torch', 'transformers', 'accelerate', 'Pillow', 'flash-attn'):
            try: versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: pass
        self.identity = {'gpu': torch.cuda.get_device_name(0), 'python': platform.python_version(), 'packages': versions}
        if backend in {'gemma', 'qwen'}:
            from transformers import AutoProcessor, AutoModelForMultimodalLM
            processor_settings = {'min_pixels':256*28*28, 'max_pixels':1280*28*28} if backend == 'qwen' else {}
            self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True, **processor_settings)
            self.model = AutoModelForMultimodalLM.from_pretrained(model_path, local_files_only=True,
                dtype=torch.float16, device_map={'': 0}, attn_implementation='eager').eval()
            self.identity.update(dtype='float16', attention='eager', repetition_guard='exact_token_tail_v1',
                                 max_generation_seconds=max_generation_seconds, processor_settings=processor_settings)
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
                return_tensors='pt', add_generation_prompt=True,
                **({'enable_thinking':False} if self.backend == 'gemma' else {})).to(self.model.device)
            size = inputs['input_ids'].shape[-1]
            from transformers import StoppingCriteriaList
            guard = GenerationGuard(size, self.max_generation_seconds)
            gen_kwargs = {'max_new_tokens': self.maximum, 'do_sample': False,
                          'stopping_criteria': StoppingCriteriaList([guard])}
            if self.backend in {'gemma', 'qwen'}:
                gen_kwargs['repetition_penalty'] = 1.15
            output = self.model.generate(**inputs, **gen_kwargs)
            tokens = output[0][size:]
            raw = self.processor.decode(tokens, skip_special_tokens=False)
            text = (response_text(self.processor.parse_response(raw, prefix=inputs['input_ids']))
                    if self.backend == 'gemma' else self.processor.decode(tokens, skip_special_tokens=True))
            import unicodedata
            text = unicodedata.normalize('NFC', text)
            limited = len(tokens) >= self.maximum
            reason = guard.reason or ('token_limit' if limited else 'complete')
            return {'text':text, 'raw_response':raw, 'generated_tokens':len(tokens),
                    'completion_status':reason, 'outcome':'truncated' if reason != 'complete' else 'predicted'}


def run(packet, output, backend, model_path, revision, *, max_pages=10, max_new_tokens=8192, max_generation_seconds=120, engine=None, api_key=None):
    packet, output = Path(packet), Path(output)
    model_path = Path(model_path) if model_path else None
    manifest = load_packet(packet)
    if backend == 'gemini_api':
        if not api_key:
            import os
            api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or os.environ.get('G_API') or os.environ.get('mmlu')
        if not api_key:
            raise ValueError('Set GEMINI_API_KEY or pass --api-key for the Gemini backend')
    elif backend not in MODELS or not re.fullmatch(r'[0-9a-f]{64}' if backend=='surya' else r'[0-9a-f]{40}', revision):
        raise ValueError('Use a supported backend and pinned revision (Surya: component manifest SHA256; others: full model commit)')
    if backend != 'gemini_api' and (not model_path or not model_path.is_dir()):
        raise ValueError('Download a local model snapshot first')
    if type(max_pages) is not int or max_pages < 1 or type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 8192:
        raise ValueError('Invalid page/token limit')
    if type(max_generation_seconds) is not int or not 1 <= max_generation_seconds <= 3600:
        raise ValueError('Generation time limit must be 1–3600 seconds')
    if output.exists():
        completed = list(output.glob('LK-EDU-*.json'))
        if completed:
            raise ValueError('Choose a new output directory; existing runs are preserved')
        import shutil
        shutil.rmtree(output)
    # Frozen input identities; references and review labels are deliberately not opened here.
    selected = manifest['samples'][:max_pages]
    weights = {}
    if backend != 'gemini_api' and model_path:
        weight_files = sorted(model_path.rglob('*.safetensors'))
        print(f'Verifying {len(weight_files)} model weight files...', flush=True)
        for index, path in enumerate(weight_files, 1):
            print(f'Weights [{index}/{len(weight_files)}]: {path.name}', flush=True)
            weights[str(path.relative_to(model_path))] = file_hash(path)
        if engine is None and not weights: raise ValueError('Local snapshot has no safetensors weights')
    metadata = {'schema_version':'neural-ocr-run-1','backend':backend,'model_id':MODELS[backend], 'model_revision':revision or 'api',
                'weights_sha256':weights, 'packet_manifest_sha256':file_hash(packet/'manifest.json'),
                'prompt':None if backend=='surya' else (PROMPT if backend != 'gemini_api' else 'gemini_sinhala_ocr_v1'),
                'model_revision_kind':'api' if backend=='gemini_api' else ('local_components_manifest_sha256' if backend=='surya' else 'huggingface_commit'),
                'decoding':{'task':'ocr_with_boxes','region_max_tokens':256,'math_mode':True,'sort_lines':True} if backend=='surya' else None,
                'max_new_tokens':None if backend in {'surya','gemini_api'} else max_new_tokens,'max_pages':max_pages,'selected_samples':[s['sample_id'] for s in selected],
                'generation_guard':{'max_seconds':max_generation_seconds,'repetition':'exact_token_tail_v1'} if backend in {'gemma','qwen'} else None,
                'gemma_generation_guard':{'max_seconds':max_generation_seconds,'repetition':'exact_token_tail_v1'} if backend == 'gemma' else None,
                'created_at_utc':utc_now(),'review_required':True,'training_approved':False}
    identity = hashlib.sha256(json.dumps(metadata,sort_keys=True).encode()).hexdigest()
    metadata['run_id'] = identity
    output.mkdir(parents=True)
    metadata['status']='loading';write_json(output/'run.json',metadata)
    try:
        print(f'Loading {MODELS[backend]}...', flush=True)
        loading_started = time.monotonic()
        if engine is None and backend=='gemini_api':
            from pipeline.ocr.gemini_backend import GeminiBackend
            engine=GeminiBackend(api_key, model_name=MODELS['gemini_api'], max_generation_seconds=max_generation_seconds)
        elif engine is None and backend=='surya':
            from pipeline.ocr.surya_backend import SuryaBackend, block_network
            block_network()
            engine=SuryaBackend(model_path,revision,max_generation_seconds)
        engine = engine or GPUBackend(backend, model_path, max_new_tokens, max_generation_seconds)
        metadata.update(runtime=engine.identity, status='running', completed_pages=0)
        write_json(output/'run.json',metadata)
        print(f'Model loaded in {time.monotonic()-loading_started:.1f}s; {len(selected)} pages selected.', flush=True)
        for index, sample in enumerate(selected,1):
            start=time.monotonic()
            metadata.update(current_sample=sample['sample_id'], updated_at_utc=utc_now())
            write_json(output/'run.json',metadata)
            print(f"[{index}/{len(selected)}] {sample['sample_id']}: starting transcription", flush=True)
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
            metadata.update(completed_pages=index, updated_at_utc=utc_now())
            write_json(output/'run.json',metadata)
            print(f"[{index}/{len(selected)}] {sample['sample_id']}: {record['outcome']} ({record['seconds']:.1f}s)",flush=True)
        metadata.update(status='finished', current_sample=None)
    except Exception as exc:
        metadata.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        metadata['updated_at_utc']=utc_now();write_json(output/'run.json',metadata)
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=MODELS,required=True);parser.add_argument('--model-path',type=Path,default=None)
    parser.add_argument('--revision',default=None);parser.add_argument('--max-pages',type=int,default=10)
    parser.add_argument('--max-new-tokens',type=int,default=8192)
    parser.add_argument('--api-key',default=None,help='API key for gemini_api backend (or set GEMINI_API_KEY env var)')
    parser.add_argument('--max-generation-seconds',type=int,default=120,help='Gemma/Qwen soft decode deadline; Surya soft page deadline between model steps; excludes model loading; not applied to DeepSeek upstream infer')
    args=parser.parse_args()
    try:run(args.packet,args.output,args.backend,args.model_path,args.revision,max_pages=args.max_pages,max_new_tokens=args.max_new_tokens,max_generation_seconds=args.max_generation_seconds,api_key=args.api_key)
    except Exception as exc:parser.exit(2,f'Neural OCR comparison error: {exc}\n')

if __name__=='__main__':main()
