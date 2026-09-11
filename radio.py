"""Captura metadados ICY e adiciona músicas a uma playlist TIDAL ou Spotify."""
import argparse
import logging
import os
from pathlib import Path
import re
import time
import urllib.request
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from tidal_client import TidalClient
from uuid import UUID
from history import History
from matching import choose_track
from rate_limit import retry_delay

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('radio')


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError('A rádio encerrou a conexão antes de enviar os metadados.')
        data.extend(chunk)
    return bytes(data)


def stream_titles(url, timeout=15, max_blocks=None):
    req = urllib.request.Request(url, headers={'Icy-MetaData': '1', 'User-Agent': 'RadioPlaylist/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        interval = int(response.headers.get('icy-metaint', 0))
        if not 0 < interval <= 2_000_000:
            raise ValueError('Stream sem icy-metaint válido. Use a URL direta do áudio com metadados ICY.')
        blocks = 0
        while max_blocks is None or blocks < max_blocks:
            blocks += 1
            read_exact(response, interval)
            size = read_exact(response, 1)[0] * 16
            if not size:
                if max_blocks is None:
                    yield None
                continue
            raw = read_exact(response, size).rstrip(b'\0')
            try:
                metadata = raw.decode('utf-8')
            except UnicodeDecodeError:
                metadata = raw.decode('latin-1')
            match = re.search(r"(?:^|;)\s*StreamTitle='(.*?)';", metadata)
            if match:
                title = match.group(1).strip()
                if title:
                    yield title
                elif max_blocks is None:
                    yield None
            elif max_blocks is None:
                yield None


def obter_metadados_icecast(url, timeout=15):
    stream = stream_titles(url, timeout, max_blocks=5)
    try:
        return next(stream, None)
    finally:
        stream.close()


def required(name):
    value = os.getenv(name, '').strip()
    if not value or value.startswith(('SEU_', 'ID_DA_', 'http://link-da-')):
        raise ValueError(f'Preencha {name} no arquivo .env.')
    return value


def playlist_id(value):
    value = value.split('?')[0].rstrip('/').split('/')[-1].split(':')[-1]
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError('PLAYLIST_ID deve ser o UUID ou link da playlist TIDAL.') from None


def processar(client, playlist, title, dry_run=False, history=None):
    if client is not None and isinstance(client, TidalClient):
        import fcntl
        from hashlib import sha256
        from app_config import storage_root
        path = storage_root(ROOT) / ('.playlist-' + sha256((client.provider+':'+playlist).encode()).hexdigest()[:24] + '.lock')
        with open(path, 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return _processar(client, playlist, title, dry_run, history)
    return _processar(client, playlist, title, dry_run, history)


def _processar(client, playlist, title, dry_run=False, history=None):
    def record(status, track_id=None, score=None):
        if history:
            history.record(playlist, title, status, track_id, score)
    record('detectada')
    learned = history.choice(title) if history else None
    parts = re.split(r'\s+[-–—]\s+', title, maxsplit=1)
    if not learned and (len(parts) != 2 or not all(parts)):
        record('ignorada')
        LOG.info('Ignorada (esperado Artista - Música): %s', title)
        return
    try:
        if learned:
            # Validar a faixa antes de usar uma escolha manual, sem busca aproximada.
            result = client.request('GET', f"/tracks/{learned['id']}", params={'countryCode': client.country})
            track = result.get('data')
            if not isinstance(track, dict) or track.get('type') != 'tracks' or str(track.get('id')) != learned['id']:
                raise ValueError('A faixa escolhida não foi retornada pelo serviço musical.')
            candidates, score = [], None
            LOG.info('Usando escolha salva: %s → serviço musical %s', title, learned['id'])
        else:
            candidates = client.search(*parts)
            if history:
                history.save_candidates(playlist, title, candidates)
            track, score = choose_track(*parts, candidates)
        if not track:
            status = 'incerta' if candidates else 'nao_encontrada'
            record(status, score=score)
            LOG.info('%s: %s (pontuação %.2f)', status, title, score)
            for candidate in candidates[:3]:
                attrs = candidate.get('attributes', {})
                LOG.info('Candidato serviço musical: %s — %s%s',
                         ', '.join(candidate.get('_artists', [])) or 'artista não informado',
                         attrs.get('title', ''),
                         ' [' + attrs['version'] + ']' if attrs.get('version') else '')
            return
        tid = track['id']
        if (history and history.contains(playlist, tid)) or tid in client.playlist_tracks(playlist):
            record('duplicada', tid, score)
            LOG.info('Já registrada ou presente na playlist: %s', title)
            return
        if dry_run:
            record('simulacao', tid, score)
            LOG.info('Simulação: %s (serviço musical %s, seleção %s)', title, tid, 'manual' if learned else score)
            return
        client.add_track(playlist, tid)
        record('adicionada', tid, score)
        LOG.info('Adicionada: %s (serviço musical %s)', title, tid)
    except Exception:
        record('erro')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--radio-only', action='store_true', help='Lê a rádio sem conectar ao serviço musical')
    parser.add_argument('--dry-run', action='store_true', help='Busca no serviço musical sem adicionar músicas')
    parser.add_argument('--once', action='store_true', help='Executa uma verificação e encerra')
    parser.add_argument('--history', action='store_true', help='Mostra os últimos 20 registros locais')
    parser.add_argument('--profile', default='default', help='ID da rádio cadastrada no painel')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    load_dotenv(ROOT / '.env')
    from radio_profiles import apply_profile
    try:
        directory = apply_profile(ROOT, args.profile)
    except ValueError as exc:
        LOG.error('%s', exc)
        return 1
    history = History(directory / 'history.sqlite3')
    if args.history:
        for row in history.recent():
            print(' | '.join('' if value is None else str(value) for value in row))
        history.close()
        return 0
    lock = None
    try:
        if not args.once:
            from instance_lock import acquire
            lock = acquire(directory / '.monitor.lock')
            from radio_profiles import get_profile
            if get_profile(ROOT,args.profile).get('archived'):
                raise ValueError('Rádio arquivada. Restaure pelo painel antes de executar.')
        url = required('RADIO_STREAM_URL')
        if urlparse(url).scheme not in ('http', 'https'):
            raise ValueError('RADIO_STREAM_URL deve começar com http:// ou https://.')
        interval = int(os.getenv('POLL_INTERVAL', '30'))
        if interval < 1:
            raise ValueError('POLL_INTERVAL deve ser um inteiro positivo.')
        client = playlist = None
        if not args.radio_only:
            from music_service import client_from_values, parse_playlist
            provider = os.getenv('MUSIC_PROVIDER','tidal')
            playlist = parse_playlist(required('PLAYLIST_ID'),provider)
            client = client_from_values(ROOT,provider,os.environ)
            if args.once:
                client.access_token()
        if not args.once:
            from pipeline import monitor
            return monitor(url, client, playlist or '', history, directory / 'history.sqlite3',
                           args.dry_run, args.radio_only, interval)
        last = None
        rate_failures = 0
        while True:
            delay = interval
            try:
                title = obter_metadados_icecast(url)
                if title and title != last:
                    LOG.info('Tocando agora: %s', title)
                    if not args.radio_only:
                        processar(client, playlist, title, args.dry_run, history)
                    else:
                        history.record('', title, 'detectada')
                    last = title
                    rate_failures = 0
                elif not title:
                    LOG.info('Nenhum título recebido nesta verificação.')
            except requests.RequestException as exc:
                response = getattr(exc, 'response', None)
                status = response.status_code if response is not None else getattr(exc, 'http_status', None)
                headers = response.headers if response is not None else (getattr(exc, 'headers', None) or {})
                if status == 429:
                    rate_failures += 1
                    delay = max(interval, retry_delay(headers.get('Retry-After'), rate_failures))
                    LOG.warning('Limite de requisições do serviço musical atingido (429). Aguarde %s segundos%s.',
                                delay, ' e execute novamente' if args.once else '; o app tentará novamente automaticamente')
                else:
                    LOG.error('Erro serviço musical/HTTP (status %s). Confira acesso, credenciais e playlist.', status)
                if status in (400, 401, 403, 404) or args.once:
                    return 1
            except (OSError, EOFError, ValueError) as exc:
                LOG.error('%s', exc)
                if args.once:
                    return 1
            if args.once:
                return 0
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                time.sleep(min(30, max(0, deadline - time.monotonic())))
    except (ValueError, OSError, EOFError) as exc:
        LOG.error('%s', exc)
        return 1
    except requests.RequestException:
        LOG.error('Falha no login do serviço musical. Confira as credenciais e o acesso do aplicativo; se o token foi revogado, refaça a autorização do serviço no terminal.')
        return 1
    except KeyboardInterrupt:
        LOG.info('Monitoramento encerrado.')
        return 0

    finally:
        history.close()
        if lock:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
