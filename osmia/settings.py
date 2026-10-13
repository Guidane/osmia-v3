"""Osmia settings.

Everything Osmia stores (the database, uploaded files) is in one folder, ``data/``
(or ``OSMIA_DATA_DIR``). Set ``OSMIA_DEBUG=0``, ``OSMIA_SECRET_KEY`` and
``OSMIA_ALLOWED_HOSTS`` for real use.
"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('OSMIA_DATA_DIR') or BASE_DIR / 'data')
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEBUG = os.environ.get('OSMIA_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('OSMIA_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('Set the OSMIA_SECRET_KEY environment variable when OSMIA_DEBUG is off.')
    SECRET_KEY = 'django-insecure-local-development-only-do-not-deploy'
ALLOWED_HOSTS = [h for h in os.environ.get('OSMIA_ALLOWED_HOSTS', '').split(',') if h]
if DEBUG:
    ALLOWED_HOSTS += ['127.0.0.1', 'localhost', 'testserver']


# -- Extensions -------------------------------------------------------------------
# An extension is code: a Django app in extensions/<name>/ with an extension.json.
# Every extension found there is loaded, except those switched off on the
# Extensions page (kept in DATA_DIR/extensions.json; takes effect on restart).

EXTENSIONS_DIR = BASE_DIR / 'extensions'
EXTENSIONS_STATE = DATA_DIR / 'extensions.json'


def _extensions():
    try:
        disabled = set(json.loads(EXTENSIONS_STATE.read_text('utf-8')).get('disabled', []))
    except (OSError, ValueError):
        disabled = set()
    found = sorted(p.parent.name for p in EXTENSIONS_DIR.glob('*/extension.json'))
    return [name for name in found if name not in disabled]


OSMIA_EXTENSIONS = _extensions()

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'accounts',
    'core',
] + [f'extensions.{name}' for name in OSMIA_EXTENSIONS]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.SetupMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'osmia.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'core.context_processors.osmia',
        ],
    },
}]

WSGI_APPLICATION = 'osmia.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
        'OPTIONS': {'timeout': 20},
    }
}

# Accounts and passwords are Django's own: hashing, validation, password reset.
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'core:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Password reset mails. Without OSMIA_EMAIL_HOST they're printed on the console.
EMAIL_HOST = os.environ.get('OSMIA_EMAIL_HOST', '')
if EMAIL_HOST:
    EMAIL_PORT = int(os.environ.get('OSMIA_EMAIL_PORT', '587'))
    EMAIL_HOST_USER = os.environ.get('OSMIA_EMAIL_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('OSMIA_EMAIL_PASSWORD', '')
    EMAIL_USE_TLS = os.environ.get('OSMIA_EMAIL_TLS', '1') == '1'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = os.environ.get('OSMIA_EMAIL_FROM', 'osmia@localhost')

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('OSMIA_TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
MEDIA_ROOT = Path(os.environ.get('OSMIA_MEDIA_ROOT') or DATA_DIR / 'media')
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# The harness designer's view tab shows the designer in a frame of Osmia's own pages.
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Static files get ?v=<modification time> in their URL, so browsers never keep stale styles or scripts.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'core.storage.VersionedStaticStorage'},
}
