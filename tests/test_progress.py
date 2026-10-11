import io
import json
import logging
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone, timedelta
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from pipeline.progress import ProgressReporter, read_status
from pipeline.discovery import crawler
from pipeline.download import downloader
import test_download as fixtures
from test_download import Fetcher, SOURCE, PDF


class ProgressTests(unittest.TestCase):
    def test_throttle_transfer_rate_eta_and_final_flush(self):
        now = [0.0]
        output = io.StringIO()
        p = ProgressReporter('download', stream=output, clock=lambda: now[0])
        p.begin_transfer(100)
        lines = len(output.getvalue().splitlines())
        p.transfer(10, 100)
        self.assertEqual(len(output.getvalue().splitlines()), lines)
        now[0] = 2
        p.transfer(50, 100)
        self.assertEqual(p.state['transfer']['percent'], 50)
        self.assertEqual(p.state['transfer']['bytes_per_second'], 25)
        self.assertEqual(p.state['transfer']['eta_seconds'], 2)
        p.transfer(100, 100)
        p.finish()
        self.assertIn('100%', output.getvalue().splitlines()[-1])
        self.assertEqual(p.state['status'], 'completed')

    def test_unknown_length_has_no_percent_or_eta(self):
        p = ProgressReporter('download', mode='off')
        p.begin_transfer(None)
        p.transfer(100, None)
        self.assertIsNone(p.state['transfer']['percent'])
        self.assertIsNone(p.state['transfer']['eta_seconds'])

    def test_snapshot_read_is_read_only_and_stale_is_not_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'run.progress.json'
            wall = datetime(2026, 1, 1, tzinfo=timezone.utc)
            p = ProgressReporter('discovery', path=path, mode='off', wall_clock=lambda: wall)
            before = path.read_bytes()
            state = read_status(path, now=wall + timedelta(seconds=121))
            self.assertEqual(state['observed_status'], 'possibly_stale')
            self.assertEqual(state['status'], 'running')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(folder).iterdir()), [path])
            p.finish('interrupted')
            self.assertEqual(read_status(path, now=wall + timedelta(days=1))['observed_status'], 'interrupted')

    def test_snapshot_failure_and_closed_display_do_not_fail_work(self):
        with tempfile.TemporaryDirectory() as folder:
            blocker = Path(folder) / 'file'
            blocker.write_text('occupied')
            output = io.StringIO()
            p = ProgressReporter('download', path=blocker / 'snapshot', stream=output)
            self.assertTrue(p.snapshot_disabled)
            p.finish()
            self.assertEqual(output.getvalue().count('Progress snapshot unavailable'), 1)
        output = io.StringIO()
        output.close()
        ProgressReporter('download', stream=output).finish()

    def test_plain_stderr_does_not_pollute_stdout_and_off_is_silent(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            p = ProgressReporter('download', mode='plain')
            p.finish()
            print(json.dumps({'results': []}))
        self.assertEqual(json.loads(out.getvalue()), {'results': []})
        self.assertIn('[download]', err.getvalue())
        output = io.StringIO()
        ProgressReporter('download', mode='off', stream=output).finish()
        self.assertEqual(output.getvalue(), '')

    def test_retry_wait_and_absent_robots_are_reported(self):
        output = io.StringIO()
        p = ProgressReporter('discovery', stream=output)
        f = crawler.PoliteFetcher(0, 1, logging.getLogger('progress-test'), progress=p)
        error = HTTPError('https://school.test/robots.txt', 404, 'fixture', Message(), None)
        with patch.object(crawler, 'build_opener') as opener, patch.object(f.logger, 'warning') as warning:
            opener.return_value.open.side_effect = error
            self.assertTrue(f.robots_allowed('https://school.test/'))
            warning.assert_not_called()
        self.assertEqual(p.state['robots_outcome'], 'absent')
        self.assertEqual(p.state['robots_http_status'], 404)
        with patch.object(crawler.time, 'sleep'):
            f._wait(2)
        self.assertIn('retry_wait', output.getvalue())


class DownloadProgressTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    write_catalog = fixtures.DownloadTests.write_catalog
    execute = fixtures.DownloadTests.execute

    def test_completed_totals_and_existing_verification(self):
        report = self.execute(progress_mode='off')
        snapshot = read_status(Path(report['progress_path']))
        self.assertEqual(snapshot['counts']['jobs_completed'], len(report['results']))
        self.assertEqual(snapshot['counts']['downloaded'], 1)
        self.assertEqual(snapshot['transfer']['bytes_received'], len(PDF))
        self.assertEqual(snapshot['transfer']['percent'], 100)
        self.assertEqual(snapshot['status'], 'completed')
        report = self.execute(progress_mode='off')
        self.assertEqual(read_status(Path(report['progress_path']))['counts']['verified_existing'], 1)

    def test_dry_run_with_progress_still_writes_nothing(self):
        self.execute(dry_run=True, progress_mode='plain')
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'documents.csv'})
        self.assertEqual(Fetcher.calls, [])

    def test_interrupted_and_failed_snapshots(self):
        with patch.object(downloader, 'recover', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(progress_mode='off')
        path = next(self.settings['log_root'].glob('*.progress.json'))
        self.assertEqual(read_status(path)['status'], 'interrupted')
        Fetcher.response_factory = staticmethod(lambda: None)
        report = self.execute(progress_mode='off')
        state = read_status(Path(report['progress_path']))
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['counts']['failed'], 1)
        self.assertEqual(state['counts']['jobs_completed'], 1)


