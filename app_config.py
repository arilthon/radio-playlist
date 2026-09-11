"""Separa código, configuração e dados persistentes do aplicativo."""
import os
from pathlib import Path


def storage_root(root):
    path = Path(os.environ.get('RADIO_DATA_DIR') or root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def environment_config(values):
    # Somente as configurações do app; variáveis de processo não vão ao painel.
    keys = ('RADIO_STREAM_URL','PLAYLIST_ID','POLL_INTERVAL','TIDAL_CLIENT_ID',
            'TIDAL_CLIENT_SECRET','TIDAL_REDIRECT_URI','TIDAL_COUNTRY_CODE',
            'SPOTIFY_CLIENT_ID','SPOTIFY_REDIRECT_URI','SPOTIFY_COUNTRY_CODE')
    return {**values, **{key:os.environ[key] for key in keys if key in os.environ}}
