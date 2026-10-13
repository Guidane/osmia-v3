"""Every change to records goes through here: grid edits, forms, the API,
buttons, imports, extensions and automations themselves.

Each change is validated (field types, required fields, which choice may
follow which), saved with its links, written to the record's history, and
then handed to the automation engine. An automation that blocks the change
("Stop the change with a message") undoes all of it; one that fails only
undoes its own steps.
"""
import threading
from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from . import automation
from .data import Data, OldValues
from .models import Attachment, Change, Comment, Field, Link, Record, Sequence

_local = threading.local()


class Blocked(ValidationError):
    """An automation stopped the change; the message says why."""


@contextmanager
def acting(source):
    """Changes made inside are logged as made by ``source`` (e.g. an automation)."""
    previous = getattr(_local, 'source', '')
    _local.source = source
    try:
        yield
    finally:
        _local.source = previous


def current_source():
    return getattr(_local, 'source', '')


# -- Values ---------------------------------------------------------------------------

def _field_for(data, table, name):
    if isinstance(name, Field):
        return name
    if isinstance(name, int) or (isinstance(name, str) and name.isdigit()):
        f = data.field(int(name))
        if f is not None and f.table_id == table.pk:
            return f
    found = next((f for f in data.fields(table) if f.key == name), None) or data.field_named(table, str(name))
    if found is None:  # the key, as the field was first named (keys don't change on rename)
        from django.utils.text import slugify
        slug = slugify(str(name)).replace('-', '_')
        found = next((f for f in data.fields(table) if f.key == slug), None)
    return found


def clean_values(data, table, values, force=False):
    """Split input into (stored {key: value}, links {field: [ids]}), cleaned.
    ``force`` (automations, imports) may also set read-only fields."""
    stored, links, errors = {}, {}, []
    for name, raw in (values or {}).items():
        field = _field_for(data, table, name)
        if field is None:
            errors.append(f'{table.name} has no field "{name}".')
            continue
        if field.type == 'link':
            try:
                links[field] = field.kind.clean(field, raw, data)
            except ValidationError as exc:
                errors.extend(exc.messages)
            continue
        if not field.kind.stored or not field.kind.editable:
            if field.type == 'autonumber' and force:
                pass
            else:
                continue  # computed: nothing to set
        if field.opt('readonly') and not force:
            errors.append(f'{field.name} is set by automations, not by hand.')
            continue
        try:
            stored[field.key] = field.kind.clean(field, raw, data) if field.type != 'autonumber' else raw
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)
    return stored, links


def _check_transitions(data, table, old_data, stored):
    for key, new in stored.items():
        field = next((f for f in data.fields(table) if f.key == key), None)
        if field is None or field.type != 'select':
            continue
        rules = field.opt('transitions') or {}
        old = (old_data or {}).get(key)
        if not rules or old == new or not old:
            continue
        allowed = rules.get(old)
        if allowed is not None and new not in allowed:
            raise ValidationError(f'{field.name} can\'t go from {old} to {new or "empty"}'
                                  + (f' (only to {", ".join(allowed)}).' if allowed else '.'))


def _check_required(data, table, record_data, links, record=None):
    missing = []
    for f in data.fields(table):
        if not f.required:
            continue
        if f.type == 'link':
            ids = links.get(f) if f in links else (data.linked_ids(record, f) if record else [])
            if not ids:
                missing.append(f.name)
        elif f.kind.stored and record_data.get(f.key) in (None, '', []):
            missing.append(f.name)
    if missing:
        raise ValidationError(f'Fill in {", ".join(missing)}.')


