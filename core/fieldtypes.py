"""Field types: what a column holds, how it's entered, shown and worked out.

A type is registered once (``register``) and looked up by ``Field.type``.
Extensions can add their own with ``core.extensions.registry.field_type``.

    clean(field, raw, data)   form/API input -> the value stored in Record.data (or ValidationError)
    load(field, stored, data) stored value -> a typed value for formulas and display
    compute(field, record, data)   for types that aren't stored (formula, lookup, ...)
    html(field, value, data)  safe HTML to show the value
    text(field, value)        plain text (CSV, record names)
    raw(field, value, data)   the value as the cell editor wants it (JSON)
"""
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe

from . import formula
from .formula import FormulaError, Pair, Records

TYPES = {}

COLORS = ['#dbeafe', '#dcfce7', '#fef3c7', '#fee2e2', '#ede9fe', '#cffafe', '#fce7f3', '#e5e7eb',
          '#bfdbfe', '#bbf7d0', '#fde68a', '#fecaca', '#ddd6fe', '#a5f3fc', '#fbcfe8', '#d1d5db']


def register(cls):
    TYPES[cls.key] = cls()
    return cls


def get_type(key):
    return TYPES.get(key) or TYPES['text']


def choices_for_form():
    groups = {}
    for t in TYPES.values():
        if t.creatable:
            groups.setdefault(t.group, []).append((t.key, f'{t.icon} {t.label}'))
    return [(g, items) for g, items in groups.items()]


def fmt_number(value, decimals=None, thousands=True):
    if value is None or value == '':
        return ''
    value = formula.num(value)
    if decimals is not None:
        value = value.quantize(Decimal(1).scaleb(-int(decimals)), rounding=ROUND_HALF_UP)
    elif value == value.to_integral_value():
        value = value.quantize(Decimal(1))
    else:
        value = value.normalize()
    return f'{value:,f}' if thousands else f'{value:f}'


