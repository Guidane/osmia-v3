"""Automations: when <trigger>, if <conditions>, then <actions>.

They are built into the core: every change made through ``core.service``
(grid, forms, API, buttons, imports, extensions, other automations) is handed
to ``fire``. That is also how apps get their behaviour without code: an
order's "Place" button, booking received lines into stock, keeping a part's
average cost, or refusing an issue larger than what's on the shelf.

Values in actions are text with {Field} placeholders, or a formula when they
start with "=". In them:

    {Field}          the record the automation runs for (the trigger record)
    {old.Field}      its value before the change
    {this.Field}     the record an action is changing (update / upsert)
    {item.Field}     the linked record of a "for each" step
    {found.Field}    the record the last "find or create" step found

Actions are registered with ``@action``; extensions add their own through
``core.extensions.registry.action``.
"""
import json
import logging
import threading
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field as dc_field
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from . import filters, formula
from .formula import FormulaError, Records

log = logging.getLogger(__name__)
_local = threading.local()
MAX_DEPTH = 8

TRIGGERS = {
    'record_created': 'A record is created',
    'record_updated': 'A record is changed',
    'record_created_or_updated': 'A record is created or changed',
    'record_deleted': 'A record is about to be deleted',
    'condition_met': 'A record starts to meet the conditions',
    'button': 'A button is pressed (or run by hand)',
    'comment_added': 'A comment is added',
    'date_reached': 'A date in the record is reached',
    'schedule': 'On a schedule',
}
TRIGGER_HELP = {
    'record_updated': 'Pick fields to react only when one of them changes. Conditions can use "changed to".',
    'condition_met': 'Runs once when a record goes from not meeting the conditions to meeting them, e.g. when every '
                     'linked task is done, or when stock falls below the reorder level. Checked whenever the record or '
                     'a record linked to it changes.',
    'button': 'Put a Button field on the table and pick this automation; it also shows under "Run" on the record.',
    'date_reached': 'Runs once for each record on the day its date (plus the offset) comes.',
    'schedule': 'Runs for every record that meets the conditions, at the time you set.',
    'record_deleted': 'Runs before the record is gone, so actions can still read it. "Stop the change" keeps it.',
}


@dataclass
class Param:
    """One setting of an action, shown in the automation builder.

    type: text | template | formula | table | field | fields | values | target | link | users | teams |
          automation | select | bool
    """
    name: str
    label: str
    type: str = 'text'
    required: bool = False
    choices: tuple = ()
    help: str = ''


@dataclass
class Action:
    key: str
    label: str
    params: list
    run: object  # callable(ctx, step) -> text for the run log
    icon: str = '•'
    help: str = ''
    source: str = 'core'


ACTIONS = {}


def action(key, label, params=(), icon='•', help='', source='core'):
    def register(fn):
        ACTIONS[key] = Action(key, label, list(params), fn, icon, help, source)
        return fn
    return register


@dataclass
class Context:
    """What an automation run works with."""
    automation: object
    data: object
    record: object            # the trigger record (None for record-less schedules)
    user: object = None
    old: object = None        # OldValues, for record_updated
    trigger: str = ''
    extra: dict = dc_field(default_factory=dict)
    lines: list = dc_field(default_factory=list)

    def scope(self, **more):
        scope = {'trigger': self.record, 'old': self.old} if self.record is not None else {}
        scope.update({k: v for k, v in self.extra.items() if v is not None})
        scope.update({k: v for k, v in more.items() if v is not None})
        if self.old is None:
            scope.pop('old', None)
        return scope

    def value(self, raw, **more):
        """A param value: a formula when it starts with "=", else text with {placeholders}."""
        if isinstance(raw, str) and raw.startswith('='):
            return self.data.evaluate(raw, self.record, self.scope(**more))
        if isinstance(raw, str) and '{' in raw:
            return self.data.render(raw, self.record, self.scope(**more))
        return raw


# -- Running -------------------------------------------------------------------------

def _depth():
    return getattr(_local, 'depth', 0)


