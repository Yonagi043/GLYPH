import csv, json, unittest, hashlib
from pathlib import Path
import re
from PIL import Image
ROOT=Path(__file__).parents[1]
RUNS=ROOT/'data/processed/visual_features_v1/runs'


def current_run():
    manifest_hash = hashlib.sha256((ROOT/'data/processed/visual_features_v1/manifest.csv').read_bytes()).hexdigest()
    candidates = []
    for path in RUNS.glob('render_*'):
        # Sensitivity runs append canvas/threshold suffixes; only the canonical
        # 16-hex run id is the primary run for the frozen manifest.
        if not re.fullmatch(r'render_[0-9a-f]{16}', path.name):
            continue
        manifest = path/'run_manifest.json'
        if manifest.exists() and json.loads(manifest.read_text()).get('manifest_sha256') == manifest_hash:
            candidates.append(path)
    if not candidates:
        raise AssertionError('no primary run found for current manifest')
    # Historical runs remain for auditability.  The newest immutable run is
    # the one under test; sensitivity directories are excluded above.
    return max(candidates, key=lambda path: json.loads((path/'run_manifest.json').read_text()).get('created_at', ''))


class MeasurementContractTest(unittest.TestCase):
    def test_full_condition_matrix_is_frozen(self):
        with open(ROOT/'data/processed/visual_features_v1/manifest.csv', encoding='utf-8') as fh: rows=list(csv.DictReader(fh))
        self.assertEqual(len(rows),140)
        self.assertEqual(len({r['stimulus_id'] for r in rows}),140)
        self.assertEqual({r['script_code_iso15924'] for r in rows},{'Latn','Hani','Kana','Hang'})

    def test_fixture_outputs_exist(self):
        run=current_run(); payload=json.loads((run/'render_results.json').read_text())
        passed=[r for r in payload['results'] if r.get('status')=='passed']; self.assertTrue(passed)
        for row in passed:
            with Image.open(row['gray_path']) as image: self.assertEqual(image.size,(2048,1024))
            with Image.open(row['mask_path']) as image: self.assertEqual(image.mode,'L')
    def test_feature_contract_has_two_representations(self):
        with open(current_run()/'visual_features.csv', encoding='utf-8') as fh: rows=list(csv.DictReader(fh))
        self.assertTrue({'raster_binary','raster_grayscale'} <= {r['representation'] for r in rows})
        self.assertTrue(all(r['feature_definition_version']=='1.1.0' for r in rows))

    def test_current_protocol_has_no_failed_records(self):
        run=current_run()
        payload=json.loads((run/'render_results.json').read_text())
        failed=[r for r in payload['results'] if r.get('status')!='passed']
        self.assertFalse(failed)
        with open(run/'missing_records.csv', encoding='utf-8') as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), len(failed))
