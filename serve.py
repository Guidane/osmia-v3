"""
Run Osmia as a server:  python serve.py [--host 0.0.0.0] [--port 8000] [--threads 8]

It applies database migrations, then serves Osmia with waitress (and its static
files) in a child process and looks after it:

- once a minute it runs what's due of the automations: schedules ("every
  Monday at 8:00") and dates reached ("the day before a task is due");
- when Osmia asks to restart (an extension was switched on or off on the
  Extensions page), it starts it again;
- Ctrl+C stops it.
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
RESTART_EXIT_CODE = 3


def say(text):
    print(text, flush=True)


def clock():
    """Run due automations every minute (in the serving process)."""
    from django.db import close_old_connections

    from core import automation
    while True:
        time.sleep(60 - time.time() % 60 + 1)
        try:
            close_old_connections()
            ran = automation.tick()
            if ran:
                say(f'Ran {ran} scheduled automation{"s" if ran != 1 else ""}.')
        except Exception as exc:  # the clock must keep going
            say(f'Scheduled automations failed: {exc}')


def child(host, port, threads):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'osmia.settings')
    os.environ['OSMIA_SERVED'] = '1'
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
    from django.contrib.staticfiles.handlers import StaticFilesHandler

    from osmia.wsgi import application
    threading.Thread(target=clock, daemon=True).start()
    app = StaticFilesHandler(application)
    say(f'Osmia is running on http://{host}:{port}/')
    try:
        from waitress import serve
    except ImportError:
        from wsgiref.simple_server import make_server
        say('waitress is not installed (pip install -r requirements.txt); using the basic Python server.')
        make_server(host, port, app).serve_forever()
        return
    serve(app, host=host, port=port, threads=threads, max_request_body_size=200 * 1024 ** 2)


def main():
    parser = argparse.ArgumentParser(description='Run Osmia.')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.host, args.port, args.threads)
        return
    while True:
        cmd = [sys.executable, __file__, '--child', '--host', args.host, '--port', str(args.port), '--threads', str(args.threads)]
        try:
            code = subprocess.call(cmd, cwd=BASE_DIR)
        except KeyboardInterrupt:
            say('Osmia stopped.')
            return
        if code == RESTART_EXIT_CODE:
            say('Restarting Osmia...')
            continue
        say(f'Osmia stopped (exit code {code}).')
        return


if __name__ == '__main__':
    main()
