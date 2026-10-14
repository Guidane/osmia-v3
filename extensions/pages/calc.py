"""Calculations on pages: ``<span class="page-calc" data-formula="..." data-name="...">``.

A formula (core.formula's language) can use
    {budget.Remaining}   a field of a record put on the page with a name (data-name="budget"),
                         also through links: {project.Budget.Remaining}, SUM({order.Lines.Total})
    {Qty}                in a page table, the cell of the same row under the heading "Qty"
    {total}              another calculation on the page with that name (outside tables)

Worked out each time the page is shown, with the reader's permissions: a formula
that needs a record (or follows a link into an app) the reader can't see shows 🔒.

Tables can be very big, so a page never loads one whole past ``BIG_TABLE``
records, and the limits below keep one page from doing unbounded work.
"""
import re
from decimal import Decimal
from html import unescape

from django.utils.html import escape

from core import formula
from core.data import Data
from core.formula import FormulaError, Records
from core.models import Link, Record
from core.permissions import can

BIG_TABLE = 50_000       # records: a table this big is never loaded whole for a page
MAX_LINKED = 10_000      # linked records a formula, card or value may follow in one step
MAX_TABLE_ROWS = 500     # rows of one page table that are worked out
MAX_CALCS = 1_000        # calculations on one page

CALC = re.compile(r'<span class="page-calc"([^>]*)>(.*?)</span>', re.S)
TABLE = re.compile(r'<table>(.*?)</table>', re.S)
ROW = re.compile(r'<tr>(.*?)</tr>', re.S)
CELL = re.compile(r'<(t[hd])([^>]*)>(.*?)</\1>', re.S)
NAMED = re.compile(r'<(?:a|span|div) class="(?:record-ref|record-value|record-card)"([^>]*)>')
VALUE = re.compile(r'<span class="record-value"([^>]*)>', re.S)
ATTRS = re.compile(r'(data-[a-z]+)="([^"]*)"')
TAGS = re.compile(r'<[^>]+>')
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,30}$')
OUTPUT = re.compile(r'<span class="calc-(?:result|error)[^"]*"[^>]*>(.*?)</span>', re.S)


def attrs(text):
    return {k: unescape(v) for k, v in ATTRS.findall(text)}


class Locked(FormulaError):
    """The formula needs something the reader may not see."""


class PageData(Data):
    """Data for showing a page: big tables are read a record at a time, and links
    into apps the reader can't see are closed to formulas (``strict``)."""

    def __init__(self, user=None):
        super().__init__(user)
        self._sizes = {}
        self._link_counts = {}
        self.strict = 0   # > 0 while a page formula is worked out

    def table_size(self, table_id):
        if table_id not in self._sizes:
            self._sizes[table_id] = Record.objects.filter(table_id=table_id).count()
        return self._sizes[table_id]

    def is_big(self, table_id):
        return self.table_size(table_id) > BIG_TABLE

    def linked_ids(self, record, field):
        owner, backwards = self.owner_of(field)
        if owner.pk not in self._links:
            if owner.pk not in self._link_counts:
                self._link_counts[owner.pk] = Link.objects.filter(field_id=owner.pk).count()
            if self._link_counts[owner.pk] > BIG_TABLE:   # just this record's links, not the field's millions
                mine, other = ('target_id', 'source_id') if backwards else ('source_id', 'target_id')
                return list(Link.objects.filter(field_id=owner.pk, **{mine: record.pk})
                            .order_by('position', 'id').values_list(other, flat=True)[:MAX_LINKED + 1])
        return super().linked_ids(record, field)

    def linked(self, record, field):
        ids = self.linked_ids(record, field)
        if len(ids) > MAX_LINKED:
            raise FormulaError(f'{field.name} links to more than {MAX_LINKED:,} records, too many to work out on a page.')
        target = field.opt('target')
        if self.strict and target:
            table = self.table(target)
            if table is not None and not can(self.user, table.app, 'viewer'):
                raise Locked(f'{field.name} goes into an app you have no access to.')
        if target and len(ids) > 3 and target not in self._loaded_tables and not self.is_big(target):
            self.records(target)
        return self.records_by_ids(ids)


def readable(user, data, record_id):
    """The record, if the reader may see it; Locked or FormulaError otherwise."""
    record = Record.objects.select_related('table__app').filter(pk=record_id).first()
    if record is None:
        raise FormulaError('A record it uses was deleted.')
    if not can(user, record.table.app, 'viewer'):
        raise Locked('It uses a record you have no access to.')
    return data.record(record.pk)


def shown(value):
    """A result as text; long decimals are cut to 4 places (ROUND() for fewer)."""
    value = formula.unwrap(value)
    if isinstance(value, Decimal) and value.as_tuple().exponent < -4:
        value = value.quantize(Decimal('0.0001')).normalize()
    return formula.text(value)


class Row:
    """A page table row's cells by heading, worked out when a formula asks for them."""

    def __init__(self, calc, cells):
        self.calc, self.cells, self.values, self.busy = calc, cells, {}, set()

    def __contains__(self, name):
        return name in self.cells

    def __call__(self, name):
        if name not in self.values:
            if name in self.busy:
                raise FormulaError(f'{{{name}}} refers to itself.')
            self.busy.add(name)
            try:
                self.values[name] = self.calc.cell_value(self.cells[name], self)
            finally:
                self.busy.discard(name)
        return self.values[name]


