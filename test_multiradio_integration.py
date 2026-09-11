"""Duas capturas reais em processos isolados, com rádio HTTP local simulada."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from radio_profiles import add_profile, data_dir


class MultiRadioIntegration(unittest.TestCase):
    def test_two_streams_capture_into_separate_databases(self):
        class Stream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200); self.send_header('icy-metaint', '3'); self.end_headers()
                title = 'Artist A - Song A' if self.path == '/a' else 'Artist B - Song B'
                metadata = ("StreamTitle='" + title + "';").encode()
                size = (len(metadata) + 15) // 16
                block = b'abc' + bytes([size]) + metadata.ljust(size * 16, b'\0')
                try:
                    for _ in range(50):
                        self.wfile.write(block); self.wfile.flush(); time.sleep(.1)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Stream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        jobs = []
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for source in Path(__file__).parent.glob('*.py'):
                    if not source.name.startswith('test_'):
                        shutil.copy(source, root / source.name)
                url = f'http://127.0.0.1:{server.server_port}'
                (root / '.env').write_text(f'RADIO_STREAM_URL={url}/a\nPOLL_INTERVAL=1\n')
                second = add_profile(root, 'B', url+'/b', '550e8400-e29b-41d4-a716-446655440000')
                paths = [root / 'history.sqlite3', data_dir(root, second['id']) / 'history.sqlite3']
                try:
                    for profile in ['default', second['id']]:
                        jobs.append(subprocess.Popen([sys.executable, str(root/'radio.py'), '--profile',profile,'--radio-only'],
                                                     cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    seen = [[], []]
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        for index, path in enumerate(paths):
                            if path.exists():
                                try:
                                    with sqlite3.connect(path) as db:
                                        seen[index] = [r[0] for r in db.execute('SELECT title FROM events')]
                                except sqlite3.OperationalError:
                                    pass
                        if all(seen):
                            break
                        time.sleep(.1)
                    self.assertEqual(set(seen[0]), {'Artist A - Song A'})
                    self.assertEqual(set(seen[1]), {'Artist B - Song B'})
                    self.assertTrue(all(p.poll() is None for p in jobs))
                finally:
                    for job in jobs:
                        if job.poll() is None:
                            job.send_signal(signal.SIGINT)
                            try:
                                job.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                job.kill(); job.wait()
        finally:
            server.shutdown(); server.server_close()
