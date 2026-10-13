"""A small, safe formula language (no Python ``eval``), like a spreadsheet's.

    {Quantity} * {Unit price}
    IF({Status} = "Done", "✓", DAYS(TODAY(), {Due date}) & " days left")
    SUM({Lines.Total})                      a path through a link: every line's total
    {Part.Average cost}                     the linked part's average cost
    "Received with " & {trigger.Number}     in automations: the record that set it off

``{...}`` names a field (by name, or by key). A dotted path follows link
fields; what a name means is up to the ``resolve`` callback the caller passes
(see core.data). Values are None (blank), Decimal, str, bool, date, datetime
or lists of them.

Operators, lowest first: ``||`` ``&&`` · ``= != <> < <= > >=`` · ``&`` (join
text) · ``+ -`` · ``* / %`` · unary ``- !``.
"""
import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import timezone


class FormulaError(Exception):
    pass


class Records(list):
    """The records a link field (or a path ending in one) points at: a list of
    their names that also knows their ids, so ``{Part}`` can set a link."""

    def __init__(self, items=(), ids=()):
        super().__init__(items)
        self.ids = list(ids)


# -- Tokens ---------------------------------------------------------------------

TOKEN = re.compile(r'''
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?|\.\d+)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<ref>\{[^{}]*\})
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\|\||&&|==|!=|<>|<=|>=|[-+*/%&=<>!(),])
''', re.VERBOSE)


def tokenize(text):
    tokens, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise FormulaError(f'I don\'t understand "{text[pos:pos + 12]}".')
        pos = m.end()
        kind = m.lastgroup
        if kind == 'ws':
            continue
        value = m.group()
        if kind == 'str':
            value = re.sub(r'\\(.)', r'\1', value[1:-1])
        elif kind == 'ref':
            value = value[1:-1].strip()
            if not value:
                raise FormulaError('An empty {} names no field.')
        tokens.append((kind, value))
    tokens.append(('end', None))
    return tokens


# -- Parser (Pratt): text -> tuples ----------------------------------------------

BINARY = {
    '||': 1, '&&': 2,
    '=': 3, '==': 3, '!=': 3, '<>': 3, '<': 3, '<=': 3, '>': 3, '>=': 3,
    '&': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6,
}


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def take(self, kind=None, value=None):
        tok = self.tokens[self.i]
        if (kind and tok[0] != kind) or (value and tok[1] != value):
            want = value or kind
            got = tok[1] if tok[0] != 'end' else 'the end'
            raise FormulaError(f'Expected {want} but found {got}.')
        self.i += 1
        return tok

    def parse(self):
        node = self.expr(0)
        if self.peek()[0] != 'end':
            raise FormulaError(f'Unexpected "{self.peek()[1]}".')
        return node

    def expr(self, min_bp):
        left = self.unary()
        while True:
            kind, op = self.peek()
            bp = BINARY.get(op) if kind == 'op' else None
            if bp is None or bp <= min_bp:
                return left
            self.take()
            right = self.expr(bp)
            left = ('bin', op, left, right)

    def unary(self):
        kind, value = self.peek()
        if kind == 'op' and value in ('-', '+', '!'):
            self.take()
            return ('neg' if value == '-' else 'not' if value == '!' else 'pos', self.unary())
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == 'num':
            return ('lit', Decimal(value))
        if kind == 'str':
            return ('lit', value)
        if kind == 'ref':
            return ('ref', value)
        if kind == 'op' and value == '(':
            node = self.expr(0)
            self.take('op', ')')
            return node
        if kind == 'ident':
            name = value.upper()
            if self.peek() == ('op', '('):
                self.take()
                args = []
                if self.peek() != ('op', ')'):
                    args.append(self.expr(0))
                    while self.peek() == ('op', ','):
                        self.take()
                        args.append(self.expr(0))
                self.take('op', ')')
                if name not in FUNCTIONS:
                    raise FormulaError(f'There is no function {value}().')
                return ('call', name, args)
            if name in ('TRUE', 'FALSE'):
                return ('lit', name == 'TRUE')
            if name in ('BLANK', 'NULL'):
                return ('lit', None)
            raise FormulaError(f'"{value}" is not a function or a value; field names go in {{braces}}.')
        raise FormulaError(f'Unexpected "{value}".' if value else 'The formula ends too soon.')


