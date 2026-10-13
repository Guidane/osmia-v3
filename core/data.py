"""Reading the workspace: records, links and the values of every field.

One ``Data`` serves one request (or one automation step). It loads a table's
records and a link field's pairs once, and remembers each computed value, so
a grid of 500 orders with rollups over their lines costs a handful of queries.
Anything that writes calls ``invalidate()`` so the next read sees the change.
"""
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.html import format_html

from . import formula
from .formula import FormulaError, Records
from .models import Attachment, Field, Link, Record, Table


class OldValues:
    """A record's values before a change (for {old.Status} in automations)."""

    def __init__(self, record, data_before, links_before):
        self.record = record
        self.data = dict(data_before or {})
        self.links = dict(links_before or {})  # {field id: [ids]}


class Data:
    def __init__(self, user=None):
        self.user = user
        self._tables = {}
        self._fields_by_table = {}
        self._fields = {}
        self._records = {}
        self._loaded_tables = set()
        self._links = {}           # owner field id -> (forward {src: [dst]}, backward {dst: [src]})
        self._values = {}
        self._computing = set()
        self._users = None
        self._attachments = {}

    # -- cache control -----------------------------------------------------------------

    def invalidate(self, schema=False):
        self._records.clear()
        self._loaded_tables.clear()
        self._links.clear()
        self._values.clear()
        self._attachments.clear()
        if schema:
            self._tables.clear()
            self._fields_by_table.clear()
            self._fields.clear()

    # -- schema ------------------------------------------------------------------------

    def table(self, table):
        if table is None:
            return None
        if isinstance(table, Table):
            self._tables.setdefault(table.pk, table)
            return self._tables[table.pk]
        table_id = int(table)
        if table_id not in self._tables:
            t = Table.objects.select_related('app').filter(pk=table_id).first()
            if t is None:
                return None
            self._tables[table_id] = t
        return self._tables[table_id]

    def fields(self, table):
        table = self.table(table)
        if table is None:
            return []
        if table.pk not in self._fields_by_table:
            fields = list(Field.objects.filter(table=table))
            for f in fields:
                f.table = table
                self._fields[f.pk] = f
            self._fields_by_table[table.pk] = fields
        return self._fields_by_table[table.pk]

    def field(self, field_id):
        if field_id in (None, ''):
            return None
        if isinstance(field_id, Field):
            return field_id
        try:
            field_id = int(field_id)
        except (TypeError, ValueError):
            return None
        if field_id not in self._fields:
            f = Field.objects.select_related('table__app').filter(pk=field_id).first()
            if f is None:
                return None
            self.fields(f.table)  # loads the whole table, f included
        return self._fields.get(field_id)

    def field_named(self, table, name):
        """A field by its name (any case) or its key."""
        name = (name or '').strip()
        low = name.lower()
        fields = self.fields(table)
        return (next((f for f in fields if f.name == name), None)
                or next((f for f in fields if f.name.lower() == low), None)
                or next((f for f in fields if f.key == name), None))

    def primary_field(self, table):
        table = self.table(table)
        fields = self.fields(table)
        if table.display_field_id:
            f = self._fields.get(table.display_field_id)
            if f:
                return f
        return fields[0] if fields else None

    # -- records ------------------------------------------------------------------------

    def records(self, table):
        table = self.table(table)
        if table.pk not in self._loaded_tables:
            for r in Record.objects.filter(table_id=table.pk):
                self._records.setdefault(r.pk, r)
            self._loaded_tables.add(table.pk)
        return sorted((r for r in self._records.values() if r.table_id == table.pk), key=lambda r: (r.position, r.pk))

    def record(self, record_id):
        if isinstance(record_id, Record):
            self._records.setdefault(record_id.pk, record_id)
            return self._records[record_id.pk]
        try:
            record_id = int(record_id)
        except (TypeError, ValueError):
            return None
        if record_id not in self._records:
            r = Record.objects.filter(pk=record_id).first()
            if r is None:
                return None
            self._records[record_id] = r
        return self._records[record_id]

    def records_by_ids(self, ids):
        missing = [i for i in ids if i not in self._records]
        if missing:
            for r in Record.objects.filter(pk__in=missing):
                self._records[r.pk] = r
        return [self._records[i] for i in ids if i in self._records]

    def existing_ids(self, table_id, ids):
        return set(Record.objects.filter(table_id=table_id, pk__in=ids).values_list('pk', flat=True))

    def find_by_label(self, table_id, label):
        low = label.lower()
        return next((r for r in self.records(table_id) if self.label(r).lower() == low), None)

    def users(self):
        if self._users is None:
            self._users = {u.pk: u for u in get_user_model().objects.all()}
        return self._users

    # -- links ---------------------------------------------------------------------------

    def owner_of(self, field):
        """(the link field that stores the pairs, whether ``field`` reads them backwards)."""
        if field.opt('owner', True):
            return field, False
        inverse = self.field(field.opt('inverse'))
        return (inverse, True) if inverse is not None else (field, False)

    def _pairs(self, owner):
        if owner.pk not in self._links:
            forward, backward = defaultdict(list), defaultdict(list)
            for src, dst in Link.objects.filter(field_id=owner.pk).order_by('position', 'id').values_list('source_id', 'target_id'):
                forward[src].append(dst)
                backward[dst].append(src)
            self._links[owner.pk] = (forward, backward)
        return self._links[owner.pk]

    def linked_ids(self, record, field):
        owner, backwards = self.owner_of(field)
        forward, backward = self._pairs(owner)
        return list((backward if backwards else forward).get(record.pk, []))

    def linked(self, record, field):
        ids = self.linked_ids(record, field)
        target = field.opt('target')
        if target and target not in self._loaded_tables and len(ids) > 3:
            self.records(target)
        return self.records_by_ids(ids)

    def attachments(self, record, field):
        key = (record.pk, field.pk if field else None)
        if key not in self._attachments:
            table_id = record.table_id
            if ('table', table_id) not in self._attachments:
                grouped = defaultdict(list)
                for a in Attachment.objects.filter(record__table_id=table_id):
                    grouped[(a.record_id, a.field_id)].append(a)
                self._attachments[('table', table_id)] = grouped
            return self._attachments[('table', table_id)].get(key, [])
        return self._attachments[key]

    # -- values --------------------------------------------------------------------------

    def value(self, record, field):
        """The typed value of a field (stored or worked out)."""
        key = (record.pk, field.pk)
        if key in self._values:
            return self._values[key]
        kind = field.kind
        if kind.stored:
            value = kind.load(field, (record.data or {}).get(field.key), self)
        else:
            if key in self._computing:
                return '#ERROR' if field.type == 'formula' else None  # a field that depends on itself
            self._computing.add(key)
            try:
                value = kind.compute(field, record, self)
            finally:
                self._computing.discard(key)
        self._values[key] = value
        return value

    def values(self, record):
        return {f.key: self.value(record, f) for f in self.fields(record.table_id)}

    def label(self, record):
        primary = self.primary_field(record.table_id)
        if primary is None:
            return f'#{record.pk}'
        if primary.type in ('link', 'lookup', 'attachment', 'button'):
            return f'#{record.pk}'
        text = primary.kind.text(primary, self.value(record, primary)) if primary.type != 'formula' else \
            formula.text(self.value(record, primary))
        return text or f'#{record.pk}'

    def text(self, record, field):
        return field.kind.text(field, self.value(record, field))

    def html(self, record, field):
        if field.type == 'button':
            return format_html('<button type="button" class="btn small run-button" data-record="{}" data-field="{}"'
                               ' style="--btn:{}">{}</button>', record.pk, field.pk,
                               field.opt('color') or 'var(--brand)', field.opt('label') or field.name)
        return field.kind.html(field, self.value(record, field), self)

    def raw(self, record, field):
        return field.kind.raw(field, self.value(record, field), self)

    # -- formulas -----------------------------------------------------------------------

    def resolver(self, record, extra=None):
        """The callback that gives {name} its value for ``record``.

        extra: {'trigger': record, 'old': OldValues, 'this': record, ...}. A name
        that starts with one of these keys and a dot is looked up there.
        """
        extra = extra or {}

        def resolve(name):
            head, dot, rest = name.partition('.')
            if dot and head in extra:
                return self._resolve_in(extra[head], rest)
            if name in extra:
                target = extra[name]
                if isinstance(target, Record):
                    return Records([self.label(target)], [target.pk])
                if isinstance(target, OldValues):
                    return None
                return target
            if record is None:
                raise FormulaError(f'There is no field {{{name}}} here.')
            return self._resolve_in(record, name)
        return resolve

    def _resolve_in(self, start, path):
        if isinstance(start, OldValues):
            return self._resolve_old(start, path)
        if isinstance(start, list):
            records = start
        else:
            records = [start]
        if not records or records[0] is None:
            return None
        return self._walk(records[0].table_id, records, path, single=not isinstance(start, list))

    def _walk(self, table_id, records, path, single):
        """Follow ``path`` (field names joined with dots; names may contain dots)
        from ``records`` of ``table_id``."""
        field = self.field_named(table_id, path)
        if field is not None:
            values = [self.value(r, field) for r in records]
            if single:
                return values[0] if values else None
            from .fieldtypes import _flatten_values
            return _flatten_values(values)
        # Split at a dot where the head is a link (or a lookup of links)
        idx = path.find('.')
        while idx != -1:
            head, rest = path[:idx], path[idx + 1:]
            field = self.field_named(table_id, head)
            if field is not None and field.type == 'link':
                linked, seen = [], set()
                for r in records:
                    for x in self.linked(r, field):
                        if x.pk not in seen:
                            seen.add(x.pk)
                            linked.append(x)
                target = field.opt('target')
                if not linked:
                    return None if (single and not field.opt('multiple')) else []
                return self._walk(target, linked, rest, single=single and not field.opt('multiple'))
            idx = path.find('.', idx + 1)
        table = self.table(table_id)
        raise FormulaError(f'{table.name if table else "This table"} has no field {{{path}}}.')

    def _resolve_old(self, old, path):
        field = self.field_named(old.record.table_id, path)
        if field is None:
            raise FormulaError(f'There is no field {{old.{path}}}.')
        if field.kind.stored:
            return field.kind.load(field, old.data.get(field.key), self)
        if field.type == 'link' and field.pk in old.links:
            ids = old.links[field.pk]
            recs = self.records_by_ids(ids)
            return Records([self.label(r) for r in recs], [r.pk for r in recs])
        return self.value(old.record, field)

    def evaluate(self, expression, record, extra=None, error=None, default=None):
        """The value of a formula for ``record``. On a mistake: ``error`` if
        given, else raise FormulaError."""
        if not (expression or '').strip():
            return default
        ctx = formula.Context(self.resolver(record, extra), user=self.user,
                              record_id=record.pk if record is not None else None)
        try:
            return formula.run(expression, ctx)
        except FormulaError:
            if error is not None:
                return error
            raise

    def render(self, template, record, extra=None):
        """Text with {Field} placeholders filled in (for messages and names)."""
        if not template or '{' not in template:
            return template or ''
        out, i = [], 0
        while i < len(template):
            start = template.find('{', i)
            if start == -1:
                out.append(template[i:])
                break
            end = template.find('}', start)
            if end == -1:
                out.append(template[i:])
                break
            out.append(template[i:start])
            name = template[start + 1:end].strip()
            try:
                value = self.resolver(record, extra)(name)
                out.append(self._text_of(value))
            except FormulaError:
                out.append(template[start:end + 1])
            i = end + 1
        return ''.join(out)

    def _text_of(self, value):
        from .fieldtypes import fmt_number
        from decimal import Decimal
        value = formula.unwrap(value)
        if isinstance(value, Decimal):
            return fmt_number(value, 2 if value != value.to_integral_value() else None)
        return formula.text(value)

    # -- searching -------------------------------------------------------------------------

    def search(self, table, q, limit=None):
        """Records whose text in any shown field contains ``q``."""
        q = (q or '').strip().lower()
        records = self.records(table)
        if not q:
            return records[:limit] if limit else records
        fields = [f for f in self.fields(table) if f.type not in ('button', 'attachment', 'json')]
        out = []
        for r in records:
            if any(q in formula.text(self.value(r, f)).lower() for f in fields) or q == str(r.pk):
                out.append(r)
                if limit and len(out) >= limit:
                    break
        return out


def tables_linking_to(table_id):
    """Link fields in any table that point at ``table_id``."""
    return [f for f in Field.objects.filter(type='link').select_related('table') if f.opt('target') == table_id]


def record_ids_with_text(table_id, q):
    return Record.objects.filter(table_id=table_id).filter(Q(data__icontains=q)).values_list('pk', flat=True)
