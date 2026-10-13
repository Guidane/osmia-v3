"""The designer's JSON shapes, built from (and written to) the Devices and
Harness apps. The designer itself (static/harness/designer.js) is unchanged
from the stand-alone app; this module speaks its language.

Everything is read through core.data and written through core.service, so
history, validation and automations apply to what the designer does too.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from core import service
from core.data import Data
from core.extensions import registry
from core.formula import Records

ORIGINS = {'Made by us': 'in_house', 'External': 'external'}


def code(label):
    return slugify(label or '').replace('-', '_')


class Apps:
    """The tables of the Devices and Harness apps (made from the extension's templates)."""

    def __init__(self, user=None):
        self.data = Data(user)
        self.user = user
        self.devices = registry.table('devices', 'devices')
        self.connectors = registry.table('devices', 'connectors')
        self.pins = registry.table('devices', 'pins')
        self.signals = registry.table('devices', 'signals')
        self.pin_maps = registry.table('devices', 'pin_maps')
        self.projects = registry.table('harness', 'projects')
        self.rules = registry.table('harness', 'signal_rules')
        self.parts = registry.table('parts', 'parts')
        self.orders = registry.table('orders', 'orders')
        self.lines = registry.table('orders', 'lines')

    @property
    def ready(self):
        return all([self.devices, self.connectors, self.pins, self.signals, self.projects, self.rules])

    def f(self, table, key):
        return next((x for x in self.data.fields(table) if x.key == key), None)

    def get(self, record, key, default=None):
        field = self.f(record.table_id, key)
        if field is None:
            return default
        value = self.data.value(record, field)
        return default if value is None else value

    def text(self, record, key):
        field = self.f(record.table_id, key)
        return self.data.text(record, field) if field else ''

    def linked(self, record, key):
        field = self.f(record.table_id, key)
        return self.data.linked(record, field) if field else []

    def first(self, record, key):
        items = self.linked(record, key)
        return items[0] if items else None

    # -- devices ------------------------------------------------------------------

    def ordered(self, records, key='position'):
        def sort_key(r):
            v = self.get(r, key)
            try:
                return (0, float(v), r.pk)
            except (TypeError, ValueError):
                return (1, 0, r.pk)
        return sorted(records, key=sort_key)

    def device_json(self, device):
        data = self.data
        responsible = self.get(device, 'responsible')
        out = {
            'id': str(device.pk),
            'version': 1,
            'url': device.get_absolute_url(),
            'name': self.text(device, 'name') or f'Device {device.pk}',
            'part_number': self.text(device, 'part_number'),
            'color': self.text(device, 'color') or '#3b7dd8',
            'role': code(self.text(device, 'role')) or 'product',
            'origin': ORIGINS.get(self.text(device, 'origin'), 'in_house'),
            'responsible_user_id': str(responsible.ids[0]) if isinstance(responsible, Records) and responsible.ids else None,
            'connectors': [],
        }
        pin_ids = {}
        for c in self.ordered(self.linked(device, 'connectors')):
            try:
                tag_columns = max(1, min(4, int(self.get(c, 'tag_columns') or 1)))
            except (TypeError, ValueError):
                tag_columns = 1
            pins = []
            used = set()
            for i, p in enumerate(self.ordered(self.linked(c, 'pins')), 1):
                pid = self.text(p, 'position') or str(i)
                if pid in used:
                    pid = f'{pid}.{p.pk}'
                used.add(pid)
                pin_ids[p.pk] = (self.text(c, 'designator'), pid)
                set_number = self.get(p, 'set')
                pins.append({'id': pid, 'label': self.text(p, 'label') or pid,
                             'signal': self.text(p, 'signal'),
                             'tags': [self.text(p, f'tag{n}') for n in range(1, 5)],
                             'set': int(set_number) if set_number is not None else None,
                             'set_type': code(self.text(p, 'set_type'))})
            part = self.first(c, 'part')
            out['connectors'].append({
                'id': self.text(c, 'designator') or f'J{len(out["connectors"]) + 1:02d}',
                'side': self.text(c, 'side') if self.text(c, 'side') in ('left', 'right') else 'right',
                'tag_columns': tag_columns,
                'pins': pins,
                'part': {'part_number': data.label(part), 'name': self.text(part, 'description'),
                         'type': self.text(part, 'description') or data.label(part), 'url': part.get_absolute_url()} if part else None,
            })
        if out['role'] == 'interconnect' and self.pin_maps:
            out['pin_map'] = []
            for m in self.linked(device, 'pin_maps'):
                a, b = self.first(m, 'from_pin'), self.first(m, 'to_pin')
                if a and b and a.pk in pin_ids and b.pk in pin_ids:
                    out['pin_map'].append([*pin_ids[a.pk], *pin_ids[b.pk]])
        return out

    def all_devices(self):
        return [self.device_json(d) for d in self.data.records(self.devices)]

    @transaction.atomic
    def make_extension(self, device, designator):
        """A new interconnect device with exactly the pinout of ``device``'s
        connector: J01 (in) mapped pin for pin to J02 (out)."""
        connector = next((c for c in self.linked(device, 'connectors') if self.text(c, 'designator') == designator), None)
        if connector is None:
            raise ValidationError('That connector no longer exists on the device.')
        name = self.text(device, 'name')
        values = {'name': f'{name} {designator} extension', 'role': 'Interconnect', 'origin': self.text(device, 'origin') or 'Made by us',
                  'color': '#6b7280', 'notes': f'Extends {name} {designator}: J02 has the same pinout.'}
        if self.user is not None:
            values['responsible'] = self.user.pk
        ext = service.create_record(self.devices, values, self.user, self.data, force=True)
        tags = self.get(connector, 'tag_columns') or 1
        part = self.first(connector, 'part')
        common = {'device': [ext.pk], 'tag_columns': tags}
        inp = service.create_record(self.connectors, {**common, 'designator': 'J01', 'side': 'left', 'position': 1,
                                                      'function': f'In, from {name} {designator}'}, self.user, self.data, force=True)
        out_values = {**common, 'designator': 'J02', 'side': 'right', 'position': 2, 'function': f'Out, same pinout as {name} {designator}'}
        if part is not None and self.f(self.connectors, 'part'):
            out_values['part'] = [part.pk]
        out = service.create_record(self.connectors, out_values, self.user, self.data, force=True)
        for p in self.ordered(self.linked(connector, 'pins')):
            pin = {key: self.data.raw(p, self.f(self.pins, key)) for key in ('position', 'label', 'tag1', 'tag2', 'tag3', 'tag4', 'set', 'set_type')}
            signal = self.first(p, 'signal')
            if signal is not None:
                pin['signal'] = [signal.pk]
            a = service.create_record(self.pins, {**pin, 'connector': [inp.pk]}, self.user, self.data, force=True)
            b = service.create_record(self.pins, {**pin, 'connector': [out.pk]}, self.user, self.data, force=True)
            if self.pin_maps:
                service.create_record(self.pin_maps, {'device': [ext.pk], 'from_pin': [a.pk], 'to_pin': [b.pk]}, self.user, self.data, force=True)
        self.data.invalidate()
        return self.data.record(ext.pk)

    # -- projects -------------------------------------------------------------------

    def project_json(self, record, version=None):
        from .models import DrawingVersion
        if version:
            snap = DrawingVersion.objects.filter(record_id=record.pk, version=version).first()
            drawing = snap.data if snap else {}
        else:
            drawing = self.get(record, 'drawing') or {}
        drawing = {'instances': [], 'harnesses': [], **(drawing if isinstance(drawing, dict) else {})}
        current = self.get(record, 'version')
        return {**drawing, 'name': self.text(record, 'name') if not version else drawing.get('name', self.text(record, 'name')),
                'id': str(record.pk), 'version': int(version or current or 0)}

    @staticmethod
    def stats(drawing):
        harnesses = drawing.get('harnesses', [])
        wires = [c for h in harnesses for b in h.get('branches', []) for c in b.get('connections', [])]
        return {'device_count': len(drawing.get('instances', [])), 'harness_count': len(harnesses), 'wire_count': len(wires),
                'verified': sum(1 for w in wires if w.get('verified'))}

    @transaction.atomic
    def save_project(self, payload):
        from .models import DrawingVersion
        drawing = {k: v for k, v in payload.items() if k not in ('id', 'version', 'versions')}
        drawing.setdefault('instances', [])
        drawing.setdefault('harnesses', [])
        name = (drawing.get('name') or 'Untitled Harness')[:200]
        record = None
        if str(payload.get('id') or '').isdigit():
            record = self.data.record(int(payload['id']))
            if record is not None and record.table_id != self.projects.pk:
                record = None
        last = DrawingVersion.objects.filter(record_id=record.pk).order_by('-version').values_list('version', flat=True).first() if record else 0
        values = {'name': name, 'drawing': drawing, 'version': (last or 0) + 1, **self.stats(drawing)}
        if record is None:
            record = service.create_record(self.projects, values, self.user, self.data, force=True)
        else:
            service.update_record(record, values, self.user, self.data, force=True)
        DrawingVersion.objects.create(record_id=record.pk, version=values['version'], data=drawing, created_by=self.user)
        self.data.invalidate()
        return self.data.record(record.pk)

    @transaction.atomic
    def activate(self, record, version):
        from .models import DrawingVersion
        snap = DrawingVersion.objects.get(record_id=record.pk, version=version)
        service.update_record(record, {'drawing': snap.data, 'version': version, 'name': snap.data.get('name') or self.text(record, 'name'),
                                       **self.stats(snap.data)}, self.user, self.data, force=True)
        self.data.invalidate()
        return self.data.record(record.pk)

    def projects_using(self, device_id):
        out = []
        for p in self.data.records(self.projects):
            drawing = self.get(p, 'drawing') or {}
            if any(str(i.get('device_id')) == str(device_id) for i in drawing.get('instances', []) if isinstance(i, dict)):
                out.append(p)
        return out

    # -- signal rules -------------------------------------------------------------------

    def rule_pairs(self):
        return [[self.text(r, 'signal_a'), self.text(r, 'signal_b')] for r in self.data.records(self.rules)
                if self.text(r, 'signal_a') and self.text(r, 'signal_b')]

    def signal(self, name):
        name = str(name).strip()[:50]
        found = next((s for s in self.data.records(self.signals) if self.text(s, 'name').lower() == name.lower()), None)
        return found or service.create_record(self.signals, {'name': name}, self.user, self.data, force=True)

    @transaction.atomic
    def replace_rules(self, pairs):
        for r in list(self.data.records(self.rules)):
            service.delete_record(r, self.user, self.data)
        seen = set()
        for a, b in pairs:
            a, b = str(a).strip(), str(b).strip()
            key = tuple(sorted((a.upper(), b.upper())))
            if a and b and key not in seen:
                seen.add(key)
                service.create_record(self.rules, {'signal_a': [self.signal(a).pk], 'signal_b': [self.signal(b).pk]},
                                      self.user, self.data, force=True)

    # -- parts and orders ------------------------------------------------------------------

    def part_list(self):
        if not self.parts:
            return []
        return [{'part_number': self.data.label(p), 'name': self.text(p, 'description')} for p in self.data.records(self.parts)
                if self.get(p, 'active', True) is not False]

    @transaction.atomic
    def draft_order(self, lines, note=''):
        if not (self.orders and self.lines and self.parts):
            raise ValidationError('The Orders app is not installed.')
        wanted = {}
        for line in lines or []:
            number = str(line.get('part_number') or '').strip()
            try:
                qty = int(line.get('quantity') or 1)
            except (TypeError, ValueError):
                qty = 1
            if number and qty > 0:
                wanted[number] = wanted.get(number, 0) + qty
        parts = {self.data.label(p): p for p in self.data.records(self.parts)}
        missing = sorted(n for n in wanted if n not in parts)
        if not any(n in parts for n in wanted):
            raise ValidationError('None of those parts are in Parts: ' + ', '.join(missing) if missing else 'No parts to order.')
        note = str(note or '')[:1000]
        if missing:
            note += ('\n' if note else '') + 'Not in Parts, so not ordered: ' + ', '.join(missing)
        order = service.create_record(self.orders, {'notes': note}, self.user, self.data, force=True)
        for number, qty in wanted.items():
            if number in parts:
                price = self.get(parts[number], 'average_cost') or 0
                service.create_record(self.lines, {'order': [order.pk], 'part': [parts[number].pk], 'quantity': qty,
                                                   'unit_price': str(price)}, self.user, self.data, force=True)
        self.data.invalidate()
        order = self.data.record(order.pk)
        return {'number': self.data.label(order), 'url': order.get_absolute_url(), 'missing': missing,
                'lines': sum(1 for n in wanted if n in parts)}
