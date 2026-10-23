"""Import one local image with explicit source provenance into the production store."""
import csv
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from pipeline.dataset.native import digest, encode, publish
from pipeline.discovery.crawler import (_catalog_lock, _read_catalog, _validate_rows,
                                        make_doc_id, next_document_number)
from pipeline.discovery.filters import normalize_url
from pipeline.download.downloader import artifact_name, file_hash, recover, sync_directory, utc_now
from pipeline.ocr.images import decode


def import_image(settings, sources, image, source_id, source_url, title, *, dry_run=False):
    """One image is one catalog document/page. Reimporting the same source is idempotent."""
    image = Path(image)
    source = next((s for s in sources if s['id'] == source_id), None)
    if not source or not source['enabled'] or not source['verified']:
        raise ValueError('Select an enabled, verified source ID')
    url = normalize_url(source_url)
    allowed = {urlsplit(source['base_url']).hostname, *source.get('resource_hosts', [])}
    if not url or urlsplit(url).hostname not in allowed:
        raise ValueError('Image source URL must belong to the approved source or resource hosts')
    if not isinstance(title, str) or not title.strip(): raise ValueError('Image title is required')
    if not image.is_file() or not 0 < image.stat().st_size <= settings['max_image_bytes']:
        raise ValueError('Missing, empty or oversized image')
    content = image.read_bytes()
    if len(content) > settings['max_image_bytes']: raise ValueError('Image exceeds byte limit')
    page, kind = decode(content, settings.get('max_input_pixels', 40_000_000))
    size = list(page.size); page.close()
    sha = digest(content)
    if dry_run:
        return {'dry_run': True, 'format': kind, 'bytes': len(content), 'sha256': sha,
                'image_dimensions': size, 'source_url': url, 'catalog_written': False}
    catalog, raw_root = settings['catalog_path'], settings['raw_root']
    with _catalog_lock(catalog, 10):
        fields, rows = _read_catalog(catalog)
        row = next((r for r in rows if normalize_url(r['source_url']) == url), None)
        if row and (row['source'] != source['name'] or row['title'] != title.strip()):
            raise ValueError('Existing source URL has conflicting title/source metadata')
        if row and row['sha256']:
            if row['sha256'] != sha: raise ValueError('Source URL already has a different raw artifact; use a distinct source identity')
            receipt = recover({**row, 'status': 'DOWNLOADED'}, raw_root)
            return {'doc_id': row['doc_id'], 'outcome': 'verified_existing', 'sha256': receipt['sha256']}
        if row is None:
            row = dict.fromkeys(fields, '')
            row.update(doc_id=make_doc_id(next_document_number(rows)), title=title.strip(), source=source['name'],
                       source_url=url, status='DISCOVERED', document_type='other')
            rows.append(row)
        folder = raw_root / kind / row['doc_id']
        artifact = folder / f'{sha}.{kind}'
        receipt = {'schema_version': 'raw-download-1', 'acquisition_method': 'local_image_import',
                   'doc_id': row['doc_id'], 'source_id': source_id, 'requested_url': url,
                   'format': kind, 'bytes': len(content), 'sha256': sha,
                   'artifact_path': str(artifact.relative_to(raw_root)), 'local_filename': artifact_name(artifact),
                   'completed_at_utc': utc_now(), 'pipeline_version': 'image-import-1',
                   'image_dimensions': size, 'import_filename': image.name}
        if folder.exists():
            # Recovery after raw publication succeeded but catalog replacement did not.
            recovered = recover({**row, 'status': 'DOWNLOADED', 'sha256': sha,
                                 'local_filename': artifact_name(artifact)}, raw_root)
            if recovered.get('acquisition_method') != 'local_image_import': raise ValueError('Conflicting raw receipt')
            receipt = recovered
        else:
            publish(folder, {artifact.name: content, f'{sha}.json': encode(receipt)})
        if file_hash(image) != sha: raise ValueError('Input image changed during import')
        row.update(status='DOWNLOADED', sha256=sha, local_filename=receipt['local_filename'],
                   page_count='1', ocr_required='true', pipeline_version='image-import-1',
                   last_processed=utc_now(), error='')
        _validate_rows(rows, allow_pilots=True)
        fd, name = tempfile.mkstemp(prefix='.image-catalog-', suffix='.tmp', dir=catalog.parent)
        try:
            with os.fdopen(fd, 'w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader(); writer.writerows(rows); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, catalog); sync_directory(catalog.parent)
        finally:
            Path(name).unlink(missing_ok=True)
    return {'doc_id': row['doc_id'], 'outcome': 'imported', 'sha256': sha, 'local_filename': receipt['local_filename']}
