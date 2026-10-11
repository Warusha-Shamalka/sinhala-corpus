"""Extract four already-downloaded printed pilot PDFs; never download or update catalogs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.discovery.crawler import read_catalog
from pipeline.extraction.extractor import PopplerBackend, extract_document, load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Default is a read-only plan')
    args = parser.parse_args()
    settings = load_settings(ROOT / 'configs/ocr_broad_pipeline.yaml')
    selected = {'LK-EDU-000264', 'LK-EDU-000490', 'LK-EDU-000491', 'LK-EDU-000492'}
    rows = [r for r in read_catalog(ROOT / 'configs/ocr_broad_sources.csv') if r['doc_id'] in selected]
    if not args.execute:
        print(json.dumps({'planned': sorted(selected), 'output_root': str(settings['output_root']),
                          'catalog_updates': False}, indent=2))
        return
    backend = PopplerBackend(settings)
    results = []
    for row in rows:
        receipts = list((settings['raw_root'] / 'pdf' / row['doc_id']).glob('*.json'))
        if len(receipts) != 1:
            raise ValueError(f"Expected one downloaded version for {row['doc_id']}; prepare the broad source downloads first")
        receipt = json.loads(receipts[0].read_text())
        job = {**row, 'status': 'DOWNLOADED', 'sha256': receipt['sha256'], 'local_filename': receipt['local_filename']}
        print(f"Extracting {row['doc_id']} locally", file=sys.stderr, flush=True)
        manifest, folder, reused = extract_document(job, settings, backend)
        results.append({'doc_id': row['doc_id'], 'page_count': manifest['page_count'],
                        'ocr_pages': manifest['ocr_pages'], 'bundle': str(folder), 'reused': reused})
    print(json.dumps({'results': results, 'catalog_updates': False}, indent=2))


if __name__ == '__main__':
    main()
