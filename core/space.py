"""Spaces and everyone's home space.

A space is a record of a table marked ``is_space`` (a tree): a company, a
department, a team, a person, a programme, a project, ... Opening one shows
its page (a ``Layout`` made of blocks, see core.canvas) and what links to it.

Everyone's home space is the record of a space table whose home field (a user
field with ``options.home``) is them; it is made for them, at the top of the
tree, the first time they open Osmia, and an administrator moves it under
their team. What is "their work" (assigned to them, recently opened, starred)
is worked out across every app they can see.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone

from .formula import Records
from .models import Field, Layout, RecentView, Record, Star, Table

# Values of a select that mean a record is finished (it leaves "Assigned to me").
CLOSED = {'done', 'closed', 'cancelled', 'canceled', 'received', 'completed', 'resolved', 'released', 'obsolete',
          'rejected', 'archived'}


# -- Space tables -------------------------------------------------------------------

def space_tables():
    return list(Table.objects.filter(is_space=True, tree_field__isnull=False).select_related('app'))


def set_space(table, flag):
    """Make the records of the tree ``table`` spaces (or not)."""
    if flag and not table.tree_field_id:
        raise ValidationError(f'{table.name} is not a tree: pick its parent field first.')
    if table.is_space == bool(flag):
        return
    table.is_space = bool(flag)
    table.save(update_fields=['is_space'])
    # links into it now carry (or stop carrying) its tags
    from .access import refresh_tables
    linking = {f.table_id for f in Field.objects.filter(type='link') if f.opt('target') == table.pk}
    refresh_tables(linking | {table.pk})


def home_field(table):
    return next((f for f in Field.objects.filter(table=table, type='user') if f.opt('home')), None)


def _holds(value, user_id):
    return value == user_id or (isinstance(value, list) and user_id in value)


def home_node(user, create=True):
    """The person's home space (a record), made at the top of the first space table with a home field."""
    first = None
    for table in space_tables():
        field = home_field(table)
        if field is None:
            continue
        first = first or (table, field)
        for record in Record.objects.filter(table=table, data__has_key=field.key).order_by('pk'):
            if _holds(record.data.get(field.key), user.pk):
                return record
    if not create or first is None:
        return None
    from . import service
    from .data import Data
    table, field = first
    data = Data()
    values = {field.pk: user.pk}
    primary = data.primary_field(table)
    if primary is not None and primary.pk != field.pk and primary.kind.stored:
        values[primary.pk] = user.get_full_name() or user.username
    kind = next((f for f in data.fields(table) if f.key == 'kind' and f.type == 'select'), None)
    if kind is not None and any(c['value'] == 'Person' for c in kind.opt('choices') or []):
        values[kind.pk] = 'Person'
    return service.create_record(table, values, user=None, data=data, force=True, run_automations=False)


def is_space(record):
    table = record.table if hasattr(record, 'table') else None
    return bool(table and table.is_space and table.tree_field_id)


def layout_of(record=None, app=None):
    if record is not None:
        return Layout.objects.filter(record=record).first()
    return Layout.objects.filter(app=app).first()


def can_edit_page(user, record, data):
    """Editors of the space's app, and the people named in its people fields (its person, manager, ...)."""
    from .permissions import can
    table = data.table(record.table_id)
    if can(user, table.app, 'editor'):
        return True
    for f in data.fields(table):
        if f.type == 'user' and user.pk in (getattr(data.value(record, f), 'ids', None) or []):
            return True
    return False


def linked_here(data, record, tree):
    """What links to this space and to the spaces under it, by link field: [(field, table, [records])]."""
    nodes = [record] + [tree.records[i] for i in tree.descendant_ids(record.pk)]
    out = []
    for f in data.fields(record.table_id):
        if f.type != 'link' or f.opt('target') == record.table_id:
            continue
        target = data.table(f.opt('target'))
        if target is None:
            continue
        seen, found = set(), []
        for node in nodes:
            for r in data.linked(node, f):
                if r.pk not in seen:
                    seen.add(r.pk)
                    found.append(r)
        if found:
            out.append((f, target, found))
    return out


# -- Your work ----------------------------------------------------------------------

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
    """Open records of the apps ``user`` can see in which they are in a user field (assignee, owner, ...).
    Space tables are left out: being someone's home space or a team's manager isn't work."""
    out = []
    for app in apps:
        for table in app.tables.all():
            if table.is_space:
                continue
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
    for v in RecentView.objects.filter(user=user).select_related('record__table__app')[:limit * 2]:
        app = v.record.table.app
        record = data.record(v.record_id)
        if record is not None and can(user, app, 'viewer'):
            out.append({'record': record, 'title': data.label(record), 'table': v.record.table, 'app': app,
                        'when': v.viewed_at})
    return out[:limit]


def starred(user, data):
    from .permissions import can
    out = []
    for s in Star.objects.filter(user=user).select_related('record__table__app'):
        record = data.record(s.record_id)
        if record is not None and can(user, s.record.table.app, 'viewer'):
            out.append({'record': record, 'title': data.label(record), 'table': s.record.table, 'app': s.record.table.app})
    return out


def seen(user, record):
    """Remember that ``user`` opened ``record`` (the last 50 are kept)."""
    RecentView.objects.update_or_create(user=user, record=record)
    old = list(RecentView.objects.filter(user=user).values_list('pk', flat=True)[50:])
    if old:
        RecentView.objects.filter(pk__in=old).delete()
