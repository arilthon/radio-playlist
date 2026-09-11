import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from history import History
from pipeline import capture, process_next


class PipelineTests(unittest.TestCase):
    def test_queue_survives_error_restart_and_separates_simulation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.db'
            h = History(path)
            h.enqueue('p', 'A - One')
            h.enqueue('p', 'A - One')
            h.enqueue('p', 'A - Two')
            h.enqueue('p', 'A - Dry', True)
            with self.assertRaises(RuntimeError):
                process_next(None, 'p', h, False, Mock(side_effect=RuntimeError('offline')))
            h.close()
            h = History(path)
            self.assertEqual(h.next_pending('p')[1], 'A - One')
            process_next(None, 'p', h, False, Mock())
            self.assertEqual(h.next_pending('p')[1], 'A - Two')
            process_next(None, 'p', h, False, Mock())
            self.assertIsNone(h.next_pending('p'))
            self.assertEqual(h.next_pending('p', True)[1], 'A - Dry')
            h.close()

    def test_capture_queues_changes_without_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.db'
            stop = threading.Event()
            def stream(url):
                yield 'A - One'
                yield 'A - One'
                yield 'A - Two'
                stop.set()
            capture('test', 'p', path, False, False, 1, stop, threading.Event(), stream)
            h = History(path)
            self.assertEqual(h.next_pending('p')[1], 'A - One')
            h.finish(h.next_pending('p')[0])
            self.assertEqual(h.next_pending('p')[1], 'A - Two')
            self.assertEqual(len(h.recent()), 2)
            h.close()