@contextmanager
def paused():
    """No automation runs inside, e.g. while changes are tried out and then undone
    (they could send emails or call webhooks that can't be undone)."""
    previous = getattr(_local, 'paused', False)
    _local.paused = True
    try:
        yield
    finally:
        _local.paused = previous


def _paused():
    return getattr(_local, 'paused', False)


def current_app():
    """The app of the automation running now (None outside automations)."""
    stack = getattr(_local, 'apps', None)
    return stack[-1] if stack else None


def _automations(table_id, trigger):
    from .models import Automation
    triggers = [trigger]
    if trigger in ('record_created', 'record_updated'):
        triggers.append('record_created_or_updated')
    return list(Automation.objects.filter(table_id=table_id, active=True, trigger__in=triggers).select_related('table__app'))


def fire(trigger, record, data, user=None, old=None, changed=None):
    """Run the automations of ``record``'s table that react to ``trigger``."""
    if _depth() >= MAX_DEPTH or _paused():
        return
    for auto in _automations(record.table_id, trigger):
        if trigger == 'record_updated':
            watched = set(auto.trigger_config.get('fields') or [])
            if watched and not (watched & set(changed or ())):
                continue
        run(auto, record, data, user, old=old, trigger=trigger)


def run(auto, record, data, user=None, old=None, trigger='', check=True, extra=None):
    """Run one automation for ``record``. Its steps happen together or not at all;
    "Stop the change" (Blocked) undoes the change that set it off too."""
    from .models import AutomationRun
    from .service import Blocked, acting
    outer, data = data, data.as_system()   # automations see every record, whoever set them off
    if record is not None:
        record = data.record(record.pk)
    if _depth() >= MAX_DEPTH:
        return AutomationRun.objects.create(automation=auto, record_id=getattr(record, 'pk', None), trigger=trigger,
                                            status=AutomationRun.Status.FAILED, user=user,
                                            log=f'Not run: automations set each other off more than {MAX_DEPTH} deep.')
    if check and record is not None and not filters.matches(data, auto.conditions, record, {'trigger': record}, old=old):
        if trigger in ('button', 'manual'):
            return AutomationRun.objects.create(automation=auto, record_id=record.pk, record_label=data.label(record)[:200],
                                                trigger=trigger, status=AutomationRun.Status.SKIPPED, user=user,
                                                log='The record does not meet the conditions: '
                                                    + filters.describe(data, auto.table, auto.conditions))
        return None
    ctx = Context(automation=auto, data=data, record=record, user=user, old=old, trigger=trigger, extra=dict(extra or {}))
    status = AutomationRun.Status.OK
    label = data.label(record)[:200] if record is not None else ''
    _local.depth = _depth() + 1
    if not hasattr(_local, 'apps'):
        _local.apps = []
    _local.apps.append(auto.table.app)
    try:
        with transaction.atomic(), acting(f'automation "{auto.name}"'):
            for i, step in enumerate(auto.actions or [], 1):
                act = ACTIONS.get(step.get('type'))
                if act is None:
                    raise ValidationError(f'Step {i}: the action "{step.get("type")}" is not available '
                                          '(was it part of an extension that is switched off?).')
                for_each = step.get('for_each')
                only_if = (step.get('if') or '').strip()
                if only_if and not for_each and not formula.truthy(data.evaluate(only_if, record, ctx.scope())):
                    ctx.lines.append(f'{act.label}: skipped ({only_if} is not true).')
                    continue
                if for_each and record is not None:
                    link = next((f for f in data.fields(record.table_id) if f.key == for_each), None)
                    if link is None:
                        raise ValidationError(f'Step {i}: there is no link field "{for_each}" to go through.')
                    items = data.linked(record, link)
                    if not items:
                        ctx.lines.append(f'{act.label}: no linked {link.name.lower()}, nothing to do.')
                    for item in items:
                        ctx.extra['item'] = item
                        if only_if and not formula.truthy(data.evaluate(only_if, record, ctx.scope())):
                            continue
                        ctx.lines.append(act.run(ctx, step) or act.label)
                    ctx.extra.pop('item', None)
                else:
                    ctx.lines.append(act.run(ctx, step) or act.label)
    except Blocked:
        raise
    except (ValidationError, FormulaError) as exc:
        status = AutomationRun.Status.FAILED
        msg = ' '.join(exc.messages) if isinstance(exc, ValidationError) else f'Formula: {exc}'
        ctx.lines.append(f'Failed: {msg}' + (' (the steps above were undone)' if ctx.lines else ''))
    except Exception as exc:  # a broken automation must never break the page that set it off
        status = AutomationRun.Status.FAILED
        log.exception('Automation %s failed', auto.pk)
        ctx.lines.append(f'Failed: {type(exc).__name__}: {exc}' + (' (the steps above were undone)' if ctx.lines else ''))
    finally:
        _local.depth = _depth() - 1
        _local.apps.pop()
    data.invalidate()
    outer.invalidate()
    return AutomationRun.objects.create(automation=auto, record_id=getattr(record, 'pk', None), record_label=label,
                                        trigger=trigger, status=status, log='\n'.join(ctx.lines), user=user)