_cache = {}


def parse(text):
    text = (text or '').strip()
    if text.startswith('='):
        text = text[1:]
    if text not in _cache:
        if len(_cache) > 2000:
            _cache.clear()
        _cache[text] = Parser(text).parse() if text else ('lit', None)
    return _cache[text]


def references(text):
    """The {names} a formula uses."""
    return [v for k, v in tokenize((text or '').lstrip('=')) if k == 'ref']


def check(text):
    """None if the formula parses, else what's wrong with it."""
    try:
        parse(text)
    except FormulaError as exc:
        return str(exc)
    return None


# -- Values ------------------------------------------------------------------------

def is_blank(v):
    return v is None or v == '' or (isinstance(v, list) and not v)


def unwrap(v):
    """A one-item list counts as that item."""
    while isinstance(v, list) and len(v) == 1:
        v = v[0]
    return v


def num(v, default=Decimal(0)):
    v = unwrap(v)
    if v is None or v == '' or (isinstance(v, list) and not v):
        return default
    if isinstance(v, bool):
        return Decimal(int(v))
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        try:
            return Decimal(v.strip().replace(',', ''))
        except InvalidOperation:
            raise FormulaError(f'"{v}" is not a number.')
    if isinstance(v, list):
        raise FormulaError('That is a list of values; use SUM(), MAX(), ... to get one number.')
    raise FormulaError(f'{v} is not a number.')


def text(v):
    v = unwrap(v)
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return str(v.quantize(Decimal(1)))
        return format(v.normalize(), 'f')
    if isinstance(v, datetime):
        return timezone.localtime(v).strftime('%Y-%m-%d %H:%M') if timezone.is_aware(v) else v.strftime('%Y-%m-%d %H:%M')
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, list):
        return ', '.join(text(x) for x in v)
    return str(v)


def truthy(v):
    v = unwrap(v)
    if isinstance(v, Decimal):
        return v != 0
    return bool(v) and v != '0'


def to_date(v):
    v = unwrap(v)
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return timezone.localtime(v).date() if timezone.is_aware(v) else v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip()[:10])
        except ValueError:
            raise FormulaError(f'"{v}" is not a date (use YYYY-MM-DD).')
    raise FormulaError(f'{text(v)} is not a date.')


def flatten(values):
    for v in values:
        if isinstance(v, list):
            yield from flatten(v)
        else:
            yield v


def numbers(values):
    out = []
    for v in flatten(values):
        if v is None or v == '':
            continue
        try:
            out.append(num(v))
        except FormulaError:
            continue
    return out


def compare(op, a, b):
    a, b = unwrap(a), unwrap(b)
    if op in ('=', '==', '!=', '<>'):
        if is_blank(a) or is_blank(b):
            same = is_blank(a) and is_blank(b)
        elif isinstance(a, (Decimal, int, float, bool)) or isinstance(b, (Decimal, int, float, bool)):
            try:
                same = num(a) == num(b)
            except FormulaError:
                same = text(a) == text(b)
        elif isinstance(a, date) or isinstance(b, date):
            try:
                same = to_date(a) == to_date(b) if not (isinstance(a, datetime) and isinstance(b, datetime)) else a == b
            except FormulaError:
                same = False
        else:
            same = text(a) == text(b)
        return same if op in ('=', '==') else not same
    # ordering
    if isinstance(a, date) or isinstance(b, date):
        if is_blank(a) or is_blank(b):
            return False
        x, y = (a, b) if isinstance(a, datetime) and isinstance(b, datetime) else (to_date(a), to_date(b))
    elif isinstance(a, str) and isinstance(b, str):
        try:
            x, y = num(a), num(b)
        except FormulaError:
            x, y = a.lower(), b.lower()
    else:
        x, y = num(a), num(b)
    return {'<': x < y, '<=': x <= y, '>': x > y, '>=': x >= y}[op]


