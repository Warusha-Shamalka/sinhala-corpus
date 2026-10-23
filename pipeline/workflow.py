"""Persistent corpus setup and stage commands; human review precedes every release."""
import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path

import yaml

from pipeline.discovery.crawler import ROOT, read_catalog
from pipeline.download import downloader
from pipeline.extraction import extractor
from pipeline.processing import pages
from pipeline.processing import batch
from pipeline.dataset import reviewed, provisional, daily
from pipeline.quality import corpus as corpus_quality
from pipeline.dataset.native import encode, digest, publish, visible_manifests


def initialize(store, seed):
    store = store.resolve()
    rows = read_catalog(seed)
    # A new deployment has no downloaded artifacts. Preserve the original catalog
    # verbatim as evidence; do not misrepresent old laptop paths as Drive downloads.
    reset = []
    for row in rows:
        if row['status'] != 'DISCOVERED': reset.append(row['doc_id'])
        row.update(status='DISCOVERED', **{k: '' for k in ('local_filename', 'sha256', 'extraction_method', 'ocr_required',
                                                         'page_count', 'quality_score', 'pipeline_version', 'last_processed', 'error')})
    stream = io.StringIO(newline='')
    if not rows: raise ValueError('Empty seed catalog')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    config = yaml.safe_load((ROOT / 'configs/pipeline.yaml').read_text())
    for section in ('download', 'extraction', 'ocr', 'processing'):
        data = config[section]
        data['catalog_path'] = str(store / 'corpus/catalog/documents.csv')
        data['raw_root'] = str(store / 'corpus/raw')
        data['log_root'] = str(store / 'corpus/logs' / section)
    config['download']['accepted_formats'] = ['pdf', 'html']
    config['extraction']['output_root'] = str(store / 'corpus/extracted/pages')
    config['ocr']['extraction_root'] = config['extraction']['output_root']
    config['ocr']['output_root'] = str(store / 'corpus/extracted/tesseract')
    config['processing']['output_root'] = str(store / 'corpus/extracted/processed')
    files = {'corpus/catalog/documents.csv': stream.getvalue().encode(), 'corpus/catalog/seed.csv': seed.read_bytes(),
             'configs/pipeline.yaml': yaml.safe_dump(config, sort_keys=False, allow_unicode=True).encode(),
             'configs/sources.yaml': (ROOT / 'configs/sources.yaml').read_bytes(),
             'configs/subjects.yaml': (ROOT / 'configs/subjects.yaml').read_bytes()}
    files['initialization.json'] = encode({'schema_version': 'corpus-store-1', 'seed_sha256': digest(seed.read_bytes()),
                                          'reset_for_new_store': reset, 'output_sha256': {k: digest(v) for k, v in files.items()}})
    publish(store, files)
    return {'store': str(store), 'config': str(store / 'configs/pipeline.yaml'), 'seed_rows': len(rows),
            'reset_for_new_store': len(reset), 'raw_files_copied': 0}