def check_conditions(data, record_ids, user=None):
    """For "A record starts to meet the conditions": look at the changed record
    and its neighbours, and run for those that just started to meet them."""
    from .models import Automation, AutomationState, Record
    if _depth() >= MAX_DEPTH or _paused() or not record_ids:
        return
    autos = list(Automation.objects.filter(active=True, trigger='condition_met').select_related('table'))
    if not autos:
        return
    data = data.as_system()
    by_table = {}
    for a in autos:
        by_table.setdefault(a.table_id, []).append(a)
    records = Record.objects.filter(pk__in=record_ids, table_id__in=by_table).only('pk', 'table_id')
    for rec in records:
        record = data.record(rec.pk)
        if record is None:
            continue
        for auto in by_table[rec.table_id]:
            met = filters.matches(data, auto.conditions, record, {'trigger': record})
            state, created = AutomationState.objects.get_or_create(automation=auto, record_id=record.pk, defaults={'met': False})
            if met and not state.met:
                state.met = True
                state.save(update_fields=['met'])
                run(auto, record, data, user, trigger='condition_met', check=False)
            elif not met and state.met:
                state.met = False
                state.save(update_fields=['met'])


def prime_states(auto):
    """Remember which records already meet a "condition met" automation's
    conditions, so it only runs for records that start to meet them later."""
    from .data import Data
    from .models import AutomationState
    if auto.trigger != 'condition_met':
        return
    data = Data()
    AutomationState.objects.filter(automation=auto).delete()
    AutomationState.objects.bulk_create([
        AutomationState(automation=auto, record_id=r.pk, met=filters.matches(data, auto.conditions, r, {'trigger': r}))
        for r in data.records(auto.table)
    ])


def tick(now=None):
    """Run what's due: schedules and dates reached. Called every minute by
    serve.py, or by ``manage.py run_automations`` (e.g. from cron)."""
    from .data import Data
    from .models import Automation, AutomationState
    now = now or timezone.now()
    local = timezone.localtime(now)
    today = local.date()
    ran = 0
    for auto in Automation.objects.filter(active=True, trigger__in=['schedule', 'date_reached']).select_related('table'):
        cfg = auto.trigger_config or {}
        data = Data()
        if auto.trigger == 'date_reached':
            field = next((f for f in data.fields(auto.table) if f.key == cfg.get('field')), None)
            if field is None:
                continue
            at = cfg.get('at') or '00:00'
            if local.strftime('%H:%M') < at:
                continue
            offset = int(cfg.get('offset') or 0)
            for record in data.records(auto.table):
                try:
                    d = formula.to_date(data.value(record, field))
                except FormulaError:
                    continue
                if d is None or d + timedelta(days=offset) != today:
                    continue
                state, _ = AutomationState.objects.get_or_create(automation=auto, record_id=record.pk)
                if state.last_run == today:
                    continue
                state.last_run = today
                state.save(update_fields=['last_run'])
                if run(auto, record, data, None, trigger='date_reached') is not None:
                    ran += 1
            continue
        if not _due(cfg, local):
            continue
        cfg['last_run'] = local.isoformat()
        Automation.objects.filter(pk=auto.pk).update(trigger_config=cfg)
        if cfg.get('per_record', True):
            for record in data.records(auto.table):
                if run(auto, record, data, None, trigger='schedule') is not None:
                    ran += 1
        else:
            run(auto, None, data, None, trigger='schedule', check=False)
            ran += 1
    return ran


