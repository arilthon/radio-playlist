"""Captura contínua independente do processamento da fila persistente."""
import logging
import threading
import time

import requests

from history import History
from rate_limit import retry_delay

LOG = logging.getLogger('radio')


def capture(url, playlist, path, dry_run, radio_only, reconnect_delay, stop, ready, stream):
    history = History(path)
    last = None
    heartbeat = 0
    try:
        while not stop.is_set():
            try:
                history.activity('capture','connecting')
                for title in stream(url):
                    if stop.is_set():
                        return
                    if time.monotonic() - heartbeat >= 5 or title and title != last:
                        history.activity('capture','listening')
                        heartbeat = time.monotonic()
                    if not title or title == last:
                        continue
                    if not radio_only:
                        history.enqueue(playlist, title, dry_run)
                    history.record(playlist, title, 'capturada')
                    last = title
                    LOG.info('Rádio: %s%s', title, '' if radio_only else ' (salva na fila)')
                    ready.set()
                if not stop.is_set():
                    history.activity('capture','reconnecting',message='A rádio encerrou a conexão.',retry_at=time.time()+reconnect_delay)
            except (OSError, ValueError, EOFError) as exc:
                history.activity('capture','reconnecting',message='Não foi possível ler o áudio/metadados. Confira o stream e a rede.',retry_at=time.time()+reconnect_delay)
                LOG.warning('Captura interrompida (%s); reconectando em %ss.', type(exc).__name__, reconnect_delay)
            if stop.wait(reconnect_delay):
                return
    finally:
        history.activity('capture','stopped')
        history.close()


def process_next(client, playlist, history, dry_run, processor):
    job = history.next_pending(playlist, dry_run)
    if not job:
        return False
    job_id, title, revision = job
    # Remover somente depois do processamento; falhas ficam para nova tentativa.
    history.activity('worker','processing',title=title,mode='dry' if dry_run else 'real')
    processor(client, playlist, title, dry_run, history)
    history.finish(job_id, revision)
    return True


def monitor(url, client, playlist, history, path, dry_run, radio_only, interval):
    from radio import stream_titles, processar
    stop, ready = threading.Event(), threading.Event()
    thread = threading.Thread(target=capture, args=(url, playlist, path, dry_run, radio_only,
                                                    interval, stop, ready, stream_titles), daemon=True)
    history.activity('worker','capture_only' if radio_only else 'idle',mode='radio' if radio_only else 'dry' if dry_run else 'real')
    history.activity('session','running',mode='radio' if radio_only else 'dry' if dry_run else 'real',started=time.time())
    thread.start()
    failures = 0
    try:
        while thread.is_alive():
            try:
                if not radio_only and process_next(client, playlist, history, dry_run, processar):
                    failures = 0
                    history.activity('worker','idle',mode='dry' if dry_run else 'real')
                    continue
                ready.wait(1)
                ready.clear()
            except requests.RequestException as exc:
                response = exc.response
                status = response.status_code if response is not None else None
                headers = response.headers if response is not None else {}
                failures += 1
                delay = retry_delay(headers.get('Retry-After'), failures) if status == 429 else 60
                history.activity('worker','rate_limited' if status == 429 else 'retrying',http_status=status,retry_at=time.time()+delay)
                LOG.warning('serviço musical HTTP %s: faixa mantida na fila. Nova tentativa em %ss; captura continua.', status, delay)
                if status in (400, 401, 403, 404):
                    history.activity('worker','error',http_status=status,message='Confira o login, as permissões e a faixa/playlist. Reinicie após corrigir.')
                    LOG.error('Corrija o acesso ao serviço musical e reinicie. A fila está salva.')
                    return 1
                # A thread de captura segue trabalhando durante esta espera.
                remaining = delay
                while remaining > 0:
                    part = min(30, remaining)
                    stop.wait(part)
                    remaining -= part
        history.activity('worker','error',message='A captura encerrou inesperadamente; reinicie a rádio.')
        LOG.error('Captura encerrada inesperadamente; fila preservada.')
        return 1
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        history.activity('worker','error',message='Processamento interrompido ('+type(exc).__name__+'). Confira o diagnóstico e as escolhas manuais.')
        raise
    finally:
        history.activity('session','stopped')
        stop.set()
        thread.join(timeout=1)