def json_number(value):
    """A Decimal as it's kept in JSON: int when whole, else float."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


class FieldType:
    key = ''
    label = ''
    icon = '•'
    group = 'Basic'
    stored = True          # kept in Record.data
    editable = True        # people can set it
    creatable = True       # offered on "New field"
    editor = 'text'        # which cell editor the grid uses
    align = ''             # 'num' right-aligns numbers in grids
    filter_ops = ('is', 'is_not', 'contains', 'not_contains', 'is_empty', 'not_empty')
    help = ''

    def clean(self, field, raw, data=None):
        if raw is None:
            return None
        if isinstance(raw, (list, dict)):
            raise ValidationError(f'{field.name}: expected text.')
        value = str(raw).strip()
        return value or None

    def load(self, field, stored, data=None):
        return stored

    def compute(self, field, record, data):
        return None

    def text(self, field, value):
        return formula.text(value)

    def html(self, field, value, data=None):
        return escape(self.text(field, value))

    def raw(self, field, value, data=None):
        if isinstance(value, Decimal):
            return json_number(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    def sort_key(self, value):
        value = formula.unwrap(value)
        if value is None or value == '' or value == []:
            return (1, '')
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (Decimal, int, float)):
            return (0, float(value))
        if isinstance(value, datetime):
            return (0, value.timestamp())
        if isinstance(value, date):
            return (0, value.toordinal())
        return (0, formula.text(value).lower())

    def default(self, field):
        return field.opt('default')


# -- Text ----------------------------------------------------------------------------

@register
class Text(FieldType):
    key, label, icon = 'text', 'Text', 'Aa'
    filter_ops = FieldType.filter_ops + ('starts', 'is_any_of')

    def clean(self, field, raw, data=None):
        value = super().clean(field, raw, data)
        if value and len(value) > 2000:
            raise ValidationError(f'{field.name}: at most 2000 characters (use a Long text field for more).')
        return value


@register
class LongText(FieldType):
    key, label, icon, editor = 'longtext', 'Long text', '¶', 'textarea'

    def clean(self, field, raw, data=None):
        if raw is None:
            return None
        value = str(raw).replace('\r\n', '\n').strip()
        return value or None

    def html(self, field, value, data=None):
        return mark_safe(escape(self.text(field, value)).replace('\n', '<br>'))


@register
class Email(Text):
    key, label, icon = 'email', 'Email', '@'

    def clean(self, field, raw, data=None):
        value = super().clean(field, raw, data)
        if value and ('@' not in value or ' ' in value):
            raise ValidationError(f'{field.name}: "{value}" is not an email address.')
        return value

    def html(self, field, value, data=None):
        return format_html('<a href="mailto:{0}">{0}</a>', value) if value else ''


@register
class Url(Text):
    key, label, icon = 'url', 'Link (URL)', '🔗'

    def clean(self, field, raw, data=None):
        value = super().clean(field, raw, data)
        if value and '://' not in value and not value.startswith(('/', 'mailto:', 'tel:')):
            value = 'https://' + value
        return value

    def html(self, field, value, data=None):
        if not value:
            return ''
        shown = value.split('://', 1)[-1].rstrip('/')
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', value, shown[:60])


@register
class Phone(Text):
    key, label, icon = 'phone', 'Phone', '☎'

    def html(self, field, value, data=None):
        return format_html('<a href="tel:{0}">{0}</a>', value) if value else ''


@register
class Color(Text):
    key, label, icon, editor = 'color', 'Colour', '🎨', 'color'

    def clean(self, field, raw, data=None):
        value = super().clean(field, raw, data)
        if value and not (len(value) in (4, 7) and value.startswith('#')):
            raise ValidationError(f'{field.name}: a colour is written like #3b82f6.')
        return value

    def html(self, field, value, data=None):
        return format_html('<span class="swatch" style="background:{0}"></span> {0}', value) if value else ''


@register
class Json(FieldType):
    key, label, icon, editor, group = 'json', 'JSON', '{}', 'textarea', 'Advanced'
    filter_ops = ('is_empty', 'not_empty')

    def clean(self, field, raw, data=None):
        if raw is None or raw == '':
            return None
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                raise ValidationError(f'{field.name}: not valid JSON.')
        return raw

    def text(self, field, value):
        return json.dumps(value) if value is not None else ''

    def html(self, field, value, data=None):
        if value is None:
            return ''
        shown = json.dumps(value)
        return format_html('<code class="json">{}</code>', shown[:80] + ('…' if len(shown) > 80 else ''))

    def raw(self, field, value, data=None):
        return json.dumps(value, indent=2) if value is not None else ''


@register
class Attributes(FieldType):
    """Name-value pairs, each shown as a tag: Resistance 10 kΩ, Power 0.1 W. Kept as [{"name", "value"}];
    read (in formulas, filters, search, CSV) as "Resistance: 10 kΩ, Power: 0.1 W"."""
    key, label, icon, editor = 'attributes', 'Attributes (name: value)', '🏷', 'attributes'
    filter_ops = ('contains', 'not_contains', 'is_empty', 'not_empty')
    help = 'Name-value pairs, each a tag: Resistance 10 kΩ, Power 0.1 W.'
    NAME, VALUE = 60, 200   # longest name and value

    @staticmethod
    def _split(line):
        """"Resistance: 10 kΩ" (or "Resistance = 10 kΩ") → (name, value)."""
        for sep in (':', '='):
            if sep in line:
                name, value = line.split(sep, 1)
                return name, value
        return line, ''

    def clean(self, field, raw, data=None):
        if raw is None or raw == '':
            return []
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped[:1] in '[{':
                try:
                    raw = json.loads(stripped)
                except ValueError:
                    pass
        if isinstance(raw, dict):
            items = list(raw.items())
        elif isinstance(raw, str):
            items = [self._split(line) for line in raw.replace(';', '\n').splitlines()]
        else:
            items = []
            for item in raw if isinstance(raw, list) else [raw]:
                if isinstance(item, Pair):
                    items.append((item.name, item.value))
                elif isinstance(item, dict):
                    items.append((item.get('name', ''), item.get('value', '')))
                elif isinstance(item, (list, tuple)) and item:
                    items.append((item[0], item[1] if len(item) > 1 else ''))
                else:
                    items.append(self._split(str(item)))
        out, seen = [], set()
        for name, value in items:
            name = ' '.join(str(name if name is not None else '').split())
            value = ' '.join(str(value if value is not None else '').split())
            if not name:
                if value:
                    raise ValidationError(f'{field.name}: "{value}" needs a name.')
                continue
            if len(name) > self.NAME or len(value) > self.VALUE:
                raise ValidationError(f'{field.name}: a name is at most {self.NAME} characters, a value {self.VALUE}.')
            if name.lower() in seen:
                raise ValidationError(f'{field.name}: two attributes are called "{name}".')
            seen.add(name.lower())
            out.append({'name': name, 'value': value})
        return out

    def load(self, field, stored, data=None):
        return [Pair(p.get('name', ''), p.get('value', '')) for p in stored or [] if isinstance(p, dict)]

    def text(self, field, value):
        return ', '.join(value or [])

    def html(self, field, value, data=None):
        return format_html_join('', '<span class="attr-tag"><span class="attr-name">{}</span>{}</span>',
                                ((p.name, format_html(' {}', p.value) if p.value != '' else '') for p in value or []))

    def raw(self, field, value, data=None):
        return [{'name': p.name, 'value': p.value} for p in value or []]

    def sort_key(self, value):
        return (1, '') if not value else (0, self.text(None, value).lower())

    def default(self, field):
        return []

    def names(self, field, limit=2000):
        """The attribute names to suggest: those used in this field so far, and those its source lists."""
        from .models import Record
        found = {}
        source = self.source(field)
        for f in [field] + ([source[1]] if source else []):
            for stored in Record.objects.filter(table_id=f.table_id).values_list('data', flat=True)[:limit]:
                for p in (stored or {}).get(f.key) or []:
                    if isinstance(p, dict) and p.get('name'):
                        found.setdefault(p['name'].lower(), p['name'])
        return sorted(found.values(), key=str.lower)

    def source(self, field):
        """(link field, attributes field of the linked table) named by ``names_from`` ("category.attribute_names"):
        where the attributes a record should fill in are listed. None if it isn't set (or is gone)."""
        from .models import Field
        link_key, _, attr_key = str(field.opt('names_from') or '').partition('.')
        if not link_key or not attr_key:
            return None
        link = Field.objects.filter(table_id=field.table_id, key=link_key, type='link').first()
        if link is None:
            return None
        listed = Field.objects.filter(table_id=link.opt('target'), key=attr_key, type='attributes').first()
        return (link, listed) if listed else None

    def expected(self, field, record, data):
        """What ``record`` should fill in: the attributes its linked records (its category) list, each with the hint
        for its value, [{"name", "hint"}]."""
        source = self.source(field)
        if source is None:
            return []
        link, listed = source
        out, seen = [], set()
        for linked in data.linked(record, link):
            for p in data.raw(linked, listed) or []:
                if p['name'].lower() not in seen:
                    seen.add(p['name'].lower())
                    out.append({'name': p['name'], 'hint': p['value']})
        return out


