import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from history import History
from radio_profiles import add_profile, set_archived, get_profile, apply_profile, data_dir
from instance_lock import acquire
from dashboard import Controller


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.profile=add_profile(self.root,'Extra','https://radio.test/stream','550e8400-e29b-41d4-a716-446655440000')
        self.id=self.profile['id']

    def test_archive_restore_preserves_history_queue_choices(self):
        h=History(data_dir(self.root,self.id)/'history.sqlite3')
        self.addCleanup(h.close)
        h.record('p','Artist - Song','incerta')
        h.requeue(1,True,'123','Song')
        set_archived(self.root,self.id,True)
        self.assertTrue(get_profile(self.root,self.id)['archived'])
        with self.assertRaises(ValueError):apply_profile(self.root,self.id)
        self.assertEqual(h.choice('Artist - Song')['id'],'123')
        self.assertIsNotNone(h.next_pending('p',True))
        set_archived(self.root,self.id,False)
        self.assertFalse(get_profile(self.root,self.id)['archived'])
        self.assertEqual(len(h.recent()),2)

    def test_external_monitor_cannot_be_archived(self):
        lock=acquire(data_dir(self.root,self.id)/'.monitor.lock')
        try:
            with self.assertRaises(ValueError):set_archived(self.root,self.id,True)
        finally:lock.close()
        self.assertFalse(get_profile(self.root,self.id).get('archived',False))
        with self.assertRaises(ValueError):set_archived(self.root,'default',True)

    def test_controller_stops_owned_monitor_and_blocks_restart(self):
        with patch('dashboard.ROOT',self.root):
            c=Controller(self.id)
            c.process=Mock()
            c.process.poll.return_value=None
            c.archive()
            c.process.send_signal.assert_called_once()
            c.process.poll.return_value=0
            with self.assertRaises(ValueError):c.start('dry')
            c.archive(False)
            self.assertFalse(c.state()['archived'])
