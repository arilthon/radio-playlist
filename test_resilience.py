import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from dashboard import Controller, resume_monitors
from history import History
from pipeline import monitor, process_next


def failure(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.h = History(self.root / 'history.sqlite3')
        self.h.enqueue('p', 'A - One')
        self.h.enqueue('p', 'A - Two')

    def tearDown(self):
        self.h.close()
        self.folder.cleanup()

    def test_failed_track_does_not_block_next_and_retry_survives_restart(self):
        process_next(None, 'p', self.h, False, Mock(side_effect=failure(500)))
        self.assertEqual(self.h.next_pending('p')[1], 'A - Two')
        other = History(self.root / 'history.sqlite3')
        try:
            self.assertEqual(other.db.execute('SELECT attempts FROM pending ORDER BY id').fetchone()[0], 1)
            with patch('history.time.time', return_value=10**12):
                self.assertEqual(other.next_pending('p')[1], 'A - One')
        finally:
            other.close()

    def test_bad_track_goes_to_review(self):
        process_next(None, 'p', self.h, False, Mock(side_effect=failure(404)))
        self.assertEqual(self.h.next_pending('p')[1], 'A - Two')
        self.assertEqual(self.h.review_items()[0]['title'], 'A - One')

    def test_retry_limit_and_manual_reset(self):
        job, _, revision = self.h.next_pending('p')
        for _ in range(5):
            self.h.defer(job, revision)
        event = self.h.review_items()[0]['event_id']
        self.h.requeue(event, dry_run=False)
        row = self.h.db.execute('SELECT attempts,next_attempt FROM pending WHERE title=?', ('A - One',)).fetchone()
        self.assertEqual(row, (0, 0))

    def test_new_manual_revision_is_not_deferred(self):
        job, _, revision = self.h.next_pending('p')
        self.h.record('p', 'A - One', 'erro')
        self.h.requeue(self.h.review_items()[0]['event_id'], dry_run=False)
        self.h.defer(job, revision, permanent=True)
        self.assertEqual(self.h.next_pending('p'), (job, 'A - One', revision + 1))

    def test_account_errors_preserve_job_without_consuming_attempt(self):
        for status in (401, 403, 429):
            with self.assertRaises(requests.HTTPError):
                process_next(None, 'p', self.h, False, Mock(side_effect=failure(status)))
        self.assertEqual(self.h.db.execute('SELECT sum(attempts) FROM pending').fetchone()[0], 0)

    def test_missing_playlist_pauses_account_instead_of_rejecting_tracks(self):
        error = failure(404)
        error.response.url = 'https://example.test/v2/playlists/p/relationships/items'
        with self.assertRaises(requests.HTTPError):
            process_next(None, 'p', self.h, False, Mock(side_effect=error))
        self.assertEqual(self.h.next_pending('p')[1], 'A - One')

    def test_start_saves_mode_for_next_dashboard(self):
        with patch('dashboard.ROOT', self.root), patch('dashboard.subprocess.Popen'):
            controller = Controller()
            controller.start('radio')
            self.assertEqual(Controller().desired_mode(), 'radio')
            controller.log.close()

    def test_capture_continues_after_authorization_error(self):
        captured = threading.Event()
        def stream(url):
            yield 'A - New'
            captured.set()
            while True:
                yield None
        original_wait = threading.Event.wait
        def pause(event, seconds=None):
            if threading.current_thread() is threading.main_thread() and seconds == 30:
                self.assertTrue(original_wait(captured, 2))
                raise KeyboardInterrupt
            return original_wait(event, seconds)
        with patch('radio.stream_titles', stream), patch('radio.processar', side_effect=failure(401)), \
             patch('pipeline.retry_delay', return_value=1), patch('pipeline.threading.Event.wait', autospec=True) as wait:
            # Only interrupt the main worker wait; the capture doesn't use wait while streaming.
            wait.side_effect = pause
            with self.assertRaises(KeyboardInterrupt):
                monitor('url', None, 'p', self.h, self.root/'history.sqlite3', False, False, 1)
        self.assertTrue(self.h.db.execute("SELECT 1 FROM pending WHERE title='A - New'").fetchone())

    def test_stop_and_shutdown_persist_different_intent(self):
        with patch('dashboard.ROOT', self.root):
            controller = Controller()
            controller.save_desired('real')
            controller.stop(preserve_desired=True)
            self.assertEqual(Controller().desired_mode(), 'real')
            controller.stop()
            self.assertIsNone(Controller().desired_mode())

    def test_resume_skips_archived_and_continues_after_failure(self):
        first, second = Mock(), Mock()
        first.desired_mode.return_value = 'real'
        first.start.side_effect = ValueError('Login necessário')
        second.desired_mode.return_value = 'radio'
        factory = Mock(side_effect=[first, second])
        with patch('dashboard.profiles', return_value=[{'id':'one'}, {'id':'archived','archived':True}, {'id':'two'}]):
            resume_monitors(self.root, factory)
        first.start.assert_called_once_with('real')
        second.start.assert_called_once_with('radio')
        self.assertEqual(factory.call_count, 2)