def arith(op, a, b):
    a, b = unwrap(a), unwrap(b)
    # Dates: date ± days, date - date = days
    if isinstance(a, date) and op in '+-' and not isinstance(b, date):
        if is_blank(b):
            return a
        days = num(b)
        return a + timedelta(days=float(days)) if op == '+' else a - timedelta(days=float(days))
    if isinstance(a, date) and isinstance(b, date) and op == '-':
        return Decimal((to_date(a) - to_date(b)).days)
    if is_blank(a) and is_blank(b) and op in '+-':
        return None
    x, y = num(a), num(b)
    if op == '+':
        return x + y
    if op == '-':
        return x - y
    if op == '*':
        return x * y
    if y == 0:
        raise FormulaError('Division by zero.')
    return x / y if op == '/' else x % y


# -- Evaluation ----------------------------------------------------------------------

class Context:
    """What a formula can see. ``resolve(name)`` returns the value of {name};
    ``user`` is who's acting (USER()), ``record_id`` the record (RECORD_ID())."""

    def __init__(self, resolve, user=None, record_id=None):
        self.resolve = resolve
        self.user = user
        self.record_id = record_id


def evaluate(node, ctx):
    kind = node[0]
    if kind == 'lit':
        return node[1]
    if kind == 'ref':
        return ctx.resolve(node[1])
    if kind == 'neg':
        v = evaluate(node[1], ctx)
        return None if is_blank(v) else -num(v)
    if kind == 'pos':
        return num(evaluate(node[1], ctx))
    if kind == 'not':
        return not truthy(evaluate(node[1], ctx))
    if kind == 'bin':
        op = node[1]
        if op == '&&':
            return truthy(evaluate(node[2], ctx)) and truthy(evaluate(node[3], ctx))
        if op == '||':
            return truthy(evaluate(node[2], ctx)) or truthy(evaluate(node[3], ctx))
        a, b = evaluate(node[2], ctx), evaluate(node[3], ctx)
        if op == '&':
            return text(a) + text(b)
        if op in ('=', '==', '!=', '<>', '<', '<=', '>', '>='):
            return compare(op, a, b)
        return arith(op, a, b)
    if kind == 'call':
        fn, lazy = FUNCTIONS[node[1]]
        args = node[2]
        if lazy:
            return fn(ctx, [(lambda a=a: evaluate(a, ctx)) for a in args])
        return fn(ctx, [evaluate(a, ctx) for a in args])
    raise FormulaError('Broken formula.')


def run(text_, ctx):
    """Evaluate a formula; raises FormulaError when it can't be worked out."""
    try:
        return evaluate(parse(text_), ctx)
    except FormulaError:
        raise
    except (InvalidOperation, ArithmeticError, ValueError, TypeError, OverflowError) as exc:
        raise FormulaError(str(exc) or type(exc).__name__)
    except RecursionError:
        raise FormulaError('The formula refers to itself.')


# -- Functions -------------------------------------------------------------------------

FUNCTIONS = {}
HELP = []  # (signature, description) for the formula editor


def fn(signature, description, lazy=False):
    def register(f):
        FUNCTIONS[signature.split('(')[0]] = (f, lazy)
        HELP.append((signature, description))
        return f
    return register


def need(args, low, high=None, name=''):
    high = low if high is None else high
    if not (low <= len(args) <= high):
        raise FormulaError(f'{name}() takes {low if low == high else f"{low} to {high}"} values, not {len(args)}.')


@fn('IF(condition, then, else)', 'then if the condition holds, else else (blank if left out).', lazy=True)
def _if(ctx, args):
    need(args, 2, 3, 'IF')
    if truthy(args[0]()):
        return args[1]()
    return args[2]() if len(args) > 2 else None


@fn('IFS(cond1, value1, cond2, value2, ...)', 'The value of the first condition that holds.', lazy=True)
def _ifs(ctx, args):
    for i in range(0, len(args) - 1, 2):
        if truthy(args[i]()):
            return args[i + 1]()
    return None


