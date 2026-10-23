from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from pipeline.ocr import backends
from pipeline.ocr import surya_backend


class BackendSelectionTests(unittest.TestCase):
    def test_surya_factory_passes_local_snapshot_without_changing_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            selection = {'backend': 'surya', 'model_path': folder, 'revision': 'a' * 64, 'max_page_seconds': 90}
            with patch.object(surya_backend, 'block_network') as guard, patch.object(surya_backend, 'SuryaBackend') as adapter:
                self.assertEqual(backends.create(selection), adapter.return_value)
                adapter.assert_called_once_with(Path(folder), 'a' * 64, 90, columns=1)
                guard.assert_called_once()

    def test_different_backend_snapshot_is_hashed_and_revision_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'models--Qwen--Qwen2.5-VL-3B-Instruct' / 'snapshots' / ('b' * 40)
            root.mkdir(parents=True)
            (root / 'model.safetensors').write_bytes(b'fixture weights')
            (root / 'processor_config.json').write_text('{}')
            selection = {'backend': 'qwen', 'model_path': root, 'revision': 'b' * 40}
            engine = types.SimpleNamespace(identity={})
            with patch.object(surya_backend, 'block_network'), patch.object(backends, 'GPUBackend', return_value=engine) as adapter:
                self.assertEqual(backends.create(selection), engine)
                self.assertEqual(set(engine.identity['checkpoint_files_sha256']), {'model.safetensors', 'processor_config.json'})
                self.assertEqual(adapter.call_args.args[0], 'qwen')
                selection['revision'] = 'c' * 40
                with self.assertRaisesRegex(ValueError, 'snapshot directory'): backends.create(selection)

    def test_moving_unknown_or_missing_selections_are_rejected(self):
        for selection in ({'backend': 'unknown'}, {'backend': 'surya', 'model_path': '/models', 'revision': 'main'},
                          {'backend': 'gemma', 'model_path': '/models', 'revision': 'a' * 64}):
            with self.assertRaises(ValueError): backends.validate(selection)


if __name__ == '__main__': unittest.main()