# -- Numbers ---------------------------------------------------------------------------

@register
class Number(FieldType):
    key, label, icon, group, editor, align = 'number', 'Number', '#', 'Number', 'number', 'num'
    filter_ops = ('is', 'is_not', 'gt', 'gte', 'lt', 'lte', 'is_empty', 'not_empty')

    def decimals(self, field):
        d = field.opt('decimals')
        return int(d) if d not in (None, '') else None

    def clean(self, field, raw, data=None):
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        try:
            value = formula.num(raw)
        except FormulaError:
            raise ValidationError(f'{field.name}: "{raw}" is not a number.')
        if not value.is_finite():
            raise ValidationError(f'{field.name}: "{raw}" is not a number.')
        d = self.decimals(field)
        if d is not None:
            value = value.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
        lo, hi = field.opt('min'), field.opt('max')
        if lo not in (None, '') and value < Decimal(str(lo)):
            raise ValidationError(f'{field.name}: at least {lo}.')
        if hi not in (None, '') and value > Decimal(str(hi)):
            raise ValidationError(f'{field.name}: at most {hi}.')
        return json_number(value)

    def load(self, field, stored, data=None):
        if stored is None or stored == '':
            return None
        try:
            return Decimal(str(stored))
        except InvalidOperation:
            return None

    def text(self, field, value):
        return fmt_number(value, self.decimals(field), thousands=False) if value is not None else ''

    def html(self, field, value, data=None):
        return fmt_number(value, self.decimals(field)) if value is not None else ''


