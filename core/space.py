"""Spaces, and everyone's personal space (their home page).

A personal space is made the first time someone opens their home page, with a
"To-dos" app (to-dos and bookmarks) made from the hidden "personal" template.
The home page shows what the person chooses (``Space.config["home"]``): their
work across the apps (assigned to them, recently opened, starred), their
to-dos, bookmarks, pinned pages (with the Pages extension), notifications,
their spaces and their apps.
"""
import re

from django.db import transaction
from django.utils import timezone

from . import blueprints
from .formula import Records
from .models import App, RecentView, Space, SpaceMember, Star

# Values of a select that mean a record is finished (it leaves "Assigned to me").
CLOSED = {'done', 'closed', 'cancelled', 'canceled', 'received', 'completed', 'resolved', 'released', 'obsolete',
          'rejected', 'archived'}

HOME_SECTIONS = [
    ('work', 'Your work: assigned to you, recent, starred'),
    ('todos', 'My to-dos'),
    ('pages', 'Pinned pages'),
    ('bookmarks', 'Bookmarks'),
    ('notifications', 'Notifications'),
    ('spaces', 'Spaces'),
    ('apps', 'My apps and other apps'),
]


def home_sections(space):
    chosen = (space.config or {}).get('home')
    return [k for k, _ in HOME_SECTIONS] if chosen is None else chosen


# -- Spaces ------------------------------------------------------------------------

def make_key(name, taken=None):
    """A short unique key from a name: "Engineering team" -> "ET", "Engineering" -> "ENG"."""
    taken = taken if taken is not None else set(Space.objects.values_list('key', flat=True))
    words = re.findall(r'[A-Za-z0-9]+', name) or ['SPACE']
    base = ''.join(w[0] for w in words).upper() if len(words) > 1 else words[0][:3].upper()
    key, n = base, 2
    while key in taken:
        key, n = f'{base}{n}', n + 1
    return key


@transaction.atomic
def create_space(name, user, key='', kind=Space.Kind.TEAM, visibility=Space.Visibility.INTERNAL, description='',
                 icon='◼', color='#2e7d5b'):
    key = (key or make_key(name)).strip().upper()
    space = Space.objects.create(name=name, key=key, kind=kind, visibility=visibility, description=description,
                                 icon=icon or '◼', color=color or '#2e7d5b', created_by=user)
    if user is not None:
        SpaceMember.objects.create(space=space, user=user, role=Space.Role.ADMIN)
    return space


def space_apps(space):
    """The space's own apps, then the apps it added from other spaces."""
    own = list(space.apps.exclude(is_space=True).select_related('space'))
    added = [s.app for s in space.shortcuts.select_related('app__space')]
    return own, added


# -- Personal spaces ----------------------------------------------------------------

def personal_space(user):
    return Space.objects.filter(owner=user, kind=Space.Kind.PERSONAL).first()


@transaction.atomic
def ensure_personal(user):
    """The person's space, with its To-dos app, made the first time."""
    space = personal_space(user)
    if space is None:
        key = f'~{user.username}'[:20]
        n = 2
        while Space.objects.filter(key=key).exists():
            key, n = f'~{user.username}'[:17] + str(n), n + 1
        space = Space.objects.create(name=str(user), key=key, kind=Space.Kind.PERSONAL, visibility=Space.Visibility.PRIVATE,
                                     owner=user, icon='🏠', color='#0f766e', created_by=user,
                                     description='My own space: my to-dos, notes and apps.')
    if not App.objects.filter(space=space, is_space=True).exists():
        bp = blueprints.available(include_hidden=True)['personal']
        blueprints.install(bp, user=user, sample=True, name='To-dos', owner=user, is_space=True, space=space)
    return space


def todo_app(user):
    space = ensure_personal(user)
    return space.apps.filter(is_space=True).first()


def _table(app, key):
    return app.tables.filter(key=key).first() if app else None