@fn('SWITCH(value, case1, result1, ..., default)', 'The result whose case equals the value.', lazy=True)
def _switch(ctx, args):
    if not args:
        raise FormulaError('SWITCH() needs a value.')
    v, rest = args[0](), args[1:]
    for i in range(0, len(rest) - 1, 2):
        if compare('=', v, rest[i]()):
            return rest[i + 1]()
    return rest[-1]() if len(rest) % 2 else None


@fn('AND(a, b, ...)', 'TRUE if every value is true.', lazy=True)
def _and(ctx, args):
    return all(truthy(a()) for a in args)


@fn('OR(a, b, ...)', 'TRUE if any value is true.', lazy=True)
def _or(ctx, args):
    return any(truthy(a()) for a in args)


@fn('NOT(value)', 'TRUE if the value is false.')
def _not(ctx, args):
    need(args, 1, 1, 'NOT')
    return not truthy(args[0])


@fn('BLANK()', 'An empty value (e.g. to clear a field).')
def _blank(ctx, args):
    return None


@fn('TRUE()', 'Yes.')
def _true(ctx, args):
    return True


@fn('FALSE()', 'No.')
def _false(ctx, args):
    return False


@fn('IFERROR(value, fallback)', 'The value, or the fallback if it can\'t be worked out.', lazy=True)
def _iferror(ctx, args):
    need(args, 2, 2, 'IFERROR')
    try:
        return args[0]()
    except FormulaError:
        return args[1]()


@fn('ISBLANK(value)', 'TRUE if the value is empty.')
def _isblank(ctx, args):
    need(args, 1, 1, 'ISBLANK')
    return is_blank(unwrap(args[0]))


@fn('IN(value, option1, option2, ...)', 'TRUE if the value equals one of the options.')
def _in(ctx, args):
    if not args:
        raise FormulaError('IN() needs a value.')
    return any(compare('=', args[0], o) for o in flatten(args[1:]))


@fn('SUM(values...)', 'The total of the numbers (lists are added up too).')
def _sum(ctx, args):
    return sum(numbers(args), Decimal(0))


@fn('AVG(values...)', 'The average of the numbers.')
def _avg(ctx, args):
    vals = numbers(args)
    return sum(vals, Decimal(0)) / len(vals) if vals else None


FUNCTIONS['AVERAGE'] = FUNCTIONS['AVG']


@fn('MIN(values...)', 'The smallest number or earliest date.')
def _min(ctx, args):
    vals = [v for v in flatten(args) if not is_blank(v)]
    if vals and all(isinstance(v, date) for v in vals):
        return min(vals)
    vals = numbers(vals)
    return min(vals) if vals else None


@fn('MAX(values...)', 'The largest number or latest date.')
def _max(ctx, args):
    vals = [v for v in flatten(args) if not is_blank(v)]
    if vals and all(isinstance(v, date) for v in vals):
        return max(vals)
    vals = numbers(vals)
    return max(vals) if vals else None


@fn('COUNT(values...)', 'How many of the values are numbers.')
def _count(ctx, args):
    return Decimal(len(numbers(args)))


@fn('COUNTA(values...)', 'How many values are not empty.')
def _counta(ctx, args):
    return Decimal(sum(1 for v in flatten(args) if not is_blank(v)))


@fn('COUNTALL(values...)', 'How many values there are, empty ones too.')
def _countall(ctx, args):
    return Decimal(sum(1 for _ in flatten(args)))


def _round(v, places, mode):
    places = int(num(places)) if places is not None else 0
    q = Decimal(1).scaleb(-places)
    return num(v).quantize(q, rounding=mode)


@fn('ROUND(number, places)', 'Rounded to that many decimals (0 if left out).')
def _round_fn(ctx, args):
    need(args, 1, 2, 'ROUND')
    return None if is_blank(unwrap(args[0])) else _round(args[0], args[1] if len(args) > 1 else None, ROUND_HALF_UP)


@fn('ROUNDUP(number, places)', 'Rounded up.')
def _roundup(ctx, args):
    need(args, 1, 2, 'ROUNDUP')
    return _round(args[0], args[1] if len(args) > 1 else None, ROUND_CEILING)


