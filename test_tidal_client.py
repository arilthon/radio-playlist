import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tidal_client import SCOPES, TidalClient


class TidalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'token.json'
        self.client = TidalClient('client', 'secret', 'http://localhost:8080/callback', 'BR', self.path)
        self.client.token = {'access_token': 'test', 'expires_at': time.time() + 3600}

    @patch('tidal_client.requests.request')
    def test_search_uses_relationship_order(self, request):
        request.return_value.json.return_value = {
            'data': [{'relationships': {'tracks': {'data': [{'type': 'tracks', 'id': '2'}]}}}],
            'included': [{'type': 'tracks', 'id': '1'}, {'type': 'tracks', 'id': '2'}],
        }
        self.assertEqual(self.client.search('Artist', 'Song')[0]['id'], '2')
        self.assertEqual(request.call_args_list[0].kwargs['params']['filter[query]'], 'artist Song')

    @patch('tidal_client.requests.request')
    def test_add_payload(self, request):
        self.client.add_track('uuid', '123')
        self.assertEqual(request.call_args.args, ('POST', 'https://openapi.tidal.com/v2/playlists/uuid/relationships/items'))
        self.assertEqual(request.call_args.kwargs['json'], {'data': [{'type': 'tracks', 'id': '123'}]})

    def test_callback_validation(self):
        self.assertEqual(self.client.callback_code('http://localhost:8080/callback?state=expected&code=ok', 'expected'), 'ok')
        for url in ['http://localhost:8080/callback?state=wrong&code=x', 'https://evil.test/?state=expected&code=x', 'http://localhost:8080/callback?state=expected&error=access_denied']:
            with self.assertRaises(ValueError):
                self.client.callback_code(url, 'expected')

    @patch('tidal_client.requests.post')
    def test_refresh_and_private_cache(self, post):
        self.client.token = {'refresh_token': 'refresh', 'expires_at': 0}
        post.return_value.json.return_value = {'access_token': 'new', 'expires_in': 3600}
        self.assertEqual(self.client.access_token(), 'new')
        self.assertEqual(post.call_args.kwargs['data']['grant_type'], 'refresh_token')
        self.assertEqual(json.loads(self.path.read_text())['refresh_token'], 'refresh')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        restored = TidalClient('client', 'secret', self.client.redirect_uri, 'BR', self.path)
        self.assertEqual(restored.access_token(), 'new')
        other = TidalClient('other', 'secret', self.client.redirect_uri, 'BR', self.path)
        self.assertEqual(other.token, {})

    @patch('tidal_client.HTTPServer')
    @patch('tidal_client.webbrowser.open')
    @patch('tidal_client.secrets.token_urlsafe', side_effect=['verifier', 'state'])
    @patch('tidal_client.requests.post')
    def test_authorization_pkce(self, post, random, browser, server):
        import io
        post.return_value.json.return_value = {'access_token': 'new', 'expires_in': 3600}
        def callback():
            handler_class = server.call_args.args[1]
            handler = object.__new__(handler_class)
            handler.path = '/callback?state=state&code=code'
            handler.wfile = io.BytesIO()
            handler.send_response = lambda status: None
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            handler.do_GET()
        server.return_value.handle_request.side_effect = callback
        with patch('builtins.print'):
            self.client.authorize()
        self.assertIn('code_challenge_method=S256', browser.call_args.args[0])
        self.assertEqual(post.call_args.kwargs['data']['code_verifier'], 'verifier')
        self.assertEqual(post.call_args.kwargs['data']['code'], 'code')
