"""Impede dois monitores de processarem a mesma fila no Linux/WSL."""
import fcntl


def acquire(path):
    handle = open(path, 'a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError('Já existe um monitor ativo. Pare a outra instância antes de iniciar.') from None
    return handle


def running(path):
    try:
        handle = acquire(path)
    except ValueError:
        return True
    handle.close()
    return False
