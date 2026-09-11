import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dashboard import Controller
from history import History
from instance_lock import acquire, running


class DashboardTests(unittest.TestCase):
    def test_lock_blocks_second_monitor(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lock'
            lock = acquire(path)
            try:
                self.assertTrue(running(path))
                with self.assertRaises(ValueError):
                    acquire(path)
            finally:
                lock.close()
            self.assertFalse(running(path))

    def test_state_and_controls(self):
        with tempfile.TemporaryDirectory() as folder, patch('dashboard.ROOT', Path(folder)):
            h = History(Path(folder) / 'history.sqlite3')
            h.record('p', '<script>test</script>', 'capturada')
            h.enqueue('p','Artist - Song')
            h.close()
            c = Controller()
            state = c.state()
            self.assertEqual(state['pending_count'], 1)
            self.assertFalse(state['running'])
            with self.assertRaises(ValueError):
                c.start('invalid')
            lock = acquire(Path(folder) / '.monitor.lock')
            try:
                with self.assertRaises(ValueError):
                    c.start('real')
                with self.assertRaises(ValueError):
                    c.diagnose()
            finally:
                lock.close()

    @patch('diagnostics.dotenv_values', return_value={})
    def test_missing_config_does_not_contact_tidal(self, values):
        from diagnostics import diagnose
        with patch('diagnostics.TidalClient') as client:
            result = diagnose()
            self.assertFalse(result[0]['ok'])
            client.assert_not_called()