def _due(cfg, local):
    from datetime import datetime
    every = cfg.get('every', 'day')
    last = cfg.get('last_run')
    last = datetime.fromisoformat(last) if last else None
    if every == 'hour':
        return last is None or (local - last) >= timedelta(minutes=59)
    if local.strftime('%H:%M') < (cfg.get('at') or '08:00'):
        return False
    if last is not None and timezone.localtime(last).date() == local.date():
        return False
    if every == 'week':
        return local.isoweekday() == int(cfg.get('weekday') or 1)
    if every == 'month':
        return local.day == int(cfg.get('day') or 1)
    return True


# -- Helpers for actions ---------------------------------------------------------------------

def _table(ctx, step, key='table'):
    from .models import Table
    table_id = step.get(key)
    table = ctx.data.table(table_id) if table_id else ctx.data.table(ctx.automation.table_id)
    if table is None:
        raise ValidationError('The table this step works on no longer exists.')
    return table


def _targets(ctx, target):
    """'this' (the trigger record), 'item' (for each), 'found', or 'link:<field key>' (its linked records)."""
    target = target or 'this'
    if target == 'this':
        return [ctx.record] if ctx.record is not None else []
    if target in ('item', 'found'):
        rec = ctx.extra.get(target)
        return [rec] if rec is not None else []
    if target.startswith('link:'):
        base = ctx.extra.get('item') if target.startswith('link:item.') else ctx.record
        key = target.split(':', 1)[1].removeprefix('item.')
        if base is None:
            return []
        field = next((f for f in ctx.data.fields(base.table_id) if f.key == key), None)
        if field is None:
            raise ValidationError(f'There is no link field "{key}".')
        return ctx.data.linked(base, field)
    return []


def _values(ctx, table, values, this=None):
    out = {}
    for key, raw in (values or {}).items():
        field = next((f for f in ctx.data.fields(table) if f.key == key), None)
        if field is None:
            raise ValidationError(f'{table.name} has no field "{key}".')
        value = ctx.value(raw, this=this)
        if field.type == 'link':
            if isinstance(value, Records):
                value = value.ids
            elif value is not None and not isinstance(value, list):
                value = [value]
        elif field.type == 'user' and isinstance(value, Records):
            value = value.ids if field.opt('multiple') else (value.ids[0] if value.ids else None)
        elif isinstance(value, Records):
            value = formula.text(value)
        elif isinstance(value, list) and field.type not in ('multiselect', 'json'):
            value = formula.text(value)
        out[key] = value
    return out


