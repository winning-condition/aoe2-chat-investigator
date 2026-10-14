import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui import create_server, validate_players
from runtime import worker_command

FIELDS = ['date', 'match_id', 'file', 'map', 'opponents', 'result', 'section', 'game_time', 'speaker', 'is_target', 'type', 'message', 'attribution']


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.server = create_server(self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://{self.server.host}/{self.server.token}/'

    def tearDown(self):
        self.server.app.cancel()
        deadline = time.monotonic() + 10
        while self.server.app.job['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.05)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, route, payload=None, headers=None, raw=None):
        if raw is not None:
            body = raw
        else:
            body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + route, data=body, headers=headers or ({'Content-Type': 'application/json'} if body else {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as response:
            with response:
                return response.code, response.headers, response.read()

    def add_player(self):
        self.assertEqual(self.request('api/player', {'name': 'ExamplePlayer', 'profile_id': 1234567})[0], 200)

    def test_watchlist_persistence_edit_and_remove_keep_data(self):
        self.add_player()
        replay = self.data / 'replays/exampleplayer/imported/sample.aoe2record'
        replay.parent.mkdir(parents=True)
        replay.write_bytes(b'recording')
        self.assertEqual(self.request('api/player', {'name': 'CorrectName', 'profile_id': 1234567, 'since_match': '500000001'})[0], 200)
        self.assertTrue((self.data / 'replays/correctname/imported/sample.aoe2record').exists())
        players = json.loads((self.data / 'watchlist.json').read_text())
        self.assertEqual(players[0]['since_match'], 500000001)
        self.assertEqual(self.request('api/remove', {'profile_id': 1234567})[0], 200)
        self.assertTrue((self.data / 'replays/correctname/imported/sample.aoe2record').exists())
        self.assertEqual(self.server.app.players(), [])

    def test_invalid_players_cannot_overwrite_watchlist(self):
        self.add_player()
        original = (self.data / 'watchlist.json').read_bytes()
        for player in ({'name': '', 'profile_id': 1}, {'name': 'CON', 'profile_id': 1}, {'name': 'Other', 'profile_id': -1}, {'name': 'Other', 'profile_id': 2, 'since_match': 'oops'}):
            self.assertEqual(self.request('api/player', player)[0], 400)
        self.assertEqual(original, (self.data / 'watchlist.json').read_bytes())
        with self.assertRaises(ValueError):
            validate_players([{'name': 'a/b', 'profile_id': 1}, {'name': 'a?b', 'profile_id': 2}])

    def test_server_is_local_token_protected_and_checks_origin(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f'http://{self.server.host}/api/state')
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertEqual(self.request('api/player', {'name': 'Test', 'profile_id': 1}, {'Content-Type': 'application/json', 'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request('../LICENSE')[0], 404)
        self.assertEqual(self.request('%2e%2e/LICENSE')[0], 404)
        status, headers, body = self.request('')
        self.assertEqual(status, 200)
        self.assertIn(b'AOE2 Chat Investigator', body)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('style.css')[0], 200)
        self.assertEqual(self.request('assets/cinzel.ttf')[0], 200)

    def test_import_deduplicates_and_rejects_path_traversal(self):
        self.add_player()
        headers = {'Content-Type': 'application/octet-stream'}
        for _ in range(2):
            self.assertEqual(self.request('api/import?profile_id=1234567&filename=Test.ZIP', headers=headers, raw=b'PKfake')[0], 200)
        self.assertEqual(len(list((self.data / 'replays/exampleplayer/imported').glob('*.zip'))), 1)
        for name in ('../evil.zip', 'C:%5Cevil.zip', 'script.py'):
            self.assertEqual(self.request(f'api/import?profile_id=1234567&filename={name}', headers=headers, raw=b'abc')[0], 400)

    def test_reports_preserve_unicode_attribution_and_exports(self):
        self.add_player()
        out = self.data / 'output'
        out.mkdir()
        row = dict(zip(FIELDS, ['2026-01-14 21:17', '500000001', 'test.zip', 'Arabia', 'Opponent', 'won', 'post-game', '', 'ExamplePlayer', 'True', 'chat', '<script>alert(1)</script> gg 日本語', 'matched by timing only (unverified)']))
        with (out / 'exampleplayer_chat.csv').open('w', newline='', encoding='utf-8-sig') as file:
            writer = csv.DictWriter(file, FIELDS)
            writer.writeheader()
            writer.writerow(row)
        (out / 'exampleplayer_chat.txt').write_text('Exact transcript 日本語', encoding='utf-8')
        status, _, body = self.request('api/report?profile_id=1234567')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['rows'][0], row)
        status, headers, body = self.request('api/export?profile_id=1234567&format=txt')
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertEqual(body.decode(), 'Exact transcript 日本語')
        self.assertEqual(self.request('api/export?profile_id=1234567&format=exe')[0], 400)

    def test_real_extraction_worker_handles_spaces_and_empty_folder(self):
        self.add_player()
        self.assertEqual(self.request('api/job', {'action': 'extract', 'profile_id': 1234567, 'offline': True})[0], 200)
        self.assertEqual(self.request('api/player', {'name': 'New', 'profile_id': 9})[0], 400)
        deadline = time.monotonic() + 30
        while self.server.app.job['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertEqual(self.server.app.job['status'], 'done', self.server.app.job['log'])
        self.assertIn('0 unique replays', self.server.app.job['log'])
        self.assertTrue((self.data / 'output/exampleplayer_chat.txt').exists())

    def test_real_replay_parser_worker(self):
        fixture = Path(__file__).resolve().parents[1] / 'mgz-fast/tests/recs/de-67.2.aoe2record'
        if not fixture.exists():
            self.skipTest('Upstream replay fixture unavailable')
        import chatlog
        parsed = chatlog.parse_game(str(fixture))
        name = next(iter(parsed['players'].values()))
        folder = self.data / 'replays with spaces'
        folder.mkdir()
        shutil.copyfile(fixture, folder / 'fixture.aoe2record')
        result = subprocess.run(worker_command('chatlog.py', [str(folder), '--player', name, '--out', str(self.data / 'output'), '--offline'], self.data), capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('1 unique replays', result.stdout)
        self.assertNotIn('FAILED', result.stdout)

    def test_daily_worker_uses_chosen_data_folder(self):
        watchlist = self.data / 'watchlist.json'
        watchlist.write_text('[]')
        result = subprocess.run(worker_command('daily_check.py', ['--watchlist', str(watchlist)], self.data), capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.data / 'output/latest_check.txt').exists())
        self.assertIn('Nothing new', result.stdout)

    def test_cancel_stops_worker_and_unlocks_watchlist(self):
        self.add_player()
        with mock.patch('gui.worker_command', return_value=[sys.executable, '-u', '-c', 'import time; print("started", flush=True); time.sleep(60)']):
            self.assertEqual(self.request('api/job', {'action': 'extract', 'profile_id': 1234567})[0], 200)
            deadline = time.monotonic() + 10
            while 'started' not in self.server.app.job['log'] and time.monotonic() < deadline:
                time.sleep(.05)
            process = self.server.app.process
            self.assertIsNotNone(process)
            self.assertEqual(self.request('api/cancel', {})[0], 200)
            while self.server.app.job['status'] == 'running' and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertEqual(self.server.app.job['status'], 'cancelled')
            self.assertIsNotNone(process.poll())
            self.assertEqual(self.request('api/player', {'name': 'New', 'profile_id': 9})[0], 200)

    def test_player_name_that_begins_with_dash_is_a_value(self):
        self.assertEqual(self.request('api/player', {'name': '--out', 'profile_id': 1})[0], 200)
        self.assertEqual(self.request('api/job', {'action': 'extract', 'profile_id': 1, 'offline': True})[0], 200)
        deadline = time.monotonic() + 30
        while self.server.app.job['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertEqual(self.server.app.job['status'], 'done', self.server.app.job['log'])
        self.assertTrue((self.data / 'output/--out_chat.txt').exists())

    def test_transcript_stays_consistent_during_rebuild(self):
        self.add_player()
        report = self.data / 'output/exampleplayer_chat.csv'
        report.parent.mkdir()
        with report.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, FIELDS)
            writer.writeheader()
            writer.writerow({'match_id': '500000001', 'message': 'completed report'})
        with mock.patch('gui.worker_command', return_value=[sys.executable, '-u', '-c', 'import time; time.sleep(60)']):
            self.request('api/job', {'action': 'extract', 'profile_id': 1234567})
            report.write_text('partial rebuild', encoding='utf-8')
            status, _, body = self.request('api/report?profile_id=1234567')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['rows'][0]['message'], 'completed report')
            self.assertEqual(self.request('api/export?profile_id=1234567&format=csv')[0], 400)
            self.request('api/cancel', {})


if __name__ == '__main__':
    unittest.main()
