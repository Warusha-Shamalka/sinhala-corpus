"""Independent source-page references and offline OCR accuracy comparisons."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

from pipeline.discovery.crawler import read_catalog, CatalogError
from pipeline.download.downloader import recover, file_hash, DownloadError
from pipeline.extraction.extractor import command, utc_now, ExtractionError
from pipeline.ocr.ocr import select_input, load_settings, png_dimensions

FIELDS = ('sample_id', 'status', 'transcriber', 'verifier', 'content_type', 'equations_present', 'equations_checked', 'reference_sha256', 'notes')


def relative_file(root, value):
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError('Packet paths must be relative')
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Path escapes packet directory')
    return path


def load_packet(root, *, images=True):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 'ocr-reference-packet-1' or manifest.get('purpose') != 'ocr_evaluation':
        raise ValueError('Not an OCR evaluation packet')
    samples = manifest.get('samples')
    if not isinstance(samples, list) or not samples:
        raise ValueError('Empty reference packet')
    ids, documents = set(), {}
    artifact_paths = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('Invalid sample record')
        sid = sample.get('sample_id', '')
        if not re.fullmatch(r'LK-EDU-\d{6}_p\d{6}', sid) or sid in ids:
            raise ValueError('Invalid/duplicate sample ID')
        ids.add(sid)
        if sample.get('split') not in {'calibration', 'holdout'}:
            raise ValueError('Invalid reference split')
        digest = sample.get('raw_sha256', '')
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid raw provenance hash')
        if documents.setdefault(digest, sample['split']) != sample['split']:
            raise ValueError('Raw document crosses calibration/holdout splits')
        if type(sample.get('page_number')) is not int or sample['page_number'] < 1 or sid != f"{sample['doc_id']}_p{sample['page_number']:06d}":
            raise ValueError('Invalid page identity')
        if not re.fullmatch(r'[0-9a-f]{64}', sample.get('image_sha256', '')):
            raise ValueError('Invalid image hash')
        image = relative_file(root, sample['image_path'])
        reference = relative_file(root, sample['reference_path'])
        for artifact in (image, reference):
            if artifact in artifact_paths:
                raise ValueError('Duplicate packet artifact path')
            artifact_paths.add(artifact)
        if images and file_hash(image) != sample['image_sha256']:
            raise ValueError(f'Image checksum mismatch: {sid}')
    return manifest


def prepare(settings, destination, count=10):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing review packet')
    if type(count) is not int or count < 1:
        raise ValueError('count must be positive')
    rows = sorted((r for r in read_catalog(settings['catalog_path']) if r['status'] in {'DOWNLOADED', 'EXTRACTED'}), key=lambda r: r['doc_id'])
    documents = []
    seen_raw = set()
    for row in rows:
        if not row['sha256'] or row['sha256'] in seen_raw:
            continue
        bundle, manifest, pages = select_input(settings, row)
        flagged = [p for p in pages if p['ocr_required']]
        if flagged:
            recover({**row, 'status':'DOWNLOADED'}, settings['raw_root'])
            documents.append((row, flagged))
            seen_raw.add(row['sha256'])
    if not documents:
        raise ValueError('No flagged source pages available')
    # Round-robin coverage first, then middle/end pages, never duplicate raw pages.
    selected, used = [], set()
    ordered = []
    for row, pages in documents:
        numbers = list(dict.fromkeys([pages[0]['page_number'], pages[len(pages)//2]['page_number'], pages[-1]['page_number']] + [p['page_number'] for p in pages]))
        ordered.append((row, numbers))
    for index in range(max(len(numbers) for _, numbers in ordered)):
        for row, numbers in ordered:
            if index < len(numbers) and len(selected) < count:
                key = (row['sha256'], numbers[index])
                if key not in used:
                    selected.append((row, numbers[index]))
                    used.add(key)
    if len(selected) != count:
        raise ValueError(f'Only {len(selected)} unique pages available; requested {count}')
    holdout_docs = {row['sha256'] for row, _ in documents[-max(1, math.ceil(len(documents)*0.3)):]} if len(documents) > 1 else set()
    selected = [(row, page, {'split':'holdout' if row['sha256'] in holdout_docs else 'calibration'}) for row, page in selected]
    return render_packet(settings, destination, selected,
        sampling='document round-robin, first/middle/last pages',
        coverage_note='Current downloaded source sample; not representative of all subjects or printed/handwritten styles.')


def render_packet(settings, destination, selected, *, sampling, coverage_note):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing review packet')
    renderer = shutil.which('pdftoppm')
    if not renderer:
        raise ValueError('pdftoppm is required to prepare review images')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.reference-', dir=destination.parent))
    samples = []
    try:
        (temporary/'images').mkdir()
        (temporary/'references').mkdir()
        for row, number, metadata in selected:
            sid = f"{row['doc_id']}_p{number:06d}"
            pdf = settings['raw_root']/'pdf'/row['doc_id']/f"{row['sha256']}.pdf"
            content = command([renderer,'-f',str(number),'-l',str(number),'-singlefile','-r',str(settings['dpi']),'-scale-to',str(settings['max_image_side']),'-png',str(pdf)], timeout=settings['command_timeout_seconds'], maximum=settings['max_command_bytes'])
            png_dimensions(content)
            if file_hash(pdf) != row['sha256']:
                raise ValueError('Raw document changed during preparation')
            image = temporary/'images'/f'{sid}.png'
            image.write_bytes(content)
            (temporary/'references'/f'{sid}.txt').write_text('', encoding='utf-8')
            samples.append({'sample_id':sid,'doc_id':row['doc_id'],'raw_sha256':row['sha256'],'page_number':number,
                            'source_url':row['source_url'],'title':row['title'],**metadata,
                            'image_path':f'images/{sid}.png','image_sha256':file_hash(image),'reference_path':f'references/{sid}.txt'})
        manifest = {'schema_version':'ocr-reference-packet-1','purpose':'ocr_evaluation','created_at_utc':utc_now(),
                    'sampling':sampling,'coverage_note':coverage_note,
                    'catalog_sha256':file_hash(settings['catalog_path']),
                    'rendering':{'dpi':settings['dpi'],'max_image_side':settings['max_image_side']},'samples':samples}
        (temporary/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (temporary/'review.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
            for sample in samples:
                writer.writerow({**dict.fromkeys(FIELDS,''),'sample_id':sample['sample_id'],'status':'pending','content_type':'unknown','equations_present':'unknown','equations_checked':'false'})
        (temporary/'README.md').write_text('Reference pages for OCR evaluation only. See docs/OCR_ACCURACY_GUIDE.md in the repository. Reference files start empty; no human transcription or verification has occurred. Images are generated local artifacts; transfer this whole packet to Drive for Colab.\n',encoding='utf-8')
        temporary.rename(destination)
    finally:
        if temporary.exists(): shutil.rmtree(temporary)
    return {'packet_path':str(destination),'sample_count':len(samples),'verified_references':0}


def prepare_selection(settings, destination, selection_path):
    """Explicit public-source page selection, including PDFs with native text."""
    import yaml
    plan = yaml.safe_load(Path(selection_path).read_text(encoding='utf-8'))
    if not isinstance(plan, dict) or plan.get('schema_version') != 'ocr-selection-1':
        raise ValueError('Expected ocr-selection-1 plan')
    entries = plan.get('samples')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise ValueError('Select 1–32 source pages')
    catalog = {row['doc_id']:row for row in read_catalog(settings['catalog_path'])}
    selected, used, groups = [], set(), {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('doc_id') not in catalog:
            raise ValueError('Unknown selected document')
        row = catalog[entry['doc_id']]
        page, split = entry.get('page_number'), entry.get('split')
        if type(page) is not int or not 1 <= page <= 500 or split not in {'calibration','holdout'}:
            raise ValueError('Invalid selected page/split')
        if row['status'] not in {'DOWNLOADED','EXTRACTED'} or not row['sha256']:
            raise ValueError('Selected source has not been downloaded')
        key = (row['sha256'], page)
        if key in used or groups.setdefault(row['sha256'],split) != split:
            raise ValueError('Duplicate source page or document crossing splits')
        used.add(key)
        metadata = {'split':split, 'subject_group':entry.get('subject_group','unknown'),
                    'content_type_hint':entry.get('content_type_hint','unknown'),
                    'layout_tags':entry.get('layout_tags',[]), 'metadata_evidence':entry.get('metadata_evidence','pending source inspection')}
        if metadata['content_type_hint'] not in {'printed','handwritten','mixed','unknown'}:
            raise ValueError('Invalid content type hint')
        if any(not isinstance(metadata[k],str) or not metadata[k].strip() or len(metadata[k])>1000 for k in ('subject_group','metadata_evidence')):
            raise ValueError('Invalid source metadata')
        if not isinstance(metadata['layout_tags'],list) or len(metadata['layout_tags'])>10 or any(not isinstance(tag,str) or not tag.strip() or len(tag)>64 for tag in metadata['layout_tags']):
            raise ValueError('Invalid layout tags')
        recover({**row,'status':'DOWNLOADED'}, settings['raw_root'])
        selected.append((row,page,metadata))
    return render_packet(settings, destination, selected, sampling='explicit frozen source page selection',
        coverage_note=plan.get('coverage_note','Subject/style hints require human verification; missing strata must be reported.'))


def read_reviews(root, manifest):
    with (Path(root)/'review.csv').open(newline='',encoding='utf-8') as stream:
        reader=csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError('Invalid reference review columns')
        rows=list(reader)
    by_id={r['sample_id']:r for r in rows}
    if len(by_id)!=len(rows) or set(by_id)!={s['sample_id'] for s in manifest['samples']}:
        raise ValueError('Reference review IDs must match packet exactly')
    for sample in manifest['samples']:
        row=by_id[sample['sample_id']]
        if not relative_file(Path(root), sample['reference_path']).is_file():
            raise ValueError('Missing reference file')
        if None in row or any(v is None for v in row.values()) or row['status'] not in {'pending','verified','unreadable'}:
            raise ValueError('Malformed reference review row/status')
        if row['content_type'] not in {'unknown','printed','handwritten','mixed','blank'} or row['equations_present'] not in {'unknown','yes','no'} or row['equations_checked'] not in {'true','false'}:
            raise ValueError('Invalid content review fields')
        if row['status']=='verified':
            if not row['transcriber'].strip() or not row['verifier'].strip() or row['transcriber'].strip().casefold()==row['verifier'].strip().casefold():
                raise ValueError('Verified reference needs two different reviewers')
            text=relative_file(Path(root),sample['reference_path']).read_text(encoding='utf-8')
            if not text.strip() or '[UNREADABLE]' in text or row['content_type'] in {'unknown','blank'} or row['equations_present']=='unknown':
                raise ValueError('Verified reference needs readable, classified text')
            if row['equations_present']=='yes' and row['equations_checked']!='true':
                raise ValueError('Equations need explicit verification')
            if hashlib.sha256(text.encode()).hexdigest()!=row['reference_sha256']:
                raise ValueError('Reference changed since verification')
    return by_id


def approve(root,sample_id,transcriber,verifier,content_type,equations):
    """Explicit human CLI declaration; never called automatically by OCR."""
    root=Path(root);manifest=load_packet(root)
    rows=read_reviews(root,manifest)
    if sample_id not in rows: raise ValueError('Unknown sample')
    sample=next(s for s in manifest['samples'] if s['sample_id']==sample_id)
    row=rows[sample_id]
    text=relative_file(root,sample['reference_path']).read_text(encoding='utf-8')
    row.update(status='verified',transcriber=transcriber,verifier=verifier,content_type=content_type,equations_present=equations,
               equations_checked='true' if equations=='yes' else 'false',reference_sha256=hashlib.sha256(text.encode()).hexdigest())
    # Validate proposed review metadata before replacing the CSV.
    with tempfile.TemporaryDirectory(prefix='.approve-',dir=root) as folder:
        temporary=Path(folder)
        with (temporary/'review.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows.values())
        # References live at the same relative paths in the actual root.
        for s in manifest['samples']:
            target=relative_file(temporary,s['reference_path']);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(relative_file(root,s['reference_path']),target)
        read_reviews(temporary,manifest)
        (temporary/'review.csv').replace(root/'review.csv')
    return {'sample_id':sample_id,'status':'verified','reference_sha256':row['reference_sha256']}


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC',text).split())


def edit_distance(reference,prediction):
    # Two rows; memory linear in sequence length. CER counts Unicode codepoints.
    if len(reference)<len(prediction): reference,prediction=prediction,reference
    previous=list(range(len(prediction)+1))
    for i,a in enumerate(reference,1):
        current=[i]
        for j,b in enumerate(prediction,1):
            current.append(min(previous[j]+1,current[-1]+1,previous[j-1]+(a!=b)))
        previous=current
    return previous[-1]


def evaluate(root,prediction_dirs):
    root=Path(root);manifest=load_packet(root);reviews=read_reviews(root,manifest)
    verified=[s for s in manifest['samples'] if reviews[s['sample_id']]['status']=='verified']
    result={'schema_version':'ocr-accuracy-report-1','status':'pending_references' if not verified else 'measured',
            'verified_references':len(verified),'total_samples':len(manifest['samples']),
            'normalization':'NFC and whitespace folding; preserve case/punctuation/ZWJ/ZWNJ; codepoint CER',
            'models':[],'winner':None,'training_approved':False}
    seen_runs = set()
    for directory in prediction_dirs:
        directory=Path(directory);run=json.loads((directory/'run.json').read_text(encoding='utf-8'))
        if run.get('schema_version')!='neural-ocr-run-1' or run.get('packet_manifest_sha256')!=file_hash(root/'manifest.json'):
            raise ValueError('Prediction run does not match reference packet')
        if run['run_id'] in seen_runs:
            raise ValueError('Duplicate prediction run')
        seen_runs.add(run['run_id'])
        pages=[]
        outcomes={}
        predictions={}
        for sample in manifest['samples']:
            path=directory/f"{sample['sample_id']}.json"
            if not path.exists():
                outcomes['missing']=outcomes.get('missing',0)+1
                continue
            prediction=json.loads(path.read_text(encoding='utf-8'))
            if any(prediction.get(k)!=v for k,v in {'schema_version':'neural-ocr-prediction-1','sample_id':sample['sample_id'],'image_sha256':sample['image_sha256'],'run_id':run['run_id']}.items()):
                raise ValueError('Prediction/image/run identity mismatch')
            outcome=prediction.get('outcome','unknown')
            if not isinstance(outcome,str): raise ValueError('Invalid prediction outcome')
            outcomes[outcome]=outcomes.get(outcome,0)+1
            predictions[sample['sample_id']]=prediction
        for sample in verified:
            prediction=predictions.get(sample['sample_id'])
            if prediction is None:continue
            if prediction.get('outcome')!='predicted':continue
            text=prediction['text']
            if not isinstance(text,str) or len(text)>50000: raise ValueError('Invalid/oversized prediction text')
            reference=normalize(relative_file(root,sample['reference_path']).read_text(encoding='utf-8'))
            pred=normalize(text)
            pages.append({'sample_id':sample['sample_id'],'split':sample['split'],'content_type':reviews[sample['sample_id']]['content_type'],
                          'subject_group':sample.get('subject_group','unknown'),
                          'character_errors':edit_distance(reference,pred),'reference_characters':len(reference),
                          'word_errors':edit_distance(reference.split(),pred.split()),'reference_words':len(reference.split()),
                          'exact_match':reference==pred,'equations_present':reviews[sample['sample_id']]['equations_present']})
        metrics={}
        for split in ('calibration','holdout'):
            subset=[p for p in pages if p['split']==split]
            chars=sum(p['reference_characters'] for p in subset);words=sum(p['reference_words'] for p in subset)
            expected=sum(s['split']==split for s in verified)
            metrics[split]={'scored_pages':len(subset),'expected_verified_pages':expected,'coverage_complete':len(subset)==expected and expected>0,
                            'cer':sum(p['character_errors'] for p in subset)/chars if chars else None,
                            'wer':sum(p['word_errors'] for p in subset)/words if words else None}
        breakdowns={}
        for field in ('subject_group','content_type'):
            breakdowns[field]={}
            for label in sorted({p[field] for p in pages}):
                subset=[p for p in pages if p[field]==label]
                chars=sum(p['reference_characters'] for p in subset)
                words=sum(p['reference_words'] for p in subset)
                breakdowns[field][label]={'scored_pages':len(subset),
                    'cer':sum(p['character_errors'] for p in subset)/chars if chars else None,
                    'wer':sum(p['word_errors'] for p in subset)/words if words else None}
        result['models'].append({'backend':run['backend'],'run_id':run['run_id'],
            'run_status':run.get('status','unknown'),'outcomes':outcomes,
            'metrics':metrics,'breakdowns':breakdowns,'pages':pages})
    result['comparison_complete']=len(verified)==len(manifest['samples']) and len({m['backend'] for m in result['models']})>=2 and {s['split'] for s in verified} == {'calibration','holdout'} and all(m['run_status']=='finished' and len(m['pages'])==len(verified) for m in result['models'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--config',type=Path,default=Path('configs/pipeline.yaml'));p.add_argument('--output',type=Path,required=True);p.add_argument('--count',type=int,default=10);p.add_argument('--selection',type=Path,help='Explicit page selection YAML; includes native-text PDFs')
    p=sub.add_parser('status');p.add_argument('packet',type=Path);p.add_argument('--metadata-only',action='store_true')
    p=sub.add_parser('approve');p.add_argument('packet',type=Path);p.add_argument('--sample-id',required=True);p.add_argument('--transcriber',required=True);p.add_argument('--verifier',required=True);p.add_argument('--content-type',choices=('printed','handwritten','mixed'),required=True);p.add_argument('--equations',choices=('yes','no'),required=True)
    p=sub.add_parser('evaluate');p.add_argument('packet',type=Path);p.add_argument('--predictions',type=Path,action='append',required=True)
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            settings = load_settings(args.config)
            result = prepare_selection(settings,args.output,args.selection) if args.selection else prepare(settings,args.output,args.count)
        elif args.action=='approve':result=approve(args.packet,args.sample_id,args.transcriber,args.verifier,args.content_type,args.equations)
        elif args.action=='evaluate':result=evaluate(args.packet,args.predictions)
        else:
            manifest=load_packet(args.packet,images=not args.metadata_only);rows=read_reviews(args.packet,manifest)
            result={'status':'ready' if all(r['status']=='verified' for r in rows.values()) else 'pending_references','samples':len(rows),'verified':sum(r['status']=='verified' for r in rows.values()),'training_approved':False}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError,CatalogError,DownloadError,ExtractionError) as exc:parser.exit(2,f'Reference review error: {exc}\n')

if __name__=='__main__':raise SystemExit(main())
