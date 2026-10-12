"""Recreate the isolated broad-pilot downloads from frozen public-source metadata.

Run from the repository root. No production catalog mutations. Network is only
used with --download; the default emits a downloader plan.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.download.downloader import load_settings, load_sources, run
from pipeline.discovery.crawler import read_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    settings = load_settings(ROOT/'configs/ocr_broad_pipeline.yaml')
    seed = ROOT/'configs/ocr_broad_sources.csv'
    catalog = settings['catalog_path']
    if catalog == (ROOT/'corpus/catalog/documents.csv').resolve():
        raise ValueError('An isolated catalog is required')
    catalog.parent.mkdir(parents=True, exist_ok=True)
    if not catalog.exists():
        shutil.copyfile(seed, catalog)
    seed_rows = read_catalog(seed)
    existing = {r['doc_id']:r for r in read_catalog(catalog)}
    for row in seed_rows:
        if row['doc_id'] not in existing or existing[row['doc_id']]['source_url'] != row['source_url']:
            raise ValueError('Experiment catalog disagrees with frozen source identities')
    ids = [r['doc_id'] for r in seed_rows]
    report = run(settings, load_sources(ROOT/'configs/sources.yaml'), doc_ids=ids,
                 dry_run=not args.download, progress_mode='plain')
    report_path = catalog.parent/('download_report.json' if args.download else 'download_plan.json')
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
