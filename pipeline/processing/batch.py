"""Bounded collection/processing orchestration with isolated OCR child processes."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import yaml

from pipeline.discovery.crawler import ROOT, read_catalog, _catalog_lock
from pipeline.download import downloader
from pipeline.extraction import extractor
from pipeline.processing import pages
from pipeline.dataset.native import encode
from pipeline.download.downloader import file_hash


def child(command, config, doc_ids, sources_path, progress):
    """OCR blocks sockets inside its process; collection remains a separate process."""
    args = [sys.executable, '-B', '-m', 'pipeline.workflow', command, '--config', str(config),
            '--progress', progress]
    if command == 'collect': args.extend(['--sources', str(sources_path)])
    for doc_id in doc_ids: args.extend(['--doc-id', doc_id])
    process = subprocess.Popen(args, cwd=ROOT, text=True, stdout=subprocess.PIPE)
    try:
        stdout, _ = process.communicate()
    except BaseException:
        process.terminate()
        try: process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
        raise
    try:
        result = json.loads(stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f'{command} returned no valid JSON (exit {process.returncode})') from exc
    if not isinstance(result, dict) or process.returncode not in (0, 1):
        raise RuntimeError(f'{command} setup failed (exit {process.returncode})')
    return {**result, 'child_exit_code': process.returncode}


def run(config_path, *, sources_path=None, source_id=None, doc_ids=None,
        max_batches=3, max_download_jobs=5, max_new_pages=20, dry_run=False,
        progress_mode='auto', stage_runner=None):
    for value in (max_batches, max_download_jobs, max_new_pages):
        if type(value) is not int or value < 1:
            raise ValueError('Batch, download-job and new-page limits must be positive integers')
    config_path = Path(config_path).resolve()
    sources_path = Path(sources_path or config_path.parent / 'sources.yaml').resolve()
    download = downloader.load_settings(config_path)
    processing = pages.load_settings(config_path)
    extraction = extractor.load_settings(config_path)
    for stage in (processing, extraction):
        if stage['catalog_path'].resolve() != download['catalog_path'].resolve() or stage['raw_root'].resolve() != download['raw_root'].resolve():
            raise ValueError('Batch stages require the same catalog and raw root')
    sources = downloader.load_sources(sources_path)
    selected_source = next((source for source in sources if source['id'] == source_id), None)
    if source_id and selected_source is None: raise ValueError('Unknown source')
    rows = read_catalog(download['catalog_path'])
    if doc_ids and set(doc_ids) - {row['doc_id'] for row in rows}: raise ValueError('Unknown document ID')
    def scoped(rows):
        return [row for row in rows if (not doc_ids or row['doc_id'] in doc_ids)
                and (not selected_source or row['source'] == selected_source['name'])]
    def downloadable(rows, attempted, remaining):
        fresh = [row['doc_id'] for row in scoped(rows)
                 if row['status'] in {'DISCOVERED', 'DOWNLOAD_FAILED'} and row['doc_id'] not in attempted]
        if not fresh or remaining < 1: return []
        jobs, _ = downloader.plan_downloads(rows, sources, source_id=source_id, doc_ids=fresh,
                                            maximum=min(download['max_documents'], remaining))
        return [row['doc_id'] for row, _ in jobs]
    def processable(rows, failed):
        return [row['doc_id'] for row in scoped(rows) if row['doc_id'] not in failed
                and row['status'] in {'DOWNLOADED', 'EXTRACTED'} and row['sha256']
                and row['local_filename'].lower().endswith(('.pdf', '.html'))]
    result = {'schema_version': 'corpus-batch-run-1', 'dry_run': dry_run,
              'limits': {'max_batches': max_batches, 'max_download_jobs': max_download_jobs, 'max_new_pages': max_new_pages},
              'download_jobs_reserved': 0, 'new_pages': 0, 'batches': [], 'errors': [],
              'stop_reason': 'not_started', 'training_approved': False,
              'note': 'Raw OCR remains provisional. This runner does not approve text or export a training release.'}
    if dry_run:
        return {**result, 'download_planned': downloadable(rows, set(), max_download_jobs),
                'processing_planned': processable(rows, set()), 'stop_reason': 'dry_run',
                'preview_note': 'Current eligibility only; future processing depends on successful downloads. No network/model/filesystem writes.'}
    stage_runner = stage_runner or child
    run_id = f"batch_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}"
    folder = processing['log_root'].parent / 'batch' / run_id
    attempted, failed_docs, bundles = set(), set(), set()
    base_config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    def checkpoint():
        temporary = folder / 'run.json.tmp'
        temporary.write_bytes(encode(result)); temporary.replace(folder / 'run.json')
    with _catalog_lock(download['catalog_path'].with_name('batch-worker'), 0):
        folder.mkdir(parents=True, exist_ok=False)
        frozen_sources = folder / 'sources.yaml'
        frozen_sources.write_bytes(sources_path.read_bytes())
        result.update(run_id=run_id, report_path=str(folder / 'run.json'))
        result['source_config_sha256'] = file_hash(frozen_sources)
        checkpoint()
        try:
            for number in range(1, max_batches + 1):
                if result['new_pages'] >= max_new_pages:
                    result['stop_reason'] = 'new_page_limit'; break
                rows = read_catalog(download['catalog_path'])
                ids = downloadable(rows, attempted, max_download_jobs - result['download_jobs_reserved'])
                cycle = {'batch': number, 'download_selected': ids, 'collect': None, 'process': None}
                result['batches'].append(cycle)
                phase_config = json.loads(json.dumps(base_config))
                phase_config['processing']['max_pages'] = min(processing['max_pages'], max_new_pages - result['new_pages'])
                phase_config['download']['max_documents'] = max(1, len(ids))
                snapshot = folder / f'config_{number:03d}.yaml'
                snapshot.write_text(yaml.safe_dump(phase_config, allow_unicode=True, sort_keys=False), encoding='utf-8')
                cycle['config_snapshot'] = str(snapshot)
                if ids:
                    attempted.update(ids); result['download_jobs_reserved'] += len(ids)
                    result['active_phase'] = 'collect'; checkpoint()
                    cycle['collect'] = stage_runner('collect', snapshot, ids, frozen_sources, progress_mode)
                    for row in cycle['collect'].get('results', []):
                        if row.get('outcome') in {'failed', 'catalog_conflict'}:
                            result['errors'].append({'stage': 'collect', **row})
                ids_to_process = processable(read_catalog(download['catalog_path']), failed_docs)
                if ids_to_process:
                    result['active_phase'] = 'process'; checkpoint()
                    cycle['process'] = stage_runner('process', snapshot, ids_to_process, frozen_sources, progress_mode)
                    for error in cycle['process'].get('errors', []):
                        failed_docs.add(error['doc_id']); result['errors'].append({'stage': 'process', **error})
                    for row in cycle['process'].get('results', []):
                        if row.get('bundle'): bundles.add(row['bundle'])
                        if row.get('outcome') in {'predicted', 'truncated', 'failed'} and row.get('bundle'):
                            result['new_pages'] += 1
                        if row.get('outcome') == 'failed': result['errors'].append({'stage': 'process', **row})
                result['processed_bundles'] = sorted(bundles)
                checkpoint()
                process_report = cycle['process'] or {}
                if result['new_pages'] >= max_new_pages:
                    result['stop_reason'] = 'new_page_limit'; break
                next_download = downloadable(read_catalog(download['catalog_path']), attempted,
                                               max_download_jobs - result['download_jobs_reserved'])
                process_pending = process_report.get('stop_reason', '').startswith('batch_')
                if not next_download and not process_pending:
                    result['stop_reason'] = 'selected_work_finished' if result['download_jobs_reserved'] < max_download_jobs else 'download_job_limit'
                    break
                if not ids and not process_report.get('results') and not process_report.get('errors'):
                    result['stop_reason'] = 'no_progress'; break
            else: result['stop_reason'] = 'batch_limit'
        except BaseException as exc:
            result['stop_reason'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'stage_failed'
            result['errors'].append({'stage': result.get('active_phase'), 'error': str(exc)})
            raise
        finally:
            result['active_phase'] = 'finished'
            result['outcomes'] = dict(Counter(row.get('outcome', 'unknown') for cycle in result['batches']
                                               for row in (cycle['process'] or {}).get('results', [])))
            checkpoint()
    return result