@register
class Currency(Number):
    key, label, icon = 'currency', 'Currency', '€'

    def decimals(self, field):
        d = field.opt('decimals')
        return 2 if d in (None, '') else int(d)

    def html(self, field, value, data=None):
        if value is None:
            return ''
        symbol = field.opt('symbol', '€')
        text = fmt_number(value, self.decimals(field))
        return f'-{symbol}{text[1:]}' if text.startswith('-') else f'{symbol}{text}'


@register
class Percent(Number):
    key, label, icon = 'percent', 'Percent', '%'

    def html(self, field, value, data=None):
        if value is None:
            return ''
        pct = max(0, min(100, float(value)))
        return format_html('<span class="pct"><span style="width:{}%"></span></span> {}%', f'{pct:.0f}',
                           fmt_number(value, self.decimals(field)))


@register
class Rating(Number):
    key, label, icon, editor = 'rating', 'Rating', '★', 'rating'

    def clean(self, field, raw, data=None):
        value = super().clean(field, raw, data)
        if value is None:
            return None
        return max(0, min(int(value), int(field.opt('max', 5))))

    def html(self, field, value, data=None):
        n, top = int(value or 0), int(field.opt('max', 5))
        return format_html('<span class="stars">{}<span class="off">{}</span></span>', '★' * n, '★' * (top - n))


# -- Yes/no and dates ----------------------------------------------------------------

@register
class Checkbox(FieldType):
    key, label, icon, editor = 'checkbox', 'Checkbox', '☑', 'checkbox'
    filter_ops = ('checked', 'unchecked')

    def clean(self, field, raw, data=None):
        if isinstance(raw, str):
            return raw.strip().lower() in ('1', 'true', 'on', 'yes', 'y', 'x', '✓')
        return bool(raw)

    def load(self, field, stored, data=None):
        return bool(stored)

    def text(self, field, value):
        return 'Yes' if value else 'No'

    def html(self, field, value, data=None):
        return mark_safe('<span class="check on">✓</span>') if value else mark_safe('<span class="check"></span>')

    def default(self, field):
        return bool(field.opt('default'))


@register
class Date(FieldType):
    key, label, icon, group, editor = 'date', 'Date', '📅', 'Date', 'date'
    filter_ops = ('is', 'is_not', 'gt', 'lt', 'is_today', 'is_before_today', 'is_after_today', 'next_days', 'past_days',
                  'is_empty', 'not_empty')

    def clean(self, field, raw, data=None):
        if raw is None or raw == '':
            return None
        if isinstance(raw, datetime):
            return raw.date().isoformat()
        if isinstance(raw, date):
            return raw.isoformat()
        value = parse_date(str(raw).strip()[:10])
        if value is None:
            raise ValidationError(f'{field.name}: "{raw}" is not a date (YYYY-MM-DD).')
        return value.isoformat()

    def load(self, field, stored, data=None):
        if not stored:
            return None
        try:
            return date.fromisoformat(stored[:10])
        except (TypeError, ValueError):
            return None

    def html(self, field, value, data=None):
        if not value:
            return ''
        return value.strftime('%d %b %Y').lstrip('0')

    def default(self, field):
        return timezone.localdate().isoformat() if field.opt('default') == 'today' else None


@register
class DateTime(Date):
    key, label, icon, editor = 'datetime', 'Date and time', '🕓', 'datetime'

    def clean(self, field, raw, data=None):
        if raw is None or raw == '':
            return None
        if isinstance(raw, datetime):
            value = raw
        else:
            value = parse_datetime(str(raw).strip().replace(' ', 'T'))
            if value is None:
                d = parse_date(str(raw).strip()[:10])
                if d is None:
                    raise ValidationError(f'{field.name}: "{raw}" is not a date and time.')
                value = datetime(d.year, d.month, d.day)
        if timezone.is_naive(value):
            value = timezone.make_aware(value)
        return value.isoformat()

    def load(self, field, stored, data=None):
        if not stored:
            return None
        value = parse_datetime(stored)
        return value

    def html(self, field, value, data=None):
        if not value:
            return ''
        return timezone.localtime(value).strftime('%d %b %Y %H:%M').lstrip('0')

    def raw(self, field, value, data=None):
        return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M') if value else None

    def default(self, field):
        return timezone.now().isoformat() if field.opt('default') == 'now' else None


