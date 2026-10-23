"""Small dependency-free notebook helpers; OCR remains in its isolated process."""
import json
import subprocess
import sys


def execute(python, root, *args, allow_partial=False):
    """Stream progress on stderr while retaining stdout as a single JSON report."""
    result = subprocess.run([python, '-B', '-m', 'pipeline.workflow', *args], cwd=root,
                            text=True, stdout=subprocess.PIPE)
    if result.stdout: print(result.stdout)
    if allow_partial and result.returncode == 1:
        # Only a valid processing report is a recoverable partial result.
        # Command setup failures and malformed output must still raise.
        try:
            report = json.loads(result.stdout)
        except (ValueError, TypeError):
            result.check_returncode()
        if (isinstance(report, dict) and report.get('schema_version') == 'page-processing-run-1'
                and isinstance(report.get('results'), list) and isinstance(report.get('errors'), list)):
            print('Processing finished with issues. Inspect errors, incomplete predictions and saved reports.', file=sys.stderr)
            return report
    result.check_returncode()
    return json.loads(result.stdout)
