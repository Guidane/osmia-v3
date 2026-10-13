"""Conditions on records, shared by view filters and automation conditions.

    {"match": "all" | "any",
     "rules": [{"field": "status", "op": "is", "value": "Placed"}, ...],
     "formula": "{Total} > 500"}            optional, must also hold

``field`` is a field key. ``value`` is text as typed; one that starts with
"=" is a formula (e.g. "=TODAY()" or "={trigger.Part}").
"""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from . import formula
from .formula import FormulaError, Records

OPS = {
    'is': 'is',
    'is_not': 'is not',
    'contains': 'contains',
    'not_contains': 'does not contain',
    'starts': 'starts with',
    'is_any_of': 'is any of',
    'is_none_of': 'is none of',
    'gt': '>',
    'gte': '≥',
    'lt': '<',
    'lte': '≤',
    'is_empty': 'is empty',
    'not_empty': 'is not empty',
    'checked': 'is checked',
    'unchecked': 'is not checked',
    'is_today': 'is today',
    'is_before_today': 'is before today',
    'is_after_today': 'is after today',
    'next_days': 'is in the next … days',
    'past_days': 'is in the past … days',
    'is_me': 'is me',
    # only in automations (they compare with the value before the change)
    'changed': 'changed',
    'changed_to': 'changed to',
    'changed_from': 'changed from',
}
NO_VALUE = {'is_empty', 'not_empty', 'checked', 'unchecked', 'is_today', 'is_before_today', 'is_after_today', 'is_me',
            'changed'}
CHANGE_OPS = ('changed', 'changed_to', 'changed_from')


def ops_for(field):
    ops = list(field.kind.filter_ops)
    return [(op, OPS[op]) for op in ops if op in OPS]


def _value(data, rule, record, extra):
    raw = rule.get('value', '')
    if isinstance(raw, str) and raw.startswith('='):
        return data.evaluate(raw, record, extra)
    return raw


def _items(value):
    if isinstance(value, list):
        return [formula.text(v).strip().lower() for v in formula.flatten(value)]
    return [s.strip().lower() for s in formula.text(value).split(',') if s.strip()]


def _same(actual, wanted):
    actual = formula.unwrap(actual)
    wanted = formula.unwrap(wanted)
    if isinstance(actual, Records) or isinstance(actual, list):
        return formula.text(wanted).strip().lower() in [formula.text(v).strip().lower() for v in actual]
    if isinstance(actual, (Decimal, int, float)) and not isinstance(actual, bool):
        try:
            return formula.num(actual) == formula.num(wanted)
        except FormulaError:
            return False
    if isinstance(actual, date):
        try:
            return formula.to_date(actual) == formula.to_date(wanted)
        except FormulaError:
            return False
    if isinstance(actual, bool):
        return actual == formula.truthy(wanted) if not isinstance(wanted, str) else \
            actual == (wanted.strip().lower() in ('1', 'true', 'yes', 'checked'))
    return formula.text(actual).strip().lower() == formula.text(wanted).strip().lower()


def test(op, actual, wanted=None, user=None, old=None):
    """Does a value pass one operator?"""
    blank = formula.is_blank(formula.unwrap(actual)) if not isinstance(actual, list) else not actual
    if op == 'is_empty':
        return blank
    if op == 'not_empty':
        return not blank
    if op == 'checked':
        return formula.truthy(actual)
    if op == 'unchecked':
        return not formula.truthy(actual)
    if op == 'is_me':
        return user is not None and isinstance(actual, Records) and user.pk in actual.ids
    if op == 'is':
        return blank if formula.is_blank(wanted) else _same(actual, wanted)
    if op == 'is_not':
        return (not blank) if formula.is_blank(wanted) else not _same(actual, wanted)
    if op in ('contains', 'not_contains'):
        needle = formula.text(wanted).strip().lower()
        if isinstance(actual, list):
            found = any(needle in formula.text(v).lower() for v in actual)
        else:
            found = needle in formula.text(actual).lower()
        return found if op == 'contains' else not found
    if op == 'starts':
        return formula.text(actual).lower().startswith(formula.text(wanted).strip().lower())
    if op in ('is_any_of', 'is_none_of'):
        options = set(_items(wanted))
        values = set(_items(actual)) if isinstance(actual, list) else {formula.text(actual).strip().lower()}
        hit = bool(options & values)
        return hit if op == 'is_any_of' else not hit
    if op in ('gt', 'gte', 'lt', 'lte'):
        if blank or formula.is_blank(formula.unwrap(wanted)):
            return False
        try:
            return formula.compare({'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}[op], actual, wanted)
        except FormulaError:
            return False
    if op in ('is_today', 'is_before_today', 'is_after_today', 'next_days', 'past_days'):
        try:
            d = formula.to_date(actual)
        except FormulaError:
            return False
        if d is None:
            return False
        today = timezone.localdate()
        if op == 'is_today':
            return d == today
        if op == 'is_before_today':
            return d < today
        if op == 'is_after_today':
            return d > today
        try:
            n = int(formula.num(wanted or 0))
        except FormulaError:
            return False
        if op == 'next_days':
            return today <= d <= today + timedelta(days=n)
        return today - timedelta(days=n) <= d <= today
    if op in CHANGE_OPS:
        if old is None:
            # a new record: everything it was given counts as changed
            changed = not blank
            before = None
        else:
            before = old
            changed = formula.text(before) != formula.text(actual)
        if op == 'changed':
            return changed
        if op == 'changed_to':
            return changed and _same(actual, wanted)
        return changed and old is not None and _same(before, wanted)
    return False


def matches(data, conditions, record, extra=None, old=None):
    """Does ``record`` meet ``conditions``? ``old`` (OldValues) is the record
    before the change, for the "changed" operators."""
    conditions = conditions or {}
    rules = [r for r in conditions.get('rules') or [] if r.get('field') and r.get('op')]
    results = []
    for rule in rules:
        field = next((f for f in data.fields(record.table_id) if f.key == rule['field']), None)
        if field is None:
            results.append(False)
            continue
        actual = data.value(record, field)
        try:
            wanted = None if rule['op'] in NO_VALUE else _value(data, rule, record, extra)
        except FormulaError:
            results.append(False)
            continue
        before = None
        if rule['op'] in CHANGE_OPS and old is not None:
            before = data._resolve_old(old, field.name)
        results.append(test(rule['op'], actual, wanted, user=data.user, old=before if old is not None else None))
    ok = True
    if results:
        ok = any(results) if conditions.get('match') == 'any' else all(results)
    expression = (conditions.get('formula') or '').strip()
    if ok and expression:
        try:
            ok = formula.truthy(data.evaluate(expression, record, extra))
        except FormulaError:
            ok = False
    return ok


def apply(data, records, conditions, extra=None):
    if not conditions or (not conditions.get('rules') and not (conditions.get('formula') or '').strip()):
        return records
    return [r for r in records if matches(data, conditions, r, extra)]


def describe(data, table, conditions):
    """In words, for lists of automations: "Status is Placed and Total > 500"."""
    parts = []
    for rule in (conditions or {}).get('rules') or []:
        field = next((f for f in data.fields(table) if f.key == rule.get('field')), None)
        if field is None:
            continue
        op = OPS.get(rule.get('op'), rule.get('op'))
        parts.append(f'{field.name} {op}' + ('' if rule.get('op') in NO_VALUE else f' {rule.get("value", "")}'))
    joiner = ' or ' if (conditions or {}).get('match') == 'any' else ' and '
    text = joiner.join(parts)
    if (conditions or {}).get('formula'):
        text = (text + ' and ' if text else '') + conditions['formula']
    return text