# -- Choices ---------------------------------------------------------------------------

def choice_color(field, value):
    for i, c in enumerate(field.opt('choices') or []):
        if c.get('value') == value:
            return c.get('color') or COLORS[i % len(COLORS)]
    return '#e5e7eb'


def badge(field, value):
    return format_html('<span class="chip" style="background:{}">{}</span>', choice_color(field, value), value)


@register
class Select(FieldType):
    key, label, icon, group, editor = 'select', 'Single select', '◉', 'Choice', 'select'
    filter_ops = ('is', 'is_not', 'is_any_of', 'is_none_of', 'is_empty', 'not_empty')
    help = 'One value from a list. Choices can say which choice may follow which (e.g. Draft → Placed).'

    def values(self, field):
        return [c.get('value') for c in field.opt('choices') or []]

    def clean(self, field, raw, data=None):
        value = super().clean(field, raw, data)
        if value and value not in self.values(field):
            match = next((v for v in self.values(field) if v.lower() == value.lower()), None)
            if match is None:
                raise ValidationError(f'{field.name}: "{value}" is not one of the choices.')
            value = match
        return value

    def html(self, field, value, data=None):
        return badge(field, value) if value else ''

    def sort_key(self, value):
        return (0 if value else 1, value or '')

    def default(self, field):
        return field.opt('default') or None


@register
class MultiSelect(Select):
    key, label, icon, editor = 'multiselect', 'Multiple select', '☰', 'multiselect'
    filter_ops = ('contains', 'not_contains', 'is_any_of', 'is_empty', 'not_empty')

    def clean(self, field, raw, data=None):
        if raw is None or raw == '':
            return []
        items = raw if isinstance(raw, list) else [s for s in str(raw).split(',')]
        out = []
        for item in items:
            value = Select.clean(self, field, item, data)
            if value and value not in out:
                out.append(value)
        return out

    def load(self, field, stored, data=None):
        return list(stored or [])

    def html(self, field, value, data=None):
        return format_html_join(' ', '{}', ((badge(field, v),) for v in value or []))

    def default(self, field):
        return []


# -- People -----------------------------------------------------------------------------

@register
class UserField(FieldType):
    key, label, icon, group, editor = 'user', 'User', '👤', 'Relation', 'user'
    filter_ops = ('is_me', 'contains', 'is_empty', 'not_empty')
    help = 'One or more people who can log in.'

    def clean(self, field, raw, data=None):
        from django.contrib.auth import get_user_model
        if raw in (None, '', []):
            return [] if field.opt('multiple') else None
        items = raw if isinstance(raw, list) else str(raw).split(',')
        ids = []
        users = get_user_model().objects
        for item in items:
            item = str(item).strip()
            if not item:
                continue
            if isinstance(item, str) and item.lstrip('-').isdigit():
                user = users.filter(pk=int(item)).first()
            else:
                user = users.filter(username__iexact=item).first() or next(
                    (u for u in users.all() if str(u).lower() == item.lower()), None)
            if user is None:
                raise ValidationError(f'{field.name}: there is no user "{item}".')
            if user.pk not in ids:
                ids.append(user.pk)
        if not field.opt('multiple'):
            return ids[0] if ids else None
        return ids

    def load(self, field, stored, data=None):
        ids = stored if isinstance(stored, list) else ([stored] if stored else [])
        users = data.users() if data else {}
        ids = [i for i in ids if i in users]
        return Records([str(users[i]) for i in ids], ids)

    def html(self, field, value, data=None):
        return format_html_join(' ', '<span class="person"><b>{}</b>{}</span>',
                                ((''.join(p[0] for p in name.split()[:2]).upper(), name) for name in value or []))

    def raw(self, field, value, data=None):
        return [{'id': i, 'name': n} for i, n in zip(value.ids, value)] if value else []

    def default(self, field):
        return [] if field.opt('multiple') else None


