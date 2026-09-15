"""Spotify Web API: OAuth PKCE e formato de faixa comum ao monitor."""
import re
from urllib.parse import urlparse, parse_qs

from matching import search_artist
from tidal_client import TidalClient


def spotify_id(value, kind='playlist'):
    value = value.strip()
    if value.startswith(('http://','https://')):
        url = urlparse(value)
        parts = url.path.strip('/').split('/')
        if url.hostname != 'open.spotify.com' or len(parts) < 2 or parts[-2] != kind:
            raise ValueError(f'Use um link de {kind} do Spotify.')
        value = parts[-1]
    elif value.startswith('spotify:'):
        parts = value.split(':')
        if len(parts) != 3 or parts[1] != kind:
            raise ValueError('URI Spotify inválida.')
        value = parts[2]
    if not re.fullmatch(r'[A-Za-z0-9]{22}',value):
        raise ValueError(f'Informe o ID ou link de {kind} Spotify válido.')
    return value


class SpotifyClient(TidalClient):
    provider = 'spotify'
    scopes = 'playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative'
    token_url = 'https://accounts.spotify.com/api/token'
    authorize_url = 'https://accounts.spotify.com/authorize'
    api_url = 'https://api.spotify.com/v1'
    content_type = 'application/json'
    rate_file = '.spotify-rate.json'
    use_secret = False
    loopback_hosts = ('127.0.0.1',)

    @staticmethod
    def normalize_track(track):
        return {'type':'tracks','id':track['id'],
                'attributes':{'title':track.get('name',''),'version':''},
                '_artists':[a['name'] for a in track.get('artists',[])],
                'provider':'spotify'}

    def request(self, method, path, **kwargs):
        # O fluxo de revisão usa o mesmo formato de resposta nos dois serviços.
        if method == 'GET' and path.startswith('/tracks/'):
            params = kwargs.get('params', {})
            if 'countryCode' in params:
                kwargs['params'] = {**params,'market':params['countryCode']}
                kwargs['params'].pop('countryCode')
            result = super().request(method,path,**kwargs)
            return {'data':self.normalize_track(result)}
        return super().request(method,path,**kwargs)

    def search(self, artist, song):
        result = self.request('GET','/search',params={
            'q':f'{search_artist(artist)} {song}', 'type':'track', 'limit':10,'market':self.country})
        return [self.normalize_track(t) for t in result.get('tracks',{}).get('items',[]) if t and t.get('id')]

    def playlist_tracks(self, playlist):
        ids,offset,seen = set(),0,set()
        while True:
            result = self.request('GET',f'/playlists/{playlist}/items',params={'limit':50,'offset':offset,'market':self.country})
            for entry in result.get('items',[]):
                track = entry.get('item') or entry.get('track')
                if track and track.get('type') == 'track' and track.get('id'):
                    ids.add(track['id'])
            link = result.get('next')
            if not link:
                return ids
            try:
                offset = int(parse_qs(urlparse(link).query)['offset'][0])
            except (ValueError,KeyError,TypeError):
                raise ValueError('Paginação inesperada da playlist Spotify.') from None
            if offset in seen or offset <= 0:
                raise ValueError('Paginação repetida da playlist Spotify.')
            seen.add(offset)

    def add_track(self, playlist, track_id):
        self.request('POST',f'/playlists/{playlist}/items',json={'uris':['spotify:track:'+spotify_id(track_id,'track')]})