def _set_links(data, record, field, ids):
    owner, backwards = data.owner_of(field)
    other = data.field(field.opt('inverse'))
    if backwards:
        Link.objects.filter(field=owner, target=record).exclude(source_id__in=ids).delete()
        have = set(Link.objects.filter(field=owner, target=record).values_list('source_id', flat=True))
    else:
        Link.objects.filter(field=owner, source=record).exclude(target_id__in=ids).delete()
        have = set(Link.objects.filter(field=owner, source=record).values_list('target_id', flat=True))
    # A record on the other side that may have only one link leaves its old one.
    if other is not None and not other.opt('multiple') and ids:
        if backwards:
            Link.objects.filter(field=owner, source_id__in=ids).exclude(target=record).delete()
        else:
            Link.objects.filter(field=owner, target_id__in=ids).exclude(source=record).delete()
    new = []
    for position, rid in enumerate(ids):
        if rid in have:
            continue
        new.append(Link(field=owner, source_id=rid, target=record, position=position) if backwards
                   else Link(field=owner, source=record, target_id=rid, position=position))
    Link.objects.bulk_create(new)
    for position, rid in enumerate(ids):  # keep the order they were given in
        q = Link.objects.filter(field=owner, source_id=rid, target=record) if backwards else \
            Link.objects.filter(field=owner, source=record, target_id=rid)
        q.exclude(position=position).update(position=position)


def _texts(data, record, fields):
    return {f.pk: data.text(record, f) for f in fields}


def _log(table, record_id, label, action, changes=None, user=None):
    Change.objects.create(table=table, record_id=record_id, record_label=label[:200], action=action,
                          changes=changes or {}, user=user, source=current_source()[:200])


def _guard(table):
    """Automations of a person's own app don't write to apps they may only look at."""
    from .permissions import check_automation_write
    check_automation_write(automation.current_app(), table)


def _neighbours(data, record):
    ids = set()
    for f in data.fields(record.table_id):
        if f.type == 'link':
            ids.update(data.linked_ids(record, f))
    return ids


# -- Records ----------------------------------------------------------------------------

def next_number(field):
    seq, _ = Sequence.objects.select_for_update().get_or_create(field=field)
    seq.value += 1
    seq.save(update_fields=['value'])
    return seq.value


def create_record(table, values=None, user=None, data=None, force=False, run_automations=True):
    data = data or Data(user)
    table = data.table(table)
    _guard(table)
    with transaction.atomic():
        stored, links = clean_values(data, table, values, force=force)
        record_data = {}
        for f in data.fields(table):
            if f.kind.stored and f.type != 'autonumber':
                default = f.kind.default(f)
                if default not in (None, [], ''):
                    try:
                        record_data[f.key] = f.kind.clean(f, default, data)
                    except ValidationError:
                        pass  # a default that no longer fits the field
        record_data.update(stored)
        _check_required(data, table, record_data, links)
        for f in data.fields(table):
            if f.type == 'autonumber' and record_data.get(f.key) in (None, ''):
                record_data[f.key] = next_number(f)
        top = Record.objects.filter(table=table).aggregate(m=Max('position'))['m'] or 0
        record = Record.objects.create(table=table, data=record_data, created_by=user, updated_by=user, position=top + 1)
        for field, ids in links.items():
            _set_links(data, record, field, ids)
        data.invalidate()
        record = data.record(record.pk)
        _log(table, record.pk, data.label(record), Change.Action.CREATE,
             {f.name: ['', t] for f, t in ((f, data.text(record, f)) for f in data.fields(table)
                                           if f.kind.stored or f.type == 'link') if t}, user)
        if run_automations:
            automation.fire('record_created', record, data, user)
            automation.check_conditions(data, {record.pk} | _neighbours(data, record), user)
    return record


def update_record(record, values, user=None, data=None, force=False):
    data = data or Data(user)
    record = data.record(record)
    table = data.table(record.table_id)
    _guard(table)
    with transaction.atomic():
        stored, links = clean_values(data, table, values, force=force)
        old_data = dict(record.data or {})
        old_links = {f.pk: data.linked_ids(record, f) for f in links}
        stored = {k: v for k, v in stored.items() if old_data.get(k) != v}
        links = {f: ids for f, ids in links.items() if ids != old_links[f.pk]}
        if not stored and not links:
            return record
        _check_transitions(data, table, old_data, stored)
        new_data = {**old_data, **stored}
        _check_required(data, table, new_data, links, record)
        changed_fields = [f for f in data.fields(table) if f.key in stored or f in links]
        before = _texts(data, record, changed_fields)
        before_neighbours = _neighbours(data, record)
        record.data = new_data
        record.updated_by = user
        record.save(update_fields=['data', 'updated_by', 'updated_at'])
        for field, ids in links.items():
            _set_links(data, record, field, ids)
        data.invalidate()
        record = data.record(record.pk)
        after = _texts(data, record, changed_fields)
        diff = {f.name: [before[f.pk], after[f.pk]] for f in changed_fields if before[f.pk] != after[f.pk]}
        _log(table, record.pk, data.label(record), Change.Action.UPDATE, diff, user)
        old = OldValues(record, old_data, old_links)
        automation.fire('record_updated', record, data, user, old=old, changed={f.key for f in changed_fields})
        automation.check_conditions(data, {record.pk} | before_neighbours | _neighbours(data, record), user)
    return record


