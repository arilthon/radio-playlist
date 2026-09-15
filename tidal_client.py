"""Cliente da API pública TIDAL com OAuth Authorization Code + PKCE."""
import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import requests
from matching import search_artist

SCOPES = 'playlists.write search.read'
TOKEN_URL = 'https://auth.tidal.com/v1/oauth2/token'
API_URL = 'https://openapi.tidal.com/v2'


class TidalClient:
    scopes = SCOPES
    token_url = TOKEN_URL
    authorize_url = 'https://login.tidal.com/authorize'
    api_url = API_URL
    content_type = 'application/vnd.api+json'
    rate_file = '.tidal-rate.json'
    use_secret = True
    loopback_hosts = ('localhost', '127.0.0.1')
    provider = 'tidal'
    def __init__(self, client_id, client_secret, redirect_uri, country, cache_path):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.country = country
        self.cache_path = Path(cache_path)
        self.token = {}
        if self.cache_path.exists():
            cached = json.loads(self.cache_path.read_text())
            if cached.get('client_id') == client_id and cached.get('requested_scope') == self.scopes:
                self.token = cached

    def _exchange(self, data):
        response = requests.post(self.token_url, data={**data, 'client_id': self.client_id},
                                 auth=(self.client_id, self.client_secret) if self.use_secret else None, timeout=15)
        response.raise_for_status()
        token = response.json()
        if not token.get('access_token'):
            raise ValueError('O serviço não retornou um token de acesso.')
        token.setdefault('refresh_token', self.token.get('refresh_token'))
        token.update(expires_at=time.time() + float(token['expires_in']),
                     client_id=self.client_id, requested_scope=self.scopes)
        self.token = token
        temporary = self.cache_path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump(token, file)
        os.replace(temporary, self.cache_path)

    def authorize(self):
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        state = secrets.token_urlsafe(32)
        url = self.authorize_url + '?' + urlencode({
            'response_type': 'code', 'client_id': self.client_id,
            'redirect_uri': self.redirect_uri, 'scope': self.scopes,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state,
        })
        parsed = urlparse(self.redirect_uri)
        if parsed.scheme != 'http' or parsed.hostname not in self.loopback_hosts:
            raise ValueError('Use uma Redirect URI HTTP com endereço local permitido e cadastre a mesma URL no painel do serviço.')
        received = {}
        client = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Não registrar códigos OAuth nos logs HTTP.

            def do_GET(self):
                if urlparse(self.path).path != parsed.path:
                    self.send_error(404)
                    return
                try:
                    received['code'] = client.callback_code(
                        f'{parsed.scheme}://{parsed.netloc}{self.path}', state)
                    status, message = 200, 'Autorizacao recebida. Volte ao terminal para acompanhar o programa.'
                except ValueError:
                    status, message = 400, 'Retorno de login invalido. Tente novamente pelo link exibido no terminal.'
                body = message.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            server = HTTPServer((os.environ.get('OAUTH_BIND_HOST','127.0.0.1'), parsed.port or 80), CallbackHandler)
        except OSError:
            raise ValueError('Nao foi possivel abrir a porta do callback. Feche outra instancia do programa ou configure outra porta no .env e no painel do serviço.') from None
        with server:
            server.timeout = 1
            print('Autorize o aplicativo no navegador:\n' + url, flush=True)
            print('Se o navegador nao abrir, copie o link acima e abra no navegador deste computador. Aguardando por ate 3 minutos...', flush=True)
            webbrowser.open(url)
            deadline = time.monotonic() + 180
            while 'code' not in received and time.monotonic() < deadline:
                server.handle_request()
        if 'code' not in received:
            raise ValueError('Tempo de login esgotado. Execute novamente e abra o link no navegador do mesmo computador.')
        code = received['code']
        self._exchange({'grant_type': 'authorization_code', 'code': code,
                        'redirect_uri': self.redirect_uri, 'code_verifier': verifier})

    def callback_code(self, callback, state):
        parsed, expected = urlparse(callback), urlparse(self.redirect_uri)
        if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
            raise ValueError('URL de retorno diferente de Redirect URI.')
        params = parse_qs(parsed.query)
        if not secrets.compare_digest(params.get('state', [''])[0], state):
            raise ValueError('Estado OAuth inválido. Inicie o login novamente.')
        if 'error' in params or not params.get('code'):
            raise ValueError('Autorização do serviço recusada ou sem código.')
        return params['code'][0]

    def access_token(self):
        import fcntl
        # Recarregar o token dentro da trava evita renovações concorrentes.
        with open(self.cache_path.with_suffix('.lock'), 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if self.cache_path.exists():
                cached = json.loads(self.cache_path.read_text())
                if cached.get('client_id') == self.client_id and cached.get('requested_scope') == self.scopes:
                    self.token = cached
            return self._access_token()

    def _access_token(self):
        if self.token.get('access_token') and self.token.get('expires_at', 0) > time.time() + 60:
            return self.token['access_token']
        if self.token.get('refresh_token'):
            self._exchange({'grant_type': 'refresh_token', 'refresh_token': self.token['refresh_token']})
        else:
            self.authorize()
        return self.token['access_token']

    def request(self, method, path, **kwargs):
        if hasattr(self, 'cache_path'):
            from tidal_coordination import account_gate
            with account_gate(self.cache_path.parent / self.rate_file):
                return self._request(method, path, **kwargs)
        return self._request(method, path, **kwargs)

    def _request(self, method, path, **kwargs):
        # Cache apenas de metadados: playlist continua sendo consultada antes de incluir.
        cacheable = method == 'GET' and not path.startswith('/playlists/')
        cache = getattr(self, '_metadata_cache', {})
        self._metadata_cache = cache
        key = (path, json.dumps(kwargs, sort_keys=True))
        now = time.monotonic()
        if cacheable and key in cache and now - cache[key][0] < 600:
            return copy.deepcopy(cache[key][1])
        wait = getattr(self, '_next_request', 0) - now
        if wait > 0:
            time.sleep(wait)
        self._next_request = time.monotonic() + 1.0
        response = requests.request(method, self.api_url + path, headers={
            'Authorization': 'Bearer ' + self.access_token(),
            'Accept': self.content_type, 'Content-Type': self.content_type,
        }, timeout=15, **kwargs)
        response.raise_for_status()
        result = response.json() if response.content else {}
        if cacheable:
            if len(cache) >= 256:
                cache.pop(next(iter(cache)))
            cache[key] = (time.monotonic(), copy.deepcopy(result))
        return result

    def search(self, artist, song):
        result = self.request('GET', '/searchResults', params={
            'filter[query]': f'{search_artist(artist)} {song}'[:256], 'countryCode': self.country, 'include': 'tracks',
        })
        resources = result.get('data', [])
        if not resources:
            return []
        refs = resources[0].get('relationships', {}).get('tracks', {}).get('data', [])
        included = {(item['type'], item['id']): item for item in result.get('included', [])}
        candidates = []
        for ref in refs[:10]:
            if ref['type'] != 'tracks':
                continue
            track = included.get(('tracks', ref['id']))
            if track:
                artists = self.request('GET', f"/tracks/{track['id']}/relationships/artists",
                                       params={'include': 'artists', 'countryCode': self.country})
                track['_artists'] = [a.get('attributes', {}).get('name', '')
                                     for a in artists.get('included', []) if a.get('type') == 'artists']
                candidates.append(track)
        return candidates

    def playlist_tracks(self, playlist):
        from urllib.parse import parse_qs, urlparse
        ids, cursor, seen = set(), None, set()
        while True:
            params = {'countryCode': self.country}
            if cursor:
                params['page[cursor]'] = cursor
            result = self.request('GET', f'/playlists/{playlist}/relationships/items', params=params)
            ids.update(item['id'] for item in result.get('data', []) if item.get('type') == 'tracks')
            link = result.get('links', {}).get('next')
            if not link:
                return ids
            if isinstance(link, dict):
                link = link.get('href', '')
            cursor = parse_qs(urlparse(link).query).get('page[cursor]', [None])[0]
            if not cursor or cursor in seen:
                raise ValueError('Paginação inesperada da playlist; inclusão interrompida para evitar duplicatas.')
            seen.add(cursor)

    def add_track(self, playlist, track_id):
        self.request('POST', f'/playlists/{playlist}/relationships/items',
                     json={'data': [{'type': 'tracks', 'id': str(track_id)}]})