@fn('ROUNDDOWN(number, places)', 'Rounded down.')
def _rounddown(ctx, args):
    need(args, 1, 2, 'ROUNDDOWN')
    return _round(args[0], args[1] if len(args) > 1 else None, ROUND_FLOOR)


@fn('ABS(number)', 'The number without its sign.')
def _abs(ctx, args):
    need(args, 1, 1, 'ABS')
    return abs(num(args[0]))


@fn('INT(number)', 'The whole number below it.')
def _int(ctx, args):
    need(args, 1, 1, 'INT')
    return num(args[0]).to_integral_value(rounding=ROUND_FLOOR)


@fn('MOD(number, divisor)', 'The remainder.')
def _mod(ctx, args):
    need(args, 2, 2, 'MOD')
    return arith('%', args[0], args[1])


@fn('POWER(number, power)', 'The number to the power.')
def _power(ctx, args):
    need(args, 2, 2, 'POWER')
    return Decimal(str(math.pow(float(num(args[0])), float(num(args[1])))))


@fn('SQRT(number)', 'The square root.')
def _sqrt(ctx, args):
    need(args, 1, 1, 'SQRT')
    return num(args[0]).sqrt()


@fn('VALUE(text)', 'The text as a number.')
def _value(ctx, args):
    need(args, 1, 1, 'VALUE')
    return num(args[0], None)


@fn('CONCAT(values...)', 'The values joined into one text.')
def _concat(ctx, args):
    return ''.join(text(a) for a in args)


@fn('JOIN(list, separator)', 'The list\'s values joined with the separator (", " if left out).')
def _join(ctx, args):
    need(args, 1, 2, 'JOIN')
    sep = text(args[1]) if len(args) > 1 else ', '
    return sep.join(text(v) for v in flatten([args[0]]) if not is_blank(v))


@fn('LEN(text)', 'How many characters.')
def _len(ctx, args):
    need(args, 1, 1, 'LEN')
    return Decimal(len(text(args[0])))


@fn('UPPER(text)', 'In capitals.')
def _upper(ctx, args):
    return text(args[0] if args else '').upper()


@fn('LOWER(text)', 'In small letters.')
def _lower(ctx, args):
    return text(args[0] if args else '').lower()


@fn('TRIM(text)', 'Without spaces at the ends.')
def _trim(ctx, args):
    return text(args[0] if args else '').strip()


@fn('LEFT(text, count)', 'The first characters.')
def _left(ctx, args):
    need(args, 2, 2, 'LEFT')
    return text(args[0])[:int(num(args[1]))]


@fn('RIGHT(text, count)', 'The last characters.')
def _right(ctx, args):
    need(args, 2, 2, 'RIGHT')
    n = int(num(args[1]))
    return text(args[0])[-n:] if n else ''


@fn('MID(text, start, count)', 'Characters from position start (1 is the first).')
def _mid(ctx, args):
    need(args, 3, 3, 'MID')
    start = max(int(num(args[1])) - 1, 0)
    return text(args[0])[start:start + int(num(args[2]))]


@fn('SUBSTITUTE(text, old, new)', 'Every old replaced by new.')
def _substitute(ctx, args):
    need(args, 3, 3, 'SUBSTITUTE')
    return text(args[0]).replace(text(args[1]), text(args[2]))


@fn('CONTAINS(text, part)', 'TRUE if the text contains the part (any case).')
def _contains(ctx, args):
    need(args, 2, 2, 'CONTAINS')
    return text(args[1]).lower() in text(args[0]).lower()


@fn('REPT(text, count)', 'The text repeated.')
def _rept(ctx, args):
    need(args, 2, 2, 'REPT')
    return text(args[0]) * max(0, min(int(num(args[1])), 1000))


@fn('TEXT(value, decimals)', 'The value as text; numbers with that many decimals.')
def _text(ctx, args):
    need(args, 1, 2, 'TEXT')
    if len(args) > 1 and not is_blank(unwrap(args[0])):
        return f'{_round(args[0], args[1], ROUND_HALF_UP):,}'
    return text(args[0])


@fn('TODAY()', 'Today\'s date.')
def _today(ctx, args):
    return timezone.localdate()


