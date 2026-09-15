import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import requests
from history import History


class ReviewHTTPTests(unittest.TestCase):
    def test_csrf_approval_reprocessing_and_forgetting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copy(Path(__file__).parent / 'dashboard.html', root / 'dashboard.html')
            h = History(root / 'history.sqlite3')
            h.record('playlist','Artist - Song','incerta')
            event_id = h.db.execute('SELECT max(id) FROM events').fetchone()[0]
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
            code = 'import dashboard; from pathlib import Path; dashboard.ROOT=Path(__import__("sys").argv[1]); dashboard.serve(int(__import__("sys").argv[2]))'
            process = subprocess.Popen([sys.executable,'-c',code,str(root),str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            base=f'http://127.0.0.1:{port}'
            try:
                for _ in range(50):
                    try:
                        html=requests.get(base,timeout=1).text
                        break
                    except requests.ConnectionError:
                        time.sleep(.1)
                else:
                    self.fail('Painel não iniciou.')
                token=re.search("const csrf='([^']+)'",html).group(1)
                payload={'event_id':event_id,'track':'123','mode':'dry','profile':'default'}
                self.assertEqual(requests.post(base+'/api/approve',json=payload,timeout=2).status_code,403)
                headers={'X-CSRF-Token':token}
                radio = {'name':'Edit test','url':'https://radio.test/a','playlist':'a'*22,'provider':'spotify'}
                created = requests.post(base+'/api/radios',json=radio,headers=headers,timeout=2).json()
                edit = {**radio,'profile':created['id'],'name':'Edited','url':'https://radio.test/b'}
                self.assertEqual(requests.post(base+'/api/edit',json=edit,timeout=2).status_code,403)
                self.assertEqual(requests.post(base+'/api/edit',json=edit,headers=headers,timeout=2).status_code,200)
                radios = requests.get(base+'/api/radios',timeout=2).json()
                saved = next(p for p in radios if p['id']==created['id'])
                self.assertEqual(saved['name'],'Edited')
                self.assertEqual(saved['url'],'https://radio.test/b')
                self.assertEqual(requests.post(base+'/api/approve',json=payload,headers=headers,timeout=2).status_code,200)
                state=requests.get(base+'/api/state',timeout=2).json()
                self.assertEqual(state['learned'][0]['track_id'],'123')
                self.assertEqual(state['pending'][0][1],1)
                self.assertIsNone(h.next_pending('playlist',False))
                self.assertEqual(requests.post(base+'/api/reprocess',json={'event_id':event_id,'mode':'real'},headers=headers,timeout=2).status_code,200)
                self.assertIsNotNone(h.next_pending('playlist',False))
                self.assertEqual(requests.post(base+'/api/forget',json={'title':'Artist - Song'},headers=headers,timeout=2).status_code,200)
                self.assertIsNone(h.choice('Artist - Song'))
            finally:
                h.close()
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
