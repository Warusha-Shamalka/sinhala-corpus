import csv
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.dataset import pair_index


class PairIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def rows(self, changes=None):
        base = {f: '' for f in pair_index.FIELDS}
        base.update(exam='AL', subject='Physics', year='2020', language='si', metadata_status='unverified')
        rows = [{**base, 'doc_id': 'P', 'role': 'paper'}, {**base, 'doc_id': 'K', 'role': 'key'}]
        if changes: rows[1].update(changes)
        return rows

    def suggest(self, rows):
        path = self.root / 'index.csv'
        with path.open('w', newline='') as f:
            w=csv.DictWriter(f,fieldnames=pair_index.FIELDS); w.writeheader(); w.writerows(rows)
        pair_index.suggest(path, self.root / 'result')
        return [json.loads(s) for s in (self.root / 'result/suggestions.jsonl').read_text().splitlines()]

    def test_partial_matches_remain_unapproved(self):
        result = self.suggest(self.rows())[0]
        self.assertFalse(result['pairing_verified']); self.assertTrue(result['review_required'])
        self.assertIn('variant',result['missing_fields'])

    def test_conflicting_year_does_not_match(self):
        self.assertEqual(self.suggest(self.rows({'year':'2021'})), [])

    def test_multiple_keys_are_ambiguous(self):
        rows=self.rows(); rows.append({**rows[1], 'doc_id':'K2'})
        self.assertTrue(all(r['ambiguous'] for r in self.suggest(rows)))

    def test_unresolved_compilations_never_match_by_year(self):
        rows=self.rows(); rows[0]['collection_id']='UNRESOLVED'
        self.assertEqual(self.suggest(rows), [])

    def test_catalog_hints_are_not_approved_and_multiple_years_are_unknown(self):
        path=self.root/'catalog.csv'
        rows=[{'doc_id':'P','title':'Pesuru AL Physics past paper 2018 2020','document_type':'past_paper'},
              {'doc_id':'K','title':'AL Physics marking scheme 2020','document_type':'other'}]
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        pair_index.prepare(path,self.root/'index')
        with (self.root/'index/documents.csv').open() as f: output=list(csv.DictReader(f))
        self.assertEqual(output[0]['year'],''); self.assertEqual(output[0]['collection_id'],'UNRESOLVED')
        self.assertEqual(output[1]['role'],'key')
        self.assertTrue(all(r['metadata_status']=='unverified' for r in output))

    def test_subject_and_medium_hints_are_separate_and_conflicts_stay_unknown(self):
        path=self.root/'catalog.csv'
        rows=[{'doc_id':'P','title':'2020 AL Physics paper I Sinhala Medium','document_type':'past_paper','subject':''},
              {'doc_id':'K','title':'2020 AL Physics answer key Sinhala Medium','document_type':'marking_scheme','subject':'Biology'}]
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        pair_index.prepare(path,self.root/'index')
        with (self.root/'index/documents.csv').open() as f: output=list(csv.DictReader(f))
        self.assertEqual(output[0]['subject'],'Physics'); self.assertEqual(output[0]['language'],'si')
        self.assertEqual(output[0]['paper_number'],'1'); self.assertEqual(output[1]['subject'],'')
