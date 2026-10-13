import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.shortcuts import redirect

_ready = False
_migrated = False
_lock = threading.Lock()


def migrate_if_needed():
    """Apply database migrations that haven't been, however Osmia was started
    (serve.py, manage.py runserver, another WSGI server)."""
    global _migrated
    if _migrated:
        return
    with _lock:
        if _migrated:
            return
        from django.core.management import call_command
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            call_command('migrate', interactive=False, verbosity=0)
        _migrated = True


class SetupMiddleware:
    """Brings the database up to date, then, until there is an administrator,
    sends every page to the setup page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _ready
        migrate_if_needed()
        if not _ready:
            if get_user_model().objects.filter(is_superuser=True).exists():
                _ready = True
            elif not request.path.startswith(('/setup/', '/static/')):
                return redirect('core:setup')
        return self.get_response(request)
