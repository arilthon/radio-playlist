"""Seleção do serviço musical por rádio."""
import re
from app_config import storage_root
from tidal_client import TidalClient
from spotify_client import SpotifyClient, spotify_id


def client_from_values(root, provider, values):
    root = storage_root(root)
    country = (values.get('SPOTIFY_COUNTRY_CODE' if provider=='spotify' else 'TIDAL_COUNTRY_CODE') or 'BR').strip().upper()
    if not re.fullmatch('[A-Z]{2}',country):
        raise ValueError('O país do catálogo deve ter duas letras, por exemplo BR.')
    if provider == 'spotify':
        client_id = (values.get('SPOTIFY_CLIENT_ID') or '').strip()
        if not client_id:
            raise ValueError('Preencha SPOTIFY_CLIENT_ID no .env.')
        return SpotifyClient(client_id,None,values.get('SPOTIFY_REDIRECT_URI') or 'http://127.0.0.1:8081/callback',
                             country,root / '.spotify-cache.json')
    if provider != 'tidal':
        raise ValueError('Serviço inválido.')
    for field in ('TIDAL_CLIENT_ID','TIDAL_CLIENT_SECRET'):
        if not values.get(field):
            raise ValueError('Preencha '+field+' no .env.')
    return TidalClient(values['TIDAL_CLIENT_ID'],values['TIDAL_CLIENT_SECRET'],
                       values.get('TIDAL_REDIRECT_URI') or 'http://localhost:8080/callback',
                       country,root / '.tidal-cache.json')


def parse_playlist(value,provider):
    if provider == 'spotify':
        return spotify_id(value)
    from radio import playlist_id
    return playlist_id(value)
