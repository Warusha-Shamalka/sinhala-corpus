"""Small dependency-free notebook helpers; OCR remains in its isolated process."""
import json
import subprocess


def execute(python, root, *args):
    """Stream progress on stderr while retaining stdout as a single JSON report."""
    result = subprocess.run([python, '-B', '-m', 'pipeline.workflow', *args], cwd=root,
                            text=True, stdout=subprocess.PIPE)
    if result.stdout: print(result.stdout)
    result.check_returncode()
    return json.loads(result.stdout)