def delete_record(record, user=None, data=None):
    data = data or Data(user)
    record = data.record(record)
    table = data.table(record.table_id)
    _guard(table)
    with transaction.atomic():
        automation.fire('record_deleted', record, data, user)
        neighbours = _neighbours(data, record)
        label = data.label(record)
        _log(table, record.pk, label, Change.Action.DELETE,
             {f.name: [t, ''] for f, t in ((f, data.text(record, f)) for f in data.fields(table) if f.kind.stored) if t}, user)
        files = [a.file for a in record.attachments.all()]
        record.delete()
        transaction.on_commit(lambda: [f.delete(save=False) for f in files])
        data.invalidate()
        automation.check_conditions(data, neighbours, user)


def move_record(record, before_id=None, after_id=None):
    """Put a record between two others (drag and drop in grids and kanban)."""
    siblings = {r.pk: r.position for r in Record.objects.filter(table_id=record.table_id).only('pk', 'position')}
    if after_id and int(after_id) in siblings:
        lo = siblings[int(after_id)]
        higher = sorted(p for p in siblings.values() if p > lo)
        record.position = (lo + higher[0]) / 2 if higher else lo + 1
    elif before_id and int(before_id) in siblings:
        hi = siblings[int(before_id)]
        lower = sorted(p for p in siblings.values() if p < hi)
        record.position = (lower[-1] + hi) / 2 if lower else hi - 1
    record.save(update_fields=['position'])


def press_button(record, field, user=None, data=None):
    """Run the automation behind a button field. Returns the run (or None)."""
    data = data or Data(user)
    record = data.record(record)
    auto = field.opt('automation')
    from .models import Automation
    auto = Automation.objects.filter(pk=auto, active=True).first() if auto else None
    if auto is None:
        raise ValidationError(f'The button "{field.opt("label") or field.name}" has no automation to run.')
    with transaction.atomic():
        _log(data.table(record.table_id), record.pk, data.label(record), Change.Action.BUTTON,
             {'Button': ['', field.opt('label') or field.name]}, user)
        run = automation.run(auto, record, data, user, trigger='button', check=True)
    return run


def run_manually(auto, records, user=None):
    data = Data(user)
    runs = []
    with transaction.atomic():
        for record in records:
            runs.append(automation.run(auto, data.record(record), data, user, trigger='manual', check=True))
    return runs


# -- Files and comments --------------------------------------------------------------------

def add_comment(record, text, user):
    comment = Comment.objects.create(record=record, user=user, text=text.strip())
    data = Data(user)
    _log(record.table, record.pk, data.label(data.record(record.pk)), Change.Action.COMMENT, {'Comment': ['', text[:200]]}, user)
    automation.fire('comment_added', data.record(record.pk), data, user)
    return comment


def add_attachment(record, field, upload, user):
    from .uploads import store
    attachment = store(record, field, upload, user)
    data = Data(user)
    _log(record.table, record.pk, data.label(data.record(record.pk)), Change.Action.FILE,
         {field.name if field else 'Files': ['', f'+ {attachment.name}']}, user)
    automation.fire('record_updated', data.record(record.pk), data, user, changed={field.key} if field else set())
    return attachment


def remove_attachment(attachment, user):
    record = attachment.record
    name = attachment.name
    attachment.file.delete(save=False)
    attachment.delete()
    data = Data(user)
    _log(record.table, record.pk, data.label(data.record(record.pk)), Change.Action.FILE,
         {attachment.field.name if attachment.field_id else 'Files': [f'− {name}', '']}, user)


__all__ = ['Blocked', 'acting', 'create_record', 'update_record', 'delete_record', 'press_button', 'Attachment']
