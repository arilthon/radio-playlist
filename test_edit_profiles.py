import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from history import History
from instance_lock import acquire
from radio_profiles import add_profile, apply_profile, data_dir, edit_profile, get_profile, set_archived


class EditProfileTests(unittest.TestCase):
    def test_edit_preserves_id_history_archive_and_rejects_destination_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = add_profile(root, 'One', 'https://radio.test/a', 'a'*22, 'spotify')
            h = History(data_dir(root, p['id'])/'history.sqlite3')
            h.enqueue(p['playlist'], 'Artist - Song')
            h.record(p['playlist'], 'Artist - Song', 'capturada')
            set_archived(root, p['id'], True)
            changed = edit_profile(root, p['id'], 'New', 'https://radio.test/b', p['playlist'], 'spotify')
            self.assertEqual(changed['id'], p['id'])
            self.assertTrue(changed['archived'])
            self.assertEqual(h.next_pending(p['playlist'])[1], 'Artist - Song')
            with self.assertRaises(ValueError):
                edit_profile(root, p['id'], 'New', changed['url'], 'b'*22, 'spotify')
            h.close()

    def test_active_monitor_duplicate_name_and_invalid_url_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = add_profile(root, 'One', 'https://radio.test/a', 'a'*22, 'spotify')
            lock = acquire(data_dir(root,p['id'])/'.monitor.lock')
            try:
                with self.assertRaises(ValueError):
                    edit_profile(root,p['id'],'New',p['url'],p['playlist'],'spotify')
            finally:
                lock.close()
            for name, url in [('Rádio principal',p['url']), ('New','file:///tmp/a')]:
                with self.assertRaises(ValueError):
                    edit_profile(root,p['id'],name,url,p['playlist'],'spotify')

    def test_default_override_survives_other_profile_updates_and_applies(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            edit_profile(root,'default','Main','https://radio.test/main','a'*22,'spotify')
            p = add_profile(root,'Other','https://radio.test/other','b'*22,'spotify')
            set_archived(root,p['id'],True)
            apply_profile(root,'default')
            self.assertEqual(os.environ['MUSIC_PROVIDER'],'spotify')
            self.assertEqual(os.environ['RADIO_STREAM_URL'],'https://radio.test/main')
            self.assertEqual(get_profile(root,'default')['name'],'Main')

    def test_unused_profile_can_change_service(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = add_profile(root,'One','https://radio.test/a','a'*22,'spotify')
            changed = edit_profile(root,p['id'],'One',p['url'],'11111111-1111-1111-1111-111111111111','tidal')
            self.assertEqual(changed['provider'],'tidal')
