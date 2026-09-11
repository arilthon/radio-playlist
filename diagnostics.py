"""Diagnósticos somente de leitura; não inicia autorização interativa."""
import json
from pathlib import Path

import requests
from dotenv import dotenv_values

from radio import obter_metadados_icecast, playlist_id
from tidal_client import TidalClient
from music_service import client_from_values, parse_playlist

ROOT = Path(__file__).resolve().parent


def diagnose(profile_id='default'):
    values = dotenv_values(ROOT / '.env')
    provider = 'tidal'
    if profile_id != 'default':
        from radio_profiles import get_profile
        profile = get_profile(ROOT, profile_id)
        provider = profile.get('provider','tidal')
        values.update(RADIO_STREAM_URL=profile['url'], PLAYLIST_ID=profile['playlist'])
    checks = []
    def add(name, ok, detail):
        checks.append({'name': name, 'ok': ok, 'detail': detail})
    fields = ('RADIO_STREAM_URL','PLAYLIST_ID') + (('SPOTIFY_CLIENT_ID',) if provider == 'spotify' else ('TIDAL_CLIENT_ID','TIDAL_CLIENT_SECRET'))
    missing = [key for key in fields if not values.get(key)]
    add('Configuração', not missing, 'Preencha: ' + ', '.join(missing) if missing else 'Campos obrigatórios preenchidos.')
    if values.get('RADIO_STREAM_URL'):
        try:
            title = obter_metadados_icecast(values['RADIO_STREAM_URL'])
            add('Rádio', bool(title), 'Título recebido: ' + title if title else 'Conectou, mas não recebeu título. Confira os metadados da emissora.')
        except Exception:
            add('Rádio', False, 'Falha ao ler ICY. Confira a URL direta do áudio e a conexão.')
    if missing:
        return checks
    try:
        pid = parse_playlist(values['PLAYLIST_ID'],provider)
        client = client_from_values(ROOT,provider,values)
        if not client.token:
            add('Login '+provider.upper(), False, 'Sem login salvo. Execute radio.py --profile '+profile_id+' --dry-run --once no terminal e autorize no navegador.')
            return checks
        client.access_token()
        add('Login '+provider.upper(), True, 'Token disponível e válido no cache ou renovado. A próxima consulta valida o acesso à API.')
        client.request('GET', f'/playlists/{pid}')
        add('Playlist', True, 'Playlist acessível para leitura. A permissão de escrita não foi testada para não alterar músicas.')
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else None
        detail = {429: 'Limite do serviço atingido. Aguarde antes de testar novamente.',
                  401: 'Login expirado ou revogado. Autorize novamente no terminal.',
                  403: 'Acesso negado. Confira permissões do aplicativo e da conta.',
                  404: 'Playlist não encontrada. Confira o link no .env.'}.get(status, 'Falha na conexão com o serviço. Confira credenciais e rede.')
        add(provider.upper(), False, detail)
    except Exception:
        add(provider.upper(), False, 'Configuração, ID da playlist ou cache inválido. Confira o .env e refaça o login se necessário.')
    return checks


if __name__ == '__main__':
    import sys
    print(json.dumps(diagnose(sys.argv[1] if len(sys.argv) > 1 else 'default'), ensure_ascii=False))
