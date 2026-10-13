"""Asking serve.py to restart Osmia (after switching an extension on or off)."""
import os
import threading

RESTART_EXIT_CODE = 3


def request_restart(delay=1.0):
    """Exit with RESTART_EXIT_CODE shortly, after this response is sent. Under
    serve.py that starts Osmia again; otherwise the administrator restarts it."""
    if os.environ.get('OSMIA_SERVED') != '1':
        return False
    threading.Timer(delay, lambda: os._exit(RESTART_EXIT_CODE)).start()
    return True