class DiscoveryProgressTests(unittest.TestCase):
    def test_json_output_and_final_snapshot_with_fake_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = crawler.build_argument_parser().parse_args(['--source', 'school', '--dry-run', '--json', '--quiet'])
            logger = logging.getLogger('progress-discovery')
            def discover(source, subjects, limits, logger, sink, progress):
                progress.update(force=True, source_id='school', counts={'pages_visited': 2, 'candidates': 0})
                return [], {'pages_visited': 2, 'errors': 0, 'outcome': 'success'}
            output = io.StringIO()
            with patch.object(crawler, 'create_logger', return_value=(logger, root / 'run.log')), patch.object(crawler, 'load_configuration', return_value=([SOURCE], {})), patch.object(crawler, 'read_catalog', return_value=[]), patch.object(crawler, 'discover_source', side_effect=discover), redirect_stdout(output):
                self.assertEqual(crawler.run(args), 0)
            report = json.loads(output.getvalue())
            state = read_status(Path(report['progress_path']))
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['counts']['pages_visited'], report['totals']['pages_visited'])

    def test_real_discovery_final_counts_match_source_stats(self):
        class FakeFetcher:
            def __init__(self, *args, **kwargs):
                self.error_count = 0
            def robots_allowed(self, url):
                return True
            def fetch_html(self, url, base):
                return crawler.FetchedPage('<title>Home</title><a href="/paper.pdf">Grade 10 History past paper PDF</a><a href="/about">About</a>', url)
        p = ProgressReporter('discovery', mode='off')
        with patch.object(crawler, 'PoliteFetcher', FakeFetcher):
            candidates, stats = crawler.discover_source(SOURCE, {}, {'max_pages_per_source': 1}, logging.getLogger('progress-counts'), progress=p)
        self.assertEqual(p.state['counts']['pages_visited'], stats['pages_visited'])
        self.assertEqual(p.state['counts']['candidates'], len(candidates))
        self.assertGreater(p.state['counts']['rejected'], 0)
        self.assertEqual(p.state['stop_reason'], stats['stop_reason'])

    def test_discovery_interruption_is_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = crawler.build_argument_parser().parse_args(['--dry-run', '--quiet', '--json'])
            with patch.object(crawler, 'create_logger', return_value=(logging.getLogger('interrupt-test'), root / 'run.log')), patch.object(crawler, '_run', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    crawler.run(args)
            self.assertEqual(read_status(root / 'run.progress.json')['status'], 'interrupted')
