"""Configurações por rádio, mantendo a configuração original do .env."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from dotenv import dotenv_values
from app_config import storage_root, environment_config


def data_dir(root, profile_id='default'):
    root = storage_root(root)
    if profile_id == 'default':
        return Path(root)
    if not re.fullmatch(r'[a-f0-9]{12}', profile_id):
        raise ValueError('Identificador de rádio inválido.')
    directory = Path(root) / 'stations' / profile_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def profiles(root):
    root = Path(root)
    values = environment_config(dotenv_values(root / '.env'))
    original = {'id': 'default', 'provider': 'tidal', 'name': 'Rádio principal',
                'url': values.get('RADIO_STREAM_URL') or '', 'playlist': values.get('PLAYLIST_ID') or ''}
    path = storage_root(root) / 'radios.json'
    return [original] + [{'provider':'tidal', **item} for item in (json.loads(path.read_text()) if path.exists() else [])]


def get_profile(root, profile_id):
    for profile in profiles(root):
        if profile['id'] == profile_id:
            return profile
    raise ValueError('Rádio não encontrada.')


def add_profile(root, name, url, playlist, provider='tidal'):
    if not all(isinstance(v, str) for v in (name, url, playlist)):
        raise ValueError('Preencha nome, URL e playlist.')
    name, url, playlist = name.strip(), url.strip(), playlist.strip()
    if not 1 <= len(name) <= 80 or len(url) > 2048:
        raise ValueError('Informe um nome de até 80 caracteres e uma URL válida.')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Use a URL direta do áudio com http:// ou https://.')
    if provider not in ('tidal','spotify'):
        raise ValueError('Selecione TIDAL ou Spotify.')
    from music_service import parse_playlist
    playlist = parse_playlist(playlist,provider)
    entries = profiles(root)[1:]
    if any(p['name'].casefold() == name.casefold() for p in profiles(root)):
        raise ValueError('Já existe uma rádio com esse nome.')
    profile = dict(id=uuid4().hex[:12], name=name, url=url, playlist=playlist, provider=provider)
    entries.append(profile)
    path = storage_root(root) / 'radios.json'
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump(entries, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return profile


def set_archived(root, profile_id, archived):
    if profile_id == 'default':
        raise ValueError('A rádio principal do .env não pode ser arquivada.')
    get_profile(root, profile_id)
    from instance_lock import acquire
    lock = acquire(data_dir(root, profile_id) / '.monitor.lock')
    try:
        entries = profiles(root)[1:]
        for entry in entries:
            if entry['id'] == profile_id:
                entry['archived'] = bool(archived)
        path = storage_root(root) / 'radios.json'
        temporary = path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump(entries, file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        lock.close()


def apply_profile(root, profile_id):
    profile = get_profile(root, profile_id)
    if profile.get('archived'):
        raise ValueError('Rádio arquivada. Restaure pelo painel antes de executar.')
    os.environ['MUSIC_PROVIDER'] = profile['provider']
    if profile_id != 'default':
        os.environ['RADIO_STREAM_URL'] = profile['url']
        os.environ['PLAYLIST_ID'] = profile['playlist']
    return data_dir(root, profile_id)
