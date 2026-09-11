"""Painel local: python dashboard.py e abra http://127.0.0.1:8090."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time

from history import History
from radio_status import summarize
from instance_lock import running
from radio_profiles import data_dir, profiles, get_profile, add_profile, set_archived
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent


class Controller:
    def __init__(self, profile_id='default'):
        self.profile_id = profile_id
        self.directory = data_dir(ROOT, profile_id)
        self.lock = threading.RLock()
        self.process = None
        self.mode = None
        self.log = None
        self.checks = []
        self.diagnosing = False
        self.last_diagnosis = 0

    def start(self, mode):
        with self.lock:
            if get_profile(ROOT,self.profile_id).get('archived'):
                raise ValueError('Rádio arquivada. Restaure antes de iniciar.')
            if running(self.directory / '.monitor.lock') or (self.process and self.process.poll() is None):
                raise ValueError('Já existe um monitor ativo.')
            if self.diagnosing:
                raise ValueError('Aguarde o diagnóstico terminar.')
            if mode not in ('real', 'dry', 'radio'):
                raise ValueError('Modo inválido.')
            if mode != 'radio':
                from dotenv import dotenv_values
                from music_service import client_from_values
                provider = get_profile(ROOT,self.profile_id).get('provider','tidal')
                client = client_from_values(ROOT,provider,dotenv_values(ROOT / '.env'))
                if not client.token.get('refresh_token') and not (
                    client.token.get('access_token') and client.token.get('expires_at',0)>time.time()+60
                ):
                    raise ValueError(f'Conclua o login {provider.upper()} no terminal antes de iniciar: '
                                     f'.venv/bin/python radio.py --profile {self.profile_id} --dry-run --once')
            if self.log:
                self.log.close()
            self.log = open(self.directory / '.dashboard.log', 'w')
            args = [sys.executable, '-u', str(ROOT / 'radio.py'), '--profile', self.profile_id]
            args += {'real': [], 'dry': ['--dry-run'], 'radio': ['--radio-only']}[mode]
            self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.log, stderr=self.log, stdin=subprocess.DEVNULL)
            self.mode = mode

    def stop(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait(timeout=5)

    def archive(self, archived=True):
        with self.lock:
            if self.profile_id == 'default':
                raise ValueError('A rádio principal do .env não pode ser arquivada.')
            if self.diagnosing:
                raise ValueError('Aguarde o diagnóstico terminar.')
            if self.process and self.process.poll() is None:
                self.stop()
            elif running(self.directory / '.monitor.lock'):
                raise ValueError('Pare a rádio no terminal original antes de arquivar.')
            set_archived(ROOT,self.profile_id,archived)

    def diagnose(self):
        with self.lock:
            if self.diagnosing or time.monotonic() - self.last_diagnosis < 60:
                raise ValueError('Aguarde pelo menos um minuto entre diagnósticos.')
            if running(self.directory / '.monitor.lock') or (self.process and self.process.poll() is None):
                raise ValueError('Pare o monitor antes do diagnóstico para evitar chamadas simultâneas ao serviço musical.')
            self.diagnosing = True
            self.last_diagnosis = time.monotonic()
        def work():
            try:
                result = subprocess.run([sys.executable, str(ROOT / 'diagnostics.py'), self.profile_id], cwd=ROOT,
                                        capture_output=True, text=True, timeout=60)
                self.checks = json.loads(result.stdout) if result.returncode == 0 else []
                if not self.checks:
                    raise ValueError()
            except Exception:
                self.checks = [{'name': 'Diagnóstico', 'ok': False, 'detail': 'Não terminou em tempo hábil. Confira a conexão da rádio e tente novamente.'}]
            finally:
                self.diagnosing = False
        threading.Thread(target=work, daemon=True).start()

    def review_action(self, action, body):
        history = History(self.directory / 'history.sqlite3')
        try:
            if action == 'forget':
                title = body.get('title')
                if not isinstance(title, str):
                    raise ValueError('Título inválido.')
                history.forget(title)
                return
            event_id = body.get('event_id')
            if not isinstance(event_id, int) or isinstance(event_id, bool):
                raise ValueError('Selecione um registro do histórico.')
            mode = body.get('mode', 'dry')
            if mode not in ('real', 'dry'):
                raise ValueError('Escolha simulação ou inclusão.')
            track_id, label = None, ''
            if action == 'approve':
                value = body.get('track', '')
                if not isinstance(value, str):
                    raise ValueError('Faixa inválida.')
                profile = get_profile(ROOT,self.profile_id)
                provider = profile.get('provider','tidal')
                if provider == 'spotify':
                    from spotify_client import spotify_id
                    track_id = spotify_id(value,'track')
                else:
                    if value.startswith(('http://','https://')):
                        parsed = urlparse(value)
                        if parsed.hostname not in ('tidal.com','www.tidal.com','listen.tidal.com') or '/track/' not in parsed.path:
                            raise ValueError('Use um link de faixa TIDAL.')
                        value = parsed.path.rstrip('/').split('/')[-1]
                    track_id = value.strip()
                label = body.get('label', '')
                if not isinstance(label, str):
                    raise ValueError('Nome da faixa inválido.')
            history.requeue(event_id, mode == 'dry', track_id, label, provider=provider if action=='approve' else 'tidal')
        finally:
            history.close()

    def state(self):
        history = History(self.directory / 'history.sqlite3')
        try:
            activities = history.activities()
            indicators = history.indicators()
            events = history.db.execute('SELECT created_at,status,title,track_id,score,id FROM events ORDER BY id DESC LIMIT 50').fetchall()
            reviews = history.review_items()
            learned = history.learned()
            latest = history.db.execute("SELECT title,created_at FROM events WHERE status='capturada' ORDER BY id DESC LIMIT 1").fetchone()
            if not latest:
                latest = history.db.execute("SELECT title,created_at FROM events WHERE status='detectada' ORDER BY id DESC LIMIT 1").fetchone()
            counts = dict(history.db.execute('SELECT status,count(*) FROM events GROUP BY status'))
            pending = history.db.execute('SELECT title,dry_run FROM pending ORDER BY id LIMIT 30').fetchall()
            count = history.db.execute('SELECT count(*) FROM pending').fetchone()[0]
        finally:
            history.close()
        owned = bool(self.process and self.process.poll() is None)
        notice = ''
        if self.process and self.process.poll() not in (None, 0):
            notice = ('Monitor encerrou com erro. Confira os avisos e o diagnóstico. Se faltar autorização, execute: '
                      f'.venv/bin/python radio.py --profile {self.profile_id} --dry-run --once')
        active = running(self.directory / '.monitor.lock') or owned
        return dict(running=active, owned=owned, detail=summarize(active,activities,indicators), indicators=indicators,
                    latest=latest, counts=counts, pending=pending, pending_count=count,
                    events=events, archived=get_profile(ROOT,self.profile_id).get('archived',False), provider=get_profile(ROOT,self.profile_id).get('provider','tidal'), mode=self.mode if owned else None, reviews=reviews, learned=learned, checks=self.checks, diagnosing=self.diagnosing, notice=notice)


def serve(port=8090):
    controllers = {'default': Controller()}
    registry_lock = threading.RLock()
    def controller_for(profile_id):
        with registry_lock:
            get_profile(ROOT, profile_id)
            if profile_id not in controllers:
                controllers[profile_id] = Controller(profile_id)
            return controllers[profile_id]
    csrf = secrets.token_urlsafe(32)
    host = f'127.0.0.1:{port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content='application/json'):
            data = body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get('Host') != host:
                return self.respond(403, {'error': 'Host inválido'})
            if self.path == '/':
                return self.respond(200, (ROOT / 'dashboard.html').read_text().replace('__CSRF__', csrf), 'text/html')
            parsed = urlparse(self.path)
            if parsed.path == '/api/state':
                try:
                    profile_id = parse_qs(parsed.query).get('profile', ['default'])[0]
                    return self.respond(200, controller_for(profile_id).state())
                except ValueError as exc:
                    return self.respond(400, {'error': str(exc)})
            if parsed.path == '/api/radios':
                items = []
                for profile in profiles(ROOT):
                    c = controller_for(profile['id'])
                    active = running(c.directory / '.monitor.lock') or bool(c.process and c.process.poll() is None)
                    history = History(c.directory / 'history.sqlite3')
                    try:
                        metrics = history.indicators()
                        detail = summarize(active,history.activities(),metrics)
                    finally:
                        history.close()
                    items.append({'id': profile['id'], 'name': profile['name'], 'running':active, 'archived':profile.get('archived',False), 'provider':profile.get('provider','tidal'),
                                  'detail':detail,'pending':metrics['queue_real']+metrics['queue_dry']})
                return self.respond(200, items)
            self.respond(404, {})

        def do_POST(self):
            if self.headers.get('Host') != host or self.headers.get('X-CSRF-Token') != csrf:
                return self.respond(403, {'error': 'Recarregue o painel.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 4096:
                    raise ValueError('Pedido inválido.')
                body = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError('Pedido inválido.')
                if self.path == '/api/radios':
                    with registry_lock:
                        created = add_profile(ROOT, body.get('name'), body.get('url'), body.get('playlist'), body.get('provider','tidal'))
                    return self.respond(200, {'ok': True, 'id': created['id']})
                controller = controller_for(body.get('profile', 'default'))
                if self.path == '/api/start':
                    with registry_lock:
                        controller.start(body.get('mode', 'dry'))
                elif self.path in ('/api/archive','/api/restore'):
                    with registry_lock:
                        controller.archive(self.path=='/api/archive')
                elif self.path == '/api/stop':
                    controller.stop()
                elif self.path == '/api/diagnose':
                    controller.diagnose()
                elif self.path in ('/api/approve', '/api/reprocess', '/api/forget'):
                    controller.review_action(self.path.rsplit('/', 1)[-1], body)
                else:
                    return self.respond(404, {})
                self.respond(200, {'ok': True})
            except ValueError as exc:
                self.respond(400, {'error': str(exc)})
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Painel: http://{host}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for controller in controllers.values():
            controller.stop()
        server.server_close()


if __name__ == '__main__':
    serve()