def _who(ctx, step):
    """Users to tell: user fields of the record, fixed people and teams."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    User = get_user_model()
    ids = set()
    for key in step.get('user_fields') or []:
        if ctx.record is None:
            continue
        field = next((f for f in ctx.data.fields(ctx.record.table_id) if f.key == key), None)
        if field is not None:
            value = ctx.data.value(ctx.record, field)
            if isinstance(value, Records):
                ids.update(value.ids)
    ids.update(int(u) for u in step.get('users') or [] if str(u).isdigit())
    for team in Group.objects.filter(pk__in=[int(t) for t in step.get('teams') or [] if str(t).isdigit()]):
        ids.update(team.user_set.values_list('pk', flat=True))
    people = list(User.objects.filter(pk__in=ids, is_active=True))
    if ctx.record is not None and ctx.record.access:   # nobody is told about a record they can't see
        from .access import allows
        people = [u for u in people if allows(u, ctx.record.access, ctx.record.pk)]
    return people


# -- The built-in actions ----------------------------------------------------------------------

TARGET_HELP = 'This record, or the records linked to it through a link field.'
VALUES_HELP = 'Text with {Field} placeholders, or a formula starting with =, e.g. =NOW() or ={Quantity} * {Unit price}.'


@action('update_record', 'Change records', icon='✎', params=[
    Param('target', 'Which records', 'target', help=TARGET_HELP),
    Param('values', 'Set', 'values', required=True, help=VALUES_HELP + ' {this.Field} is the record being changed.'),
])
def update_record_action(ctx, step):
    from .service import update_record
    targets = _targets(ctx, step.get('target'))
    if not targets:
        return 'Change records: nothing to change.'
    names = []
    for target in targets:
        table = ctx.data.table(target.table_id)
        values = _values(ctx, table, step.get('values'), this=target)
        update_record(target, values, user=ctx.user, data=ctx.data, force=True)
        names.append(ctx.data.label(ctx.data.record(target.pk)))
    return f'Changed {", ".join(names[:5])}{"…" if len(names) > 5 else ""}'


SAVE_AS = Param('save_as', 'Remember it as', 'text',
                help='A name for later steps, e.g. "copy": they can use ={copy} to link to it and {copy.Field} for its values.')


@action('create_record', 'Create a record', icon='＋', params=[
    Param('table', 'In table', 'table', required=True),
    Param('values', 'With', 'values', help=VALUES_HELP + ' To link it to this record, set its link field to =RECORD_ID().'),
    SAVE_AS,
], help='Later steps can use the new record as {found.Field}, or by the name you give it.')
def create_record_action(ctx, step):
    from .service import create_record
    table = _table(ctx, step)
    values = _values(ctx, table, step.get('values'))
    record = create_record(table, values, user=ctx.user, data=ctx.data, force=True)
    ctx.extra['found'] = ctx.data.record(record.pk)
    if (step.get('save_as') or '').strip():
        ctx.extra[step['save_as'].strip()] = ctx.extra['found']
    return f'Created {table.name.lower()} "{ctx.data.label(ctx.data.record(record.pk))}"'


@action('find_or_create', 'Find or create a record', icon='🔎', params=[
    Param('table', 'In table', 'table', required=True),
    Param('match', 'Where', 'values', required=True, help='The record whose fields equal these values (formulas allowed).'),
    Param('values', 'When creating it, also set', 'values'),
    Param('update', 'When found, set', 'values'),
    Param('save_to', 'Then link it in this record\'s field', 'link'),
    SAVE_AS,
], help='Later steps can use the record as {found.Field}, or by the name you give it.')
def find_or_create_action(ctx, step):
    from .service import create_record, update_record
    table = _table(ctx, step)
    match = _values(ctx, table, step.get('match'))
    data = ctx.data

    def same(record):
        for key, wanted in match.items():
            field = next(f for f in data.fields(table) if f.key == key)
            actual = data.value(record, field)
            if field.type == 'link':
                if sorted(actual.ids if actual else []) != sorted(wanted or []):
                    return False
            elif not filters.test('is', actual, wanted):
                return False
        return True

    found = next((r for r in data.records(table) if same(r)), None)
    if found is None:
        found = create_record(table, {**match, **_values(ctx, table, step.get('values'))}, user=ctx.user, data=data, force=True)
        line = f'Created {table.name.lower()} "{data.label(data.record(found.pk))}"'
    else:
        if step.get('update'):
            update_record(found, _values(ctx, table, step.get('update'), this=found), user=ctx.user, data=data, force=True)
        line = f'Found {table.name.lower()} "{data.label(data.record(found.pk))}"'
    found = data.record(found.pk)
    ctx.extra['found'] = found
    if (step.get('save_as') or '').strip():
        ctx.extra[step['save_as'].strip()] = found
    if step.get('save_to') and ctx.record is not None:
        update_record(ctx.record, {step['save_to']: [found.pk]}, user=ctx.user, data=data, force=True)
    return line


@action('delete_record', 'Delete records', icon='🗑', params=[
    Param('target', 'Which records', 'target', help=TARGET_HELP),
])
def delete_record_action(ctx, step):
    from .service import delete_record
    targets = _targets(ctx, step.get('target'))
    names = [ctx.data.label(t) for t in targets]
    for t in targets:
        delete_record(t, user=ctx.user, data=ctx.data)
    return f'Deleted {", ".join(names)}' if names else 'Delete: nothing to delete.'


@action('block', 'Stop the change with a message', icon='⛔', params=[
    Param('message', 'Message', 'template', required=True, help='Shown to the person; {Field} placeholders work.'),
], help='Use with conditions, e.g. "Quantity on hand is less than 0": the change that set it off is undone.')
def block_action(ctx, step):
    from .service import Blocked
    raise Blocked(ctx.value(step.get('message') or 'This change is not allowed.') or 'This change is not allowed.')


@action('notify', 'Notify people', icon='🔔', params=[
    Param('user_fields', 'People in these fields', 'user_fields'),
    Param('users', 'These people', 'users'),
    Param('teams', 'These teams', 'teams'),
    Param('message', 'Message', 'template', required=True),
], help='Shown under 🔔 in the top bar.')
def notify_action(ctx, step):
    from .models import Notification
    people = _who(ctx, step)
    message = formula.text(ctx.value(step.get('message') or ''))[:500]
    url = ctx.record.get_absolute_url() if ctx.record is not None else ''
    Notification.objects.bulk_create(Notification(user=u, message=message, url=url, automation=ctx.automation) for u in people)
    return f'Notified {", ".join(str(u) for u in people)}: {message}' if people else 'Notify: nobody to notify.'


@action('send_email', 'Send an email', icon='✉', params=[
    Param('user_fields', 'To people in these fields', 'user_fields'),
    Param('users', 'To these people', 'users'),
    Param('teams', 'To these teams', 'teams'),
    Param('to', 'To these addresses', 'template', help='Comma separated; {Field} placeholders work.'),
    Param('subject', 'Subject', 'template', required=True),
    Param('body', 'Text', 'template', required=True),
])
def send_email_action(ctx, step):
    addresses = [u.email for u in _who(ctx, step) if u.email]
    addresses += [a.strip() for a in formula.text(ctx.value(step.get('to') or '')).split(',') if '@' in a]
    if not addresses:
        return 'Email: no addresses to send to.'
    subject = formula.text(ctx.value(step.get('subject') or ''))[:200]
    body = formula.text(ctx.value(step.get('body') or ''))
    transaction.on_commit(lambda: send_mail(subject, body, None, addresses, fail_silently=True))
    return f'Emailed {", ".join(addresses)}: {subject}'


@action('webhook', 'Call a web address (webhook)', icon='🌐', params=[
    Param('url', 'Address', 'template', required=True),
], help='POSTs the record as JSON ({"automation": ..., "record": {field: value}}) after the change is saved.')
def webhook_action(ctx, step):
    url = formula.text(ctx.value(step.get('url') or ''))
    if not url.startswith(('http://', 'https://')):
        raise ValidationError(f'"{url}" is not a web address.')
    payload = {'automation': ctx.automation.name, 'trigger': ctx.trigger}
    if ctx.record is not None:
        payload['record'] = {'id': ctx.record.pk, **{f.name: ctx.data.text(ctx.record, f) for f in ctx.data.fields(ctx.record.table_id)}}
    body = json.dumps(payload).encode()

    def send():
        try:
            req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=10).close()
        except Exception:
            log.warning('Webhook %s failed', url, exc_info=True)
    transaction.on_commit(lambda: threading.Thread(target=send, daemon=True).start())
    return f'Will call {url}'


@action('run_automation', 'Run another automation', icon='↪', params=[
    Param('automation', 'Automation', 'automation', required=True),
    Param('target', 'For which records', 'target', help=TARGET_HELP),
])
def run_automation_action(ctx, step):
    from .models import Automation
    other = Automation.objects.filter(pk=step.get('automation')).first()
    if other is None:
        raise ValidationError('The automation to run no longer exists.')
    lines = []
    for target in _targets(ctx, step.get('target')):
        if target.table_id != other.table_id:
            raise ValidationError(f'"{other.name}" runs on {other.table.name}, not on {ctx.data.table(target.table_id).name}.')
        result = run(other, target, ctx.data, ctx.user, trigger='automation')
        if result is not None and result.status == result.Status.FAILED:
            raise ValidationError(f'"{other.name}" failed: {result.log}')
        lines.append(ctx.data.label(target))
    return f'Ran "{other.name}" for {", ".join(lines)}' if lines else f'"{other.name}": no records to run for.'
