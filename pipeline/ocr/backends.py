"""Replaceable local-image OCR backends shared by experiments and production."""
import re
from pathlib import Path

from pipeline.ocr.neural import GPUBackend, MODELS


def validate(selection):
    if selection.get('backend') not in MODELS:
        raise ValueError('Unknown OCR backend')
    revision = selection.get('revision', '')
    length = 64 if selection['backend'] == 'surya' else 40
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', revision):
        raise ValueError('OCR requires an immutable model revision')
    path = selection.get('model_path')
    if not isinstance(path, (str, Path)) or not str(path):
        raise ValueError('Local OCR model_path is required')
    seconds = selection.get('max_page_seconds', 120)
    if type(seconds) is not int or seconds < 1:
        raise ValueError('Invalid OCR page deadline')


def create(selection):
    validate(selection)
    if not Path(selection['model_path']).is_dir():
        raise ValueError('Local OCR checkpoint folder does not exist')
    from pipeline.ocr.surya_backend import SuryaBackend, block_network
    # A separate process is used for acquisition; no network inside OCR workers.
    block_network()
    if selection['backend'] == 'surya':
        return SuryaBackend(Path(selection['model_path']), selection['revision'], selection.get('max_page_seconds', 120))
    root = Path(selection['model_path']).resolve()
    expected_repo = 'models--' + MODELS[selection['backend']].replace('/', '--')
    if root.name != selection['revision'] or root.parent.name != 'snapshots' or root.parent.parent.name != expected_repo:
        raise ValueError('Use the selected model/revision Hugging Face snapshot directory')
    from pipeline.download.downloader import file_hash
    hashes = {str(p.relative_to(root)): file_hash(p) for p in root.rglob('*') if p.is_file()}
    if not any(p.endswith('.safetensors') for p in hashes):
        raise ValueError('Checkpoint has no recorded safetensors weights')
    engine = GPUBackend(selection['backend'], root, selection.get('max_new_tokens', 8192), selection.get('max_page_seconds', 120))
    engine.identity['checkpoint_files_sha256'] = hashes
    return engine