def _field(data, table, key):
    return next((f for f in data.fields(table) if f.key == key), None) if table else None


def widgets(user, data):
    """To-dos and bookmarks from the person's space."""
    space = ensure_personal(user)
    app = space.apps.filter(is_space=True).first()
    todos_t, marks_t = _table(app, 'todos'), _table(app, 'bookmarks')
    out = {'personal': space, 'todo_app': app, 'todos': [], 'bookmarks': [], 'todo_table': todos_t, 'todo_count': 0}
    if todos_t:
        done, due = _field(data, todos_t, 'done'), _field(data, todos_t, 'due')
        out['todo_done_field'] = done
        today = timezone.localdate()
        rows = [r for r in data.records(todos_t) if not (done and data.value(r, done))]
        rows.sort(key=lambda r: ((data.value(r, due) is None), data.value(r, due) or today, r.pk) if due else (0, today, r.pk))
        for r in rows[:12]:
            d = data.value(r, due) if due else None
            out['todos'].append({'record': r, 'title': data.label(r), 'due': d, 'late': bool(d and d < today)})
        out['todo_count'] = len(rows)
    if marks_t:
        url = _field(data, marks_t, 'url')
        out['bookmarks'] = [{'title': data.label(r), 'url': data.value(r, url)} for r in data.records(marks_t) if url][:12]
    return out


def is_closed(data, record):
    for f in data.fields(record.table_id):
        if f.type == 'select':
            value = data.value(record, f)
            if value and str(value).lower() in CLOSED:
                return True
        elif f.type == 'checkbox' and f.key in ('done', 'received', 'closed', 'completed') and data.value(record, f):
            return True
    return False


def _when(data, record):
    """A record's due date (or a similar date), to sort what's assigned."""
    for f in data.fields(record.table_id):
        if f.type == 'date' and f.key in ('due', 'end', 'deadline'):
            v = data.value(record, f)
            if v:
                return v
    return None


def assigned(user, data, apps, limit=40):
    """Open records of the apps ``user`` can see in which they are in a user field (assignee, owner, ...)."""
    out = []
    for app in apps:
        if app.is_space:
            continue
        for table in app.tables.all():
            people = [f for f in data.fields(table) if f.type == 'user']
            if not people:
                continue
            for r in data.records(table):
                fields = [f for f in people if isinstance(data.value(r, f), Records) and user.pk in data.value(r, f).ids]
                if fields and not is_closed(data, r):
                    out.append({'record': r, 'title': data.label(r), 'table': table, 'app': app,
                                'as': ', '.join(f.name for f in fields), 'when': _when(data, r)})
    today = timezone.localdate()
    for item in out:
        item['late'] = bool(item['when'] and item['when'] < today)
    out.sort(key=lambda i: (i['when'] is None, i['when'] or today))
    return out[:limit]


def recent(user, data, limit=15):
    from .permissions import can
    out = []
    for v in RecentView.objects.filter(user=user).select_related('record__table__app__space')[:limit * 2]:
        app = v.record.table.app
        if can(user, app, 'viewer'):
            out.append({'record': v.record, 'title': data.label(data.record(v.record.pk)), 'table': v.record.table,
                        'app': app, 'when': v.viewed_at})
    return out[:limit]


def starred(user, data):
    from .permissions import can
    return [{'record': s.record, 'title': data.label(data.record(s.record.pk)), 'table': s.record.table, 'app': s.record.table.app}
            for s in Star.objects.filter(user=user).select_related('record__table__app__space') if can(user, s.record.table.app, 'viewer')]


def seen(user, record):
    """Remember that ``user`` opened ``record`` (the last 50 are kept)."""
    RecentView.objects.update_or_create(user=user, record=record)
    old = list(RecentView.objects.filter(user=user).values_list('pk', flat=True)[50:])
    if old:
        RecentView.objects.filter(pk__in=old).delete()