def status(config_path):
    settings = pages.load_settings(config_path)
    catalog = read_catalog(settings['catalog_path'])
    processed, errors = [], []
    for path in visible_manifests(settings['output_root']):
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            processed.append(pages.verify_page(path.parent, manifest['identity']))
        except Exception as exc:
            errors.append({'path': str(path), 'error': str(exc)})
    return {'catalog_states': dict(Counter(r['status'] for r in catalog)), 'processed_versions': len(processed),
            'methods': dict(Counter(r['method'] for r in processed)),
            'quality_flags': dict(Counter(f for r in processed for f in r['quality_flags'])),
            'artifact_errors': errors, 'ocr_backend': settings['ocr']['backend'],
            'model_setup_required': not bool(settings['ocr'].get('revision')),
            'note': 'Page artifacts are pending review; catalog download status is not training approval.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--store', type=Path, required=True)
    init.add_argument('--seed', type=Path, default=ROOT / 'corpus/catalog/documents.csv')
    for name in ('collect', 'process', 'status', 'prepare-review'):
        stage = commands.add_parser(name)
        stage.add_argument('--config', type=Path, default=ROOT / 'configs/pipeline.yaml')
        if name in {'collect', 'process'}:
            stage.add_argument('--doc-id', action='append', dest='doc_ids')
            stage.add_argument('--dry-run', action='store_true')
            stage.add_argument('--progress', choices=['auto', 'plain', 'off'], default='auto')
        if name == 'collect':
            stage.add_argument('--sources', type=Path, help='Defaults to sources.yaml beside the pipeline config')
            stage.add_argument('--source')
        if name == 'process':
            stage.add_argument('--page-number', action='append', type=int, dest='page_numbers')
            stage.add_argument('--retry-incomplete', action='store_true')
            stage.add_argument('--until-done', action='store_true', help='Continue through all eligible pages without batch caps')
        if name == 'prepare-review':
            stage.add_argument('--output', type=Path, required=True)
            stage.add_argument('--config-hash')
    export = commands.add_parser('export')
    export.add_argument('--packet', type=Path, required=True); export.add_argument('--output', type=Path, required=True)
    image_import = commands.add_parser('import-image', help='Register a local PNG/JPEG with explicit source provenance')
    image_import.add_argument('--config', type=Path, default=ROOT / 'configs/pipeline.yaml')
    image_import.add_argument('--sources', type=Path)
    image_import.add_argument('--image', type=Path, required=True)
    image_import.add_argument('--source', required=True, help='Configured source ID')
    image_import.add_argument('--source-url', required=True)
    image_import.add_argument('--title', required=True)
    image_import.add_argument('--dry-run', action='store_true')
    verify = commands.add_parser('verify-release')
    verify.add_argument('--root', type=Path, required=True)
    quality = commands.add_parser('quality')
    quality.add_argument('--packet', type=Path, required=True)
    quality.add_argument('--output', type=Path, help='Optional immutable report folder outside the packet')
    quality.add_argument('--max-metric-cells', type=int, default=1_000_000)
    quality.add_argument('--total-metric-cells', type=int, default=5_000_000)
    quality.add_argument('--max-dedup-pages', type=int, default=1000)
    quality.add_argument('--require-exportable', action='store_true',
                         help='Exit 1 for preflight blockers; this does not certify OCR accuracy')
    run = commands.add_parser('run', help='Bounded collect/process batches; does not approve or export training text')
    run.add_argument('--config', type=Path, default=ROOT / 'configs/pipeline.yaml')
    run.add_argument('--sources', type=Path)
    run.add_argument('--source')
    run.add_argument('--doc-id', action='append', dest='doc_ids')
    run.add_argument('--max-batches', type=int, default=3)
    run.add_argument('--max-download-jobs', type=int, default=5)
    run.add_argument('--max-new-pages', type=int, default=20)
    run.add_argument('--dry-run', action='store_true')
    run.add_argument('--progress', choices=['auto', 'plain', 'off'], default='auto')
    provisional_export = commands.add_parser('provisional', help='Export an explicitly unreviewed corpus text snapshot')
    provisional_export.add_argument('--run-report', type=Path, required=True)
    provisional_export.add_argument('--output', type=Path, required=True)
    release = commands.add_parser('daily-release', help='Cumulative/delta experimental text candidates for training handoff')
    release.add_argument('--provisional', type=Path, action='append', default=[])
    release.add_argument('--reviewed', type=Path, action='append', default=[])
    release.add_argument('--previous', type=Path)
    release.add_argument('--output', type=Path, required=True)
    release.add_argument('--validation-percent', type=int, default=10)
    release.add_argument('--split-seed', default='sinhala-corpus-v1')
    release.add_argument('--max-candidates', type=int, default=5000)
    release.add_argument('--replace-existing', action='store_true', help='Explicitly replace changed provisional page text and record the change')
    daily_verify = commands.add_parser('verify-daily-release')
    daily_verify.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init': result = initialize(args.store, args.seed)
        elif args.command == 'import-image':
            from pipeline.processing.import_image import import_image
            result = import_image(pages.load_settings(args.config),
                                  downloader.load_sources(args.sources or args.config.parent / 'sources.yaml'),
                                  args.image, args.source, args.source_url, args.title, dry_run=args.dry_run)
        elif args.command == 'status': result = status(args.config)
        elif args.command == 'collect':
            result = downloader.run(downloader.load_settings(args.config), downloader.load_sources(args.sources or args.config.parent / 'sources.yaml'),
                                    source_id=args.source, doc_ids=args.doc_ids, dry_run=args.dry_run, progress_mode=args.progress)
        elif args.command == 'process':
            result = pages.run(pages.load_settings(args.config), extractor.load_settings(args.config), doc_ids=args.doc_ids,
                               page_numbers=args.page_numbers,
                               dry_run=args.dry_run, progress_mode=args.progress, retry_incomplete=args.retry_incomplete,
                               until_done=args.until_done)
        elif args.command == 'prepare-review':
            result = reviewed.prepare(pages.load_settings(args.config)['output_root'], args.output, args.config_hash)
        elif args.command == 'verify-release': result = reviewed.verify_release(args.root)
        elif args.command == 'quality':
            limits = {'max_metric_cells': args.max_metric_cells, 'total_metric_cells': args.total_metric_cells,
                      'max_dedup_pages': args.max_dedup_pages}
            result = corpus_quality.write(args.packet, args.output, **limits) if args.output else corpus_quality.report(args.packet, **limits)
        elif args.command == 'run':
            result = batch.run(args.config, sources_path=args.sources, source_id=args.source, doc_ids=args.doc_ids,
                               max_batches=args.max_batches, max_download_jobs=args.max_download_jobs,
                               max_new_pages=args.max_new_pages, dry_run=args.dry_run, progress_mode=args.progress)
        elif args.command == 'provisional': result = provisional.export(args.run_report, args.output)
        elif args.command == 'daily-release':
            result = daily.build(args.output, provisional_roots=args.provisional, reviewed_roots=args.reviewed,
                                 previous=args.previous, policy={'validation_percent': args.validation_percent,
                                 'split_seed': args.split_seed, 'max_candidates': args.max_candidates}, replace_existing=args.replace_existing)
        elif args.command == 'verify-daily-release': result = daily.verify(args.root)
        else: result = reviewed.export(args.packet, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        failed = bool(pages.has_failures(result) or result.get('artifact_errors') or any(r.get('outcome') == 'catalog_conflict' for r in result.get('results', [])))
        if args.command == 'quality' and args.require_exportable:
            failed = failed or result['export_preflight']['status'] != 'checks_passed'
        return int(failed)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        parser.exit(2, f'Corpus workflow error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
