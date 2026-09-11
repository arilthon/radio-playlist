import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_config import storage_root
from music_service import client_from_values
from radio_profiles import add_profile, profiles, data_dir


class ContainerConfigTests(unittest.TestCase):
    def test_data_and_tokens_outside_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';root.mkdir()
            data=Path(folder)/'data'
            with patch.dict(os.environ,{'RADIO_DATA_DIR':str(data)}):
                p=add_profile(root,'Test','https://radio.test/stream','a'*22,'spotify')
                self.assertTrue((data/'radios.json').exists())
                self.assertFalse((root/'radios.json').exists())
                self.assertEqual(data_dir(root),data)
                self.assertEqual(data_dir(root,p['id']),data/'stations'/p['id'])
                client=client_from_values(root,'spotify',{'SPOTIFY_CLIENT_ID':'test'})
                self.assertEqual(client.cache_path,data/'.spotify-cache.json')

    def test_environment_config_in_default_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{'RADIO_STREAM_URL':'https://env.test/stream','PLAYLIST_ID':'playlist-env'}):
                profile=profiles(Path(folder))[0]
                self.assertEqual(profile['url'],'https://env.test/stream')
                self.assertEqual(profile['playlist'],'playlist-env')

    def test_default_storage_keeps_local_behavior(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{},clear=True):
            self.assertEqual(storage_root(Path(folder)),Path(folder))

    def test_dashboard_with_container_environment_and_sigterm(self):
        import shutil
        import signal
        import socket
        import subprocess
        import sys
        import time
        import requests
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';root.mkdir()
            data=Path(folder)/'data'
            shutil.copy(Path(__file__).parent/'dashboard.html',root/'dashboard.html')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env={**os.environ,'RADIO_DATA_DIR':str(data),'DASHBOARD_BIND_HOST':'0.0.0.0','OAUTH_BIND_HOST':'0.0.0.0'}
            script='import dashboard,sys; from pathlib import Path; dashboard.ROOT=Path(sys.argv[1]); dashboard.serve(int(sys.argv[2]))'
            proc=subprocess.Popen([sys.executable,'-c',script,str(root),str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        response=requests.get(f'http://127.0.0.1:{port}/api/state',timeout=1)
                        break
                    except requests.ConnectionError:
                        time.sleep(.1)
                else:self.fail('Painel não iniciou.')
                self.assertEqual(response.status_code,200)
                self.assertTrue((data/'history.sqlite3').exists())
                self.assertFalse((root/'history.sqlite3').exists())
            finally:
                proc.send_signal(signal.SIGTERM)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            self.assertEqual(proc.returncode,0)