# -- Relations (computed from the Link table) ------------------------------------------

@register
class LinkField(FieldType):
    key, label, icon, group, editor = 'link', 'Link to records', '⇄', 'Relation', 'link'
    stored = False  # kept in the Link table, not Record.data
    filter_ops = ('contains', 'not_contains', 'is_empty', 'not_empty')
    help = 'Links records of this table to records of another (or the same) table. The other table gets a matching field.'

    def compute(self, field, record, data):
        records = data.linked(record, field)
        return Records([data.label(r) for r in records], [r.pk for r in records])

    def clean(self, field, raw, data=None):
        """Record ids (a list, or one id, or names of records in the target table)."""
        if raw in (None, '', []):
            return []
        items = raw if isinstance(raw, list) else (raw.ids if isinstance(raw, Records) else [raw])
        if isinstance(raw, Records):
            items = raw.ids
        ids = []
        for item in items:
            if isinstance(item, dict):
                item = item.get('id')
            if isinstance(item, Decimal):
                item = int(item)
            if isinstance(item, str) and item.strip().isdigit():
                item = int(item.strip())
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, str) and item.strip() and data is not None:
                found = data.find_by_label(field.opt('target'), item.strip())
                if found is None:
                    raise ValidationError(f'{field.name}: there is no "{item.strip()}" to link to.')
                ids.append(found.pk)
        if data is not None:
            valid = data.existing_ids(field.opt('target'), ids)
            missing = [i for i in ids if i not in valid]
            if missing:
                raise ValidationError(f'{field.name}: record {missing[0]} is not in the linked table.')
        ids = list(dict.fromkeys(ids))
        if not field.opt('multiple') and len(ids) > 1:
            raise ValidationError(f'{field.name}: only one record can be linked.')
        return ids

    def html(self, field, value, data=None):
        if not value:
            return ''
        return format_html_join('', '<a class="link-chip" href="/r/{}/">{}</a>', zip(value.ids, value))

    def raw(self, field, value, data=None):
        return [{'id': i, 'name': n} for i, n in zip(value.ids, value)] if value else []

    def sort_key(self, value):
        return (0 if value else 1, ', '.join(value or []).lower())


def _flatten_values(values):
    out_items, out_ids, has_ids = [], [], False
    for v in values:
        if isinstance(v, Records):
            has_ids = True
            out_items.extend(v)
            out_ids.extend(v.ids)
        elif isinstance(v, list):
            out_items.extend(v)
        elif v is not None and v != '':
            out_items.append(v)
    return Records(out_items, out_ids) if has_ids else out_items


@register
class Lookup(FieldType):
    key, label, icon, group, editable = 'lookup', 'Lookup', '↗', 'Computed', False
    stored = False
    help = 'Shows a field of the linked records, e.g. the supplier\'s email on an order.'

    def target_field(self, field, data):
        link = data.field(field.opt('link'))
        target = data.field(field.opt('field'))
        return link, target

    def compute(self, field, record, data):
        link, target = self.target_field(field, data)
        if link is None or target is None:
            return None
        values = [data.value(r, target) for r in data.linked(record, link)]
        return _flatten_values(values)

    def html(self, field, value, data=None):
        if data is None or value in (None, []):
            return ''
        target = data.field(field.opt('field'))
        if target is None:
            return escape(formula.text(value))
        if isinstance(value, Records):
            return format_html_join('', '<a class="link-chip" href="/r/{}/">{}</a>', zip(value.ids, value))
        return mark_safe(', '.join(str(target.kind.html(target, v, data)) for v in value))

    def text(self, field, value):
        return formula.text(value)


ROLLUPS = {
    'sum': 'Sum', 'avg': 'Average', 'min': 'Smallest', 'max': 'Largest',
    'count': 'Count linked records', 'counta': 'Count non-empty values', 'countunique': 'Count unique values',
    'concat': 'Join the values', 'all': 'All are true', 'any': 'Any is true', 'earliest': 'Earliest date', 'latest': 'Latest date',
}


