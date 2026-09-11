"""Coordenação local dos limites da conta TIDAL entre processos."""
from contextlib import contextmanager
import fcntl
import json
import math
import time

import requests
from rate_limit import retry_delay


@contextmanager
def account_gate(path):
    with open(path, 'a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            state = json.load(handle)
        except (ValueError, TypeError):
            state = {}
        remaining = state.get('blocked_until', 0) - time.time()
        if remaining > 0:
            response = requests.Response()
            response.status_code = 429
            response.headers['Retry-After'] = str(math.ceil(remaining))
            raise requests.HTTPError('Pausa compartilhada do TIDAL.', response=response)
        time.sleep(max(0, min(1, state.get('next_request', 0) - time.time())))
        def save():
            handle.seek(0)
            handle.truncate()
            json.dump(state, handle)
            handle.flush()
        try:
            yield
        except requests.RequestException as exc:
            if exc.response is not None and exc.response.status_code == 429:
                state['blocked_until'] = time.time() + retry_delay(exc.response.headers.get('Retry-After'))
            raise
        finally:
            state['next_request'] = time.time() + 1
            save()