@fn('NOW()', 'The date and time now.')
def _now(ctx, args):
    return timezone.now()


@fn('DATE(year, month, day)', 'A date.')
def _date(ctx, args):
    need(args, 3, 3, 'DATE')
    return date(int(num(args[0])), int(num(args[1])), int(num(args[2])))


UNITS = {'day': 1, 'days': 1, 'week': 7, 'weeks': 7}


@fn('DATEADD(date, count, unit)', 'The date moved by count days, weeks, months or years.')
def _dateadd(ctx, args):
    need(args, 2, 3, 'DATEADD')
    d = unwrap(args[0])
    if is_blank(d):
        return None
    d = d if isinstance(d, date) else to_date(d)
    n = num(args[1])
    unit = text(args[2]).lower() if len(args) > 2 else 'days'
    if unit in UNITS:
        return d + timedelta(days=float(n) * UNITS[unit])
    if unit in ('month', 'months', 'year', 'years'):
        months = int(n) * (12 if unit.startswith('year') else 1)
        y, m = divmod(d.month - 1 + months, 12)
        year, month = d.year + y, m + 1
        import calendar
        return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))
    if unit in ('hour', 'hours') and isinstance(d, datetime):
        return d + timedelta(hours=float(n))
    raise FormulaError(f'DATEADD() doesn\'t know the unit "{unit}".')


@fn('DAYS(end, start)', 'The number of days from start to end.')
def _days(ctx, args):
    need(args, 2, 2, 'DAYS')
    a, b = to_date(args[0]), to_date(args[1])
    return None if a is None or b is None else Decimal((a - b).days)


@fn('WORKDAYS(start, end)', 'Monday to Friday days from start to end, both counted.')
def _workdays(ctx, args):
    need(args, 2, 2, 'WORKDAYS')
    a, b = to_date(args[0]), to_date(args[1])
    if a is None or b is None:
        return None
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    count, d = 0, a
    while d <= b:
        count += d.weekday() < 5
        d += timedelta(days=1)
    return Decimal(count * sign)


@fn('YEAR(date)', 'The year.')
def _year(ctx, args):
    d = to_date(args[0] if args else None)
    return Decimal(d.year) if d else None


@fn('MONTH(date)', 'The month, 1 to 12.')
def _month(ctx, args):
    d = to_date(args[0] if args else None)
    return Decimal(d.month) if d else None


@fn('DAY(date)', 'The day of the month.')
def _day(ctx, args):
    d = to_date(args[0] if args else None)
    return Decimal(d.day) if d else None


@fn('WEEKDAY(date)', 'The day of the week, 1 (Monday) to 7 (Sunday).')
def _weekday(ctx, args):
    d = to_date(args[0] if args else None)
    return Decimal(d.isoweekday()) if d else None


@fn('DATESTR(date, format)', 'The date as text, e.g. DATESTR({Due}, "%d %b %Y").')
def _datestr(ctx, args):
    need(args, 1, 2, 'DATESTR')
    d = unwrap(args[0])
    if is_blank(d):
        return ''
    d = d if isinstance(d, date) else to_date(d)
    return d.strftime(text(args[1])) if len(args) > 1 else text(d)


@fn('FIRST(list)', 'The first value of a list.')
def _first(ctx, args):
    vals = list(flatten(args))
    return vals[0] if vals else None


@fn('LAST(list)', 'The last value of a list.')
def _last(ctx, args):
    vals = list(flatten(args))
    return vals[-1] if vals else None


@fn('UNIQUE(list)', 'The list without repeats.')
def _unique(ctx, args):
    seen, out = set(), []
    for v in flatten(args):
        key = text(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


@fn('RECORD_ID()', 'The id of the record.')
def _record_id(ctx, args):
    return Decimal(ctx.record_id) if ctx.record_id else None


@fn('USER()', 'The name of the person acting (blank in scheduled automations).')
def _user(ctx, args):
    return str(ctx.user) if ctx.user else None


@fn('USER_ID()', 'The id of the person acting, e.g. to set a user field.')
def _user_id(ctx, args):
    return Decimal(ctx.user.pk) if ctx.user else None