@register
class Rollup(FieldType):
    key, label, icon, group, editable, align = 'rollup', 'Rollup', 'Σ', 'Computed', False, 'num'
    stored = False
    filter_ops = Number.filter_ops
    help = 'Adds up (or counts, averages, ...) a field of the linked records; can count only the ones that match a formula.'

    def compute(self, field, record, data):
        link = data.field(field.opt('link'))
        if link is None:
            return None
        records = data.linked(record, link)
        condition = field.opt('filter')
        if condition:
            records = [r for r in records if formula.truthy(data.evaluate(condition, r, default=False))]
        func = field.opt('func', 'sum')
        if func == 'count':
            return Decimal(len(records))
        target = data.field(field.opt('field'))
        if target is None:
            return None
        values = list(formula.flatten([data.value(r, target) for r in records]))
        if func == 'counta':
            return Decimal(sum(1 for v in values if not formula.is_blank(v)))
        if func == 'countunique':
            return Decimal(len({formula.text(v) for v in values if not formula.is_blank(v)}))
        if func == 'concat':
            return ', '.join(formula.text(v) for v in values if not formula.is_blank(v))
        if func == 'all':
            return all(formula.truthy(v) for v in values)
        if func == 'any':
            return any(formula.truthy(v) for v in values)
        if func in ('earliest', 'latest'):
            dates = [v for v in values if isinstance(v, date)]
            return (min(dates) if func == 'earliest' else max(dates)) if dates else None
        nums = formula.numbers(values)
        if func == 'sum':
            return sum(nums, Decimal(0))
        if not nums:
            return None
        return {'avg': lambda: sum(nums, Decimal(0)) / len(nums), 'min': lambda: min(nums), 'max': lambda: max(nums)}[func]()

    def html(self, field, value, data=None):
        return format_value(field, value, data)

    def text(self, field, value):
        return format_text(field, value)


@register
class Formula(FieldType):
    key, label, icon, group, editable = 'formula', 'Formula', 'ƒ', 'Computed', False
    stored = False
    filter_ops = ('is', 'is_not', 'contains', 'gt', 'lt', 'is_empty', 'not_empty', 'checked', 'unchecked')
    help = 'Worked out from other fields, e.g. {Quantity} * {Unit price}.'

    def compute(self, field, record, data):
        return data.evaluate(field.opt('expression', ''), record, error='#ERROR')

    def html(self, field, value, data=None):
        return format_value(field, value, data)

    def text(self, field, value):
        return format_text(field, value)


def format_text(field, value):
    """A computed value as plain text (CSV, record names, history), rounded as the field says."""
    if value is None or value == '' or value == '#ERROR':
        return value or ''
    fmt = field.opt('format') or 'auto'
    decimals = field.opt('decimals')
    decimals = int(decimals) if decimals not in (None, '') else (2 if fmt == 'currency' else None)
    if fmt == 'checkbox' or isinstance(value, bool):
        return 'Yes' if formula.truthy(value) else 'No'
    if isinstance(value, (Decimal, int, float)) or fmt in ('number', 'currency', 'percent'):
        try:
            return fmt_number(value, decimals, thousands=False)
        except FormulaError:
            pass
    return formula.text(value)


def format_value(field, value, data=None):
    """Show a computed value, using the field's chosen format (or guessing it)."""
    fmt = field.opt('format') or 'auto'
    if value == '#ERROR':
        return mark_safe('<span class="error" title="The formula can\'t be worked out">#ERROR</span>')
    if value is None or value == '':
        return ''
    decimals = field.opt('decimals')
    decimals = int(decimals) if decimals not in (None, '') else None
    if fmt == 'currency':
        try:
            text = fmt_number(value, 2 if decimals is None else decimals)
        except FormulaError:
            return escape(formula.text(value))
        symbol = field.opt('symbol', '€')
        return f'-{symbol}{text[1:]}' if text.startswith('-') else f'{symbol}{text}'
    if fmt == 'percent':
        return f'{fmt_number(value, decimals)}%'
    if fmt == 'checkbox' or isinstance(value, bool):
        return TYPES['checkbox'].html(field, formula.truthy(value))
    if fmt == 'date' or isinstance(value, date):
        try:
            d = formula.to_date(value)
        except FormulaError:
            return escape(formula.text(value))
        return TYPES['date'].html(field, d)
    if isinstance(value, (Decimal, int, float)) or fmt == 'number':
        try:
            return fmt_number(value, decimals)
        except FormulaError:
            pass
    if isinstance(value, Records):
        return format_html_join('', '<a class="link-chip" href="/r/{}/">{}</a>', zip(value.ids, value))
    return escape(formula.text(value))


