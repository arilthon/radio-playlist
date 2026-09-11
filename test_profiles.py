import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from dashboard import Controller
from history import History
from radio_profiles import add_profile, data_dir, profiles, get_profile
from tidal_coordination import account_gate


class ProfileTests(unittest.TestCase):
    def test_preserves_default_and_isolates_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env').write_text('RADIO_STREAM_URL=https://original.test/stream\nPLAYLIST_ID=original\n')
            old = History(root / 'history.sqlite3')
            old.record('original', 'Old - Song', 'adicionada', '1')
            old.close()
            p = add_profile(root, 'Segunda', 'https://second.test/stream', '550e8400-e29b-41d4-a716-446655440000')
            self.assertEqual(profiles(root)[0]['url'], 'https://original.test/stream')
            self.assertEqual(get_profile(root, p['id'])['name'], 'Segunda')
            new = History(data_dir(root, p['id']) / 'history.sqlite3')
            self.assertEqual(new.recent(), [])
            new.enqueue('p','New - Song')
            new.close()
            old = History(root / 'history.sqlite3')
            self.assertIsNone(old.next_pending('p'))
            self.assertEqual(len(old.recent()), 1)
            old.close()
            with self.assertRaises(ValueError):
                data_dir(root, '../escape')
            with self.assertRaises(ValueError):
                add_profile(root, 'Bad', 'file:///tmp/local', 'bad')

    @patch('dashboard.subprocess.Popen')
    def test_independent_process_controls(self, popen):
        with tempfile.TemporaryDirectory() as folder, patch('dashboard.ROOT', Path(folder)):
            first = Mock(); first.poll.return_value = None
            second = Mock(); second.poll.return_value = None
            popen.side_effect = [first, second]
            (Path(folder) / 'radios.json').write_text(json.dumps([{'id':'123456789abc','name':'B','url':'https://b.test/stream','playlist':'550e8400-e29b-41d4-a716-446655440000'}]))
            a, b = Controller(), Controller('123456789abc')
            try:
                a.start('radio'); b.start('radio')
                self.assertEqual(popen.call_args_list[0].args[0][-3:], ['--profile','default','--radio-only'])
                self.assertEqual(popen.call_args_list[1].args[0][-3:], ['--profile','123456789abc','--radio-only'])
                self.assertTrue(a.state()['running']); self.assertTrue(b.state()['running'])
                a.stop()
                first.send_signal.assert_called_once()
                second.send_signal.assert_not_called()
            finally:
                a.log.close(); b.log.close()

    def test_rate_limit_is_shared_by_independent_clients(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rate.json'
            response = requests.Response(); response.status_code = 429
            response.headers['Retry-After'] = '120'
            with self.assertRaises(requests.HTTPError):
                with account_gate(path):
                    raise requests.HTTPError(response=response)
            with self.assertRaises(requests.HTTPError) as caught:
                with account_gate(path):
                    self.fail('Não deve permitir outra chamada durante a pausa.')
            self.assertEqual(caught.exception.response.status_code,429)
            self.assertGreater(int(caught.exception.response.headers['Retry-After']), 0)
