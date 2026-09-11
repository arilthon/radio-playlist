from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dashboard import Controller
from radio_profiles import add_profile


class LoginPreflightTests(unittest.TestCase):
    def test_spotify_without_login_does_not_spawn_and_names_profile(self):
        with tempfile.TemporaryDirectory() as folder, patch('dashboard.ROOT',Path(folder)):
            root=Path(folder)
            (root/'.env').write_text('SPOTIFY_CLIENT_ID=test\n')
            profile=add_profile(root,'Spotify','https://radio.test/stream','a'*22,'spotify')
            c=Controller(profile['id'])
            with patch('dashboard.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(ValueError,profile['id']):c.start('dry')
                spawn.assert_not_called()

    def test_error_notice_uses_selected_profile(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder, patch('dashboard.ROOT',Path(folder)):
            root=Path(folder)
            profile=add_profile(root,'Spotify','https://radio.test/stream','a'*22,'spotify')
            c=Controller(profile['id']);c.process=Mock();c.process.poll.return_value=1
            self.assertIn('--profile '+profile['id'],c.state()['notice'])