# -- Files, numbering, buttons ----------------------------------------------------------

@register
class Attachment(FieldType):
    key, label, icon, group, editor = 'attachment', 'Files', '📎', 'Basic', 'attachment'
    stored = False
    filter_ops = ('is_empty', 'not_empty')
    help = 'Pictures, PDFs and other files.'

    def compute(self, field, record, data):
        return data.attachments(record, field)

    def text(self, field, value):
        return ', '.join(a.name for a in value or [])

    def html(self, field, value, data=None):
        parts = []
        for a in (value or [])[:4]:
            if a.is_image:
                parts.append(format_html('<img class="thumb" src="/files/{}/?thumb=1" alt="{}" loading="lazy">', a.pk, a.name))
            else:
                parts.append(format_html('<span class="file-chip">{}</span>', a.name))
        if len(value or []) > 4:
            parts.append(format_html('<span class="muted">+{}</span>', len(value) - 4))
        return mark_safe(''.join(parts))

    def raw(self, field, value, data=None):
        return [{'id': a.pk, 'name': a.name, 'image': a.is_image} for a in value or []]

    def sort_key(self, value):
        return (0, len(value or []))


@register
class AutoNumber(FieldType):
    key, label, icon, group, editable, align = 'autonumber', 'Autonumber', '№', 'Number', False, ''
    filter_ops = ('is', 'contains', 'is_empty', 'not_empty')
    help = 'Numbers new records by itself: 1, 2, 3 or PO-0001, PO-0002, ...'

    def load(self, field, stored, data=None):
        if stored in (None, ''):
            return None
        return f'{field.opt("prefix", "")}{int(stored):0{int(field.opt("digits") or 1)}d}'

    def sort_key(self, value):
        digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
        return (0, int(digits)) if digits else (1, 0)


class _System(FieldType):
    group, editable, stored = 'System', False, False

    def raw(self, field, value, data=None):
        return formula.text(value)


@register
class CreatedTime(_System):
    key, label, icon = 'created_time', 'Created at', '🕓'
    filter_ops = Date.filter_ops

    def compute(self, field, record, data):
        return record.created_at

    def html(self, field, value, data=None):
        return TYPES['datetime'].html(field, value)


@register
class ModifiedTime(CreatedTime):
    key, label = 'modified_time', 'Last changed at'

    def compute(self, field, record, data):
        return record.updated_at


@register
class CreatedBy(_System):
    key, label, icon = 'created_by', 'Created by', '👤'
    filter_ops = ('is_me', 'contains', 'is_empty', 'not_empty')

    def compute(self, field, record, data):
        users = data.users()
        uid = record.created_by_id
        return Records([str(users[uid])], [uid]) if uid in users else Records()

    def html(self, field, value, data=None):
        return TYPES['user'].html(field, value)


@register
class ModifiedBy(CreatedBy):
    key, label = 'modified_by', 'Last changed by'

    def compute(self, field, record, data):
        users = data.users()
        uid = record.updated_by_id
        return Records([str(users[uid])], [uid]) if uid in users else Records()


@register
class RecordId(_System):
    key, label, icon, align = 'record_id', 'Record id', 'ID', 'num'

    def compute(self, field, record, data):
        return Decimal(record.pk)


@register
class Button(FieldType):
    key, label, icon, group, editable = 'button', 'Button', '▶', 'Advanced', False
    stored = False
    filter_ops = ()
    help = 'Runs an automation (with the "A button is pressed" trigger) on the record.'

    def compute(self, field, record, data):
        return None

    def html(self, field, value, data=None, record=None):
        return ''

    def sort_key(self, value):
        return (0, 0)
