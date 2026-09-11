import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spotify_client import SpotifyClient, spotify_id
from tidal_client import TidalClient
from radio_profiles import add_profile, profiles
from dashboard import Controller
from history import History

ID='a'*22


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.client=SpotifyClient('test',None,'http://127.0.0.1:8081/callback','BR',self.root/'.spotify-cache.json')

    def test_ids_and_wrong_provider_links(self):
        self.assertEqual(spotify_id('https://open.spotify.com/playlist/'+ID+'?si=x'),ID)
        self.assertEqual(spotify_id('spotify:track:'+ID,'track'),ID)
        with self.assertRaises(ValueError):spotify_id('https://tidal.com/playlist/'+ID)
        with self.assertRaises(ValueError):spotify_id('spotify:track:'+ID)

    def test_search_normalizes_artist_title_and_limit(self):
        self.client.request=Mock(return_value={'tracks':{'items':[{'id':ID,'name':'Song (Live)','artists':[{'name':'Artist'}]}]}})
        result=self.client.search('Artist','Song')
        self.assertEqual(result[0]['_artists'],['Artist'])
        self.assertEqual(result[0]['attributes']['title'],'Song (Live)')
        self.assertEqual(self.client.request.call_args.kwargs['params']['limit'],10)

    def test_playlist_pages_null_items_and_current_endpoint(self):
        self.client.request=Mock(side_effect=[{'items':[{'item':{'type':'track','id':ID}},{'item':None}], 'next':'https://api.spotify.com/v1/playlists/p/items?offset=50'}, {'items':[{'track':{'type':'track','id':'b'*22}}],'next':None}])
        self.assertEqual(self.client.playlist_tracks(ID),{ID,'b'*22})
        self.assertEqual(self.client.request.call_args.kwargs['params']['offset'],50)
        self.client.request=Mock()
        self.client.add_track(ID,ID)
        self.assertEqual(self.client.request.call_args.args,('POST',f'/playlists/{ID}/items'))
        self.assertEqual(self.client.request.call_args.kwargs['json'],{'uris':['spotify:track:'+ID]})

    @patch('tidal_client.requests.post')
    def test_pkce_exchange_and_refresh_use_spotify_without_secret(self,post):
        post.return_value.json.return_value={'access_token':'access','refresh_token':'refresh','expires_in':3600}
        self.client._exchange({'grant_type':'authorization_code','code':'code','code_verifier':'verify'})
        self.assertEqual(post.call_args.args[0],'https://accounts.spotify.com/api/token')
        self.assertIsNone(post.call_args.kwargs['auth'])
        self.assertEqual(post.call_args.kwargs['data']['code_verifier'],'verify')
        self.assertEqual(self.client.cache_path.stat().st_mode & 0o777,0o600)
        self.client.token['expires_at']=0
        self.client._access_token()
        self.assertEqual(post.call_args.kwargs['data']['grant_type'],'refresh_token')
        self.assertNotEqual(self.client.scopes,TidalClient.scopes)
        self.assertNotEqual(self.client.rate_file,TidalClient.rate_file)

    @patch('tidal_client.TidalClient.request',return_value={'id':ID,'name':'Song','artists':[{'name':'Artist'}]})
    def test_manual_track_response_common_format(self,request):
        r=self.client.request('GET','/tracks/'+ID,params={'countryCode':'BR'})
        self.assertEqual(r['data']['type'],'tracks')
        self.assertEqual(request.call_args.kwargs['params'],{'market':'BR'})

    def test_spotify_profile_manual_approval_and_legacy_default(self):
        p=add_profile(self.root,'Spotify rádio','https://radio.test/stream',ID,'spotify')
        self.assertEqual(profiles(self.root)[0]['provider'],'tidal')
        with patch('dashboard.ROOT',self.root):
            c=Controller(p['id'])
            h=History(c.directory/'history.sqlite3')
            self.addCleanup(h.close)
            h.record(ID,'Artist - Song','incerta')
            event=h.db.execute('SELECT max(id) FROM events').fetchone()[0]
            c.review_action('approve',dict(event_id=event,track='https://open.spotify.com/track/'+ID,mode='dry'))
            self.assertEqual(h.choice('Artist - Song')['id'],ID)
            self.assertEqual(c.state()['provider'],'spotify')
            with self.assertRaises(ValueError):
                c.review_action('approve',dict(event_id=event,track='https://tidal.com/browse/track/123',mode='dry'))

    @patch('tidal_client.HTTPServer')
    @patch('tidal_client.webbrowser.open')
    @patch('tidal_client.secrets.token_urlsafe', side_effect=['verifier','state'])
    @patch('tidal_client.requests.post')
    def test_spotify_authorize_uses_pkce_loopback_and_correct_scopes(self,post,random,browser,server):
        import io
        from urllib.parse import urlparse, parse_qs
        post.return_value.json.return_value={'access_token':'new','expires_in':3600}
        def callback():
            cls=server.call_args.args[1]
            handler=object.__new__(cls)
            handler.path='/callback?state=state&code=ok'
            handler.wfile=io.BytesIO()
            handler.send_response=lambda status:None
            handler.send_header=lambda *args:None
            handler.end_headers=lambda:None
            handler.do_GET()
        server.return_value.handle_request.side_effect=callback
        with patch('builtins.print'):
            self.client.authorize()
        url=urlparse(browser.call_args.args[0]); query=parse_qs(url.query)
        self.assertEqual(url.netloc,'accounts.spotify.com')
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertEqual(query['redirect_uri'],['http://127.0.0.1:8081/callback'])
        self.assertIn('playlist-modify-private',query['scope'][0])
        self.assertEqual(post.call_args.kwargs['data']['code_verifier'],'verifier')

    def test_spotify_rejects_localhost_redirect(self):
        self.client.redirect_uri='http://localhost:8081/callback'
        with self.assertRaises(ValueError):
            self.client.authorize()