class Calculator:
    def __init__(self, body, user, data):
        self.user, self.data = user, data
        self.records = {}    # name -> record id
        for m in NAMED.finditer(body):
            a = attrs(m.group(1))
            if NAME.match(a.get('data-name', '')) and a.get('data-record', '').isdigit():
                self.records.setdefault(a['data-name'], int(a['data-record']))
        self.formulas = {}   # name -> formula, of calculations outside tables
        for m in CALC.finditer(TABLE.sub('', body)):
            a = attrs(m.group(1))
            if NAME.match(a.get('data-name', '')):
                self.formulas.setdefault(a['data-name'], a.get('data-formula', ''))
        self.named_values, self.busy, self.count = {}, set(), 0

    # -- working out ---------------------------------------------------------------

    def run(self, text, row=None):
        self.count += 1
        if self.count > MAX_CALCS:
            raise FormulaError(f'Only the first {MAX_CALCS:,} calculations on a page are worked out.')
        self.data.strict += 1
        try:
            return formula.run(text, formula.Context(self.resolver(row), user=self.user))
        finally:
            self.data.strict -= 1

    def named(self, name):
        if name not in self.named_values:
            if name in self.busy:
                raise FormulaError(f'{{{name}}} refers to itself.')
            self.busy.add(name)
            try:
                self.named_values[name] = self.run(self.formulas[name])
            finally:
                self.busy.discard(name)
        return self.named_values[name]

    def resolver(self, row):
        def resolve(name):
            if row is not None and name in row:
                return row(name)
            if name in self.formulas:
                return self.named(name)
            head, dot, rest = name.partition('.')
            if head in self.records:
                record = readable(self.user, self.data, self.records[head])
                return self.data._resolve_in(record, rest) if dot else Records([self.data.label(record)], [record.pk])
            raise FormulaError(f'Nothing on this page is called {{{name}}}.')
        return resolve

    def cell_value(self, html, row):
        m = CALC.search(html)
        if m:
            return self.run(attrs(m.group(1)).get('data-formula', ''), row)
        m = VALUE.search(html)
        if m:
            a = attrs(m.group(1))
            record = readable(self.user, self.data, int(a.get('data-record') or 0))
            field = self.data.field(a.get('data-field'))
            if field is None or field.table_id != record.table_id:
                raise FormulaError('A field it uses was deleted.')
            return self.data.value(record, field)
        text = unescape(TAGS.sub(' ', html)).replace('\xa0', ' ').strip()
        return ' '.join(text.split()) or None

    # -- showing -------------------------------------------------------------------

    def output(self, work, text):
        try:
            value = shown(work())
        except Locked as e:
            return f'<span class="calc-result gone" title="{escape(str(e))}">🔒</span>'
        except FormulaError as e:
            return f'<span class="calc-error" title="{escape(text)}">⚠ {escape(str(e))}</span>'
        return f'<span class="calc-result" title="{escape(text)}">{escape(value) or "—"}</span>'

    def placeholder(self, m, row=None, skipped=False):
        a = attrs(m.group(1))
        text, name = a.get('data-formula', ''), a.get('data-name', '')
        if skipped:
            return (f'<span class="calc-error" title="{escape(text)}">Only the first {MAX_TABLE_ROWS} rows of a table '
                    f'are worked out.</span>')
        if row is None and name in self.formulas and self.formulas[name] == text:
            return self.output(lambda: self.named(name), text)
        return self.output(lambda: self.run(text, row), text)

    def table(self, m):
        header, count = None, 0

        def row_sub(rm):
            nonlocal header, count
            cells = CELL.findall(rm.group(1))
            if header is None:
                header = [' '.join(unescape(TAGS.sub(' ', c[2])).split()) for c in cells]
                return CALC.sub(lambda cm: self.placeholder(cm), rm.group(0))
            count += 1
            row = Row(self, {h: c[2] for h, c in zip(header, cells) if h})
            index = iter(range(len(cells)))

            def cell_sub(cm):
                i = next(index)
                h = header[i] if i < len(header) else ''
                first = [True]

                def calc_sub(km):
                    if count > MAX_TABLE_ROWS:
                        return self.placeholder(km, skipped=True)
                    if first[0] and h and row.cells.get(h) == cm.group(3):   # the cell's own value, worked out once
                        first[0] = False
                        return self.output(lambda: row(h), attrs(km.group(1)).get('data-formula', ''))
                    return self.placeholder(km, row)
                return f'<{cm.group(1)}{cm.group(2)}>{CALC.sub(calc_sub, cm.group(3))}</{cm.group(1)}>'
            return f'<tr>{CELL.sub(cell_sub, rm.group(1))}</tr>'
        return f'<table>{ROW.sub(row_sub, m.group(1))}</table>'

    def apply(self, body):
        body = TABLE.sub(self.table, body)
        return CALC.sub(lambda m: self.placeholder(m), body)


def calculate(body, user, data):
    """The body with every calculation worked out."""
    if 'page-calc' not in body:
        return body
    return Calculator(body, user, data).apply(body)


def result(body, user, index):
    """What the ``index``-th calculation of ``body`` shows (for the editor's preview)."""
    outputs = OUTPUT.findall(calculate(body, user, PageData(user)))
    return outputs[index] if 0 <= index < len(outputs) else ''
