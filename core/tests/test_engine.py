from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core import automation, formula, schema, service
from core.data import Data
from core.formula import FormulaError
from core.models import Automation, AutomationRun, Change, Link, Notification, Record


def ctx(values=None):
    values = values or {}

    def resolve(name):
        if name not in values:
            raise FormulaError(f'no {name}')
        return values[name]
    return formula.Context(resolve)


class FormulaTests(TestCase):
    def run_f(self, text, **values):
        return formula.run(text, ctx({k.replace('_', ' '): v for k, v in values.items()}))

    def test_arithmetic_and_precedence(self):
        self.assertEqual(self.run_f('1 + 2 * 3'), Decimal(7))
        self.assertEqual(self.run_f('(1 + 2) * 3'), Decimal(9))
        self.assertEqual(self.run_f('-2 + 5'), Decimal(3))
        self.assertEqual(self.run_f('10 / 4'), Decimal('2.5'))

    def test_fields_text_and_comparison(self):
        self.assertEqual(self.run_f('{Qty} * {Unit price}', Qty=Decimal(3), Unit_price=Decimal('2.5')), Decimal('7.5'))
        self.assertEqual(self.run_f('"PO-" & {N}', N=Decimal(7)), 'PO-7')
        self.assertTrue(self.run_f('{Status} = "Done"', Status='Done'))
        self.assertFalse(self.run_f('{Status} != "Done"', Status='Done'))
        self.assertTrue(self.run_f('{A} >= 2 && {A} < 3', A=Decimal(2)))

    def test_functions(self):
        self.assertEqual(self.run_f('IF({X} > 1, "big", "small")', X=Decimal(5)), 'big')
        self.assertEqual(self.run_f('SUM({L}, 1)', L=[Decimal(1), Decimal(2)]), Decimal(4))
        self.assertEqual(self.run_f('ROUND(2.345, 2)'), Decimal('2.35'))
        self.assertEqual(self.run_f('SWITCH("b", "a", 1, "b", 2, 3)'), Decimal(2))
        self.assertEqual(self.run_f('IFERROR(1/0, "n/a")'), 'n/a')
        self.assertEqual(self.run_f('DAYS(DATE(2026,1,10), DATE(2026,1,1))'), Decimal(9))
        self.assertEqual(self.run_f('DATEADD(DATE(2026,1,31), 1, "month")'), date(2026, 2, 28))
        self.assertEqual(self.run_f('JOIN(UNIQUE({L}), "/")', L=['a', 'b', 'a']), 'a/b')
        self.assertTrue(self.run_f('IN("x", "a", "x")'))
        self.assertEqual(self.run_f('DATE(2026,1,1) + 3'), date(2026, 1, 4))

    def test_mistakes(self):
        for bad in ['1 +', '{', 'NOPE(1)', 'abc', '(1']:
            self.assertIsNotNone(formula.check(bad), bad)
        with self.assertRaises(FormulaError):
            self.run_f('1/0')


class WorkspaceTestCase(TestCase):
    """An "orders" app: vendors, parts, orders with lines, stock moves."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('ann', password='x', first_name='Ann')
        self.app = schema.create_app('Shop', self.user)
        self.vendors = schema.create_table(self.app, 'Vendors')
        self.parts = schema.create_table(self.app, 'Parts', primary='Part number')
        self.orders = schema.create_table(self.app, 'Orders', primary=None)
        self.lines = schema.create_table(self.app, 'Lines', primary=None)
        self.moves = schema.create_table(self.app, 'Moves', primary=None)
        f = schema.add_field
        self.number = f(self.orders, 'Number', 'autonumber', {'prefix': 'PO-', 'digits': 4})
        self.orders.display_field = self.number
        self.orders.save()
        self.status = f(self.orders, 'Status', 'select', {
            'choices': [{'value': v} for v in ['Draft', 'Placed', 'Received', 'Cancelled']],
            'transitions': {'Draft': ['Placed', 'Cancelled'], 'Placed': ['Received', 'Cancelled']},
            'default': 'Draft', 'readonly': True})
        self.supplier = f(self.orders, 'Supplier', 'link', {'target': self.vendors.pk, 'multiple': False},
                          inverse_name='Orders', inverse_multiple=True)
        self.line_order = f(self.lines, 'Order', 'link', {'target': self.orders.pk, 'multiple': False},
                            inverse_name='Lines', inverse_multiple=True)
        self.lines.display_field = self.line_order
        self.lines.save()
        self.line_part = f(self.lines, 'Part', 'link', {'target': self.parts.pk, 'multiple': False},
                           inverse_name='Order lines')
        f(self.lines, 'Quantity', 'number')
        f(self.lines, 'Unit price', 'currency')
        f(self.lines, 'Total', 'formula', {'expression': '{Quantity} * {Unit price}', 'format': 'currency'})
        self.order_lines = self.orders.fields.get(name='Lines')
        f(self.orders, 'Total', 'rollup', {'link': self.order_lines.pk, 'field': self.lines.fields.get(name='Total').pk,
                                          'func': 'sum'})
        f(self.orders, 'Line count', 'rollup', {'link': self.order_lines.pk, 'func': 'count'})
        f(self.moves, 'Note', 'text')
        self.move_part = f(self.moves, 'Part', 'link', {'target': self.parts.pk}, inverse_name='Moves')
        f(self.moves, 'Quantity', 'number')
        part_moves = self.parts.fields.get(name='Moves')
        f(self.parts, 'On hand', 'rollup', {'link': part_moves.pk, 'field': self.moves.fields.get(name='Quantity').pk,
                                           'func': 'sum'})
        self.data = Data(self.user)

    def make_order(self, lines):
        acme = service.create_record(self.vendors, {'Name': 'Acme'}, self.user)
        order = service.create_record(self.orders, {'Supplier': [acme.pk]}, self.user)
        for part_number, qty, price in lines:
            part = Data().find_by_label(self.parts.pk, part_number) or \
                service.create_record(self.parts, {'Part number': part_number}, self.user)
            service.create_record(self.lines, {'Order': [order.pk], 'Part': [part.pk], 'Quantity': qty,
                                               'Unit price': price}, self.user)
        return order

    def value(self, record, name):
        data = Data(self.user)
        return data.value(data.record(record.pk), data.field_named(record.table_id, name))


class RecordTests(WorkspaceTestCase):
    def test_autonumber_default_and_rollups(self):
        order = self.make_order([('R1', 10, '0.10'), ('C1', 2, '1.50')])
        self.assertEqual(self.value(order, 'Number'), 'PO-0001')
        self.assertEqual(self.value(order, 'Status'), 'Draft')
        self.assertEqual(self.value(order, 'Total'), Decimal('4.00'))
        self.assertEqual(self.value(order, 'Line count'), Decimal(2))
        acme = Data().find_by_label(self.vendors.pk, 'Acme')
        self.assertEqual(list(self.value(acme, 'Orders')), ['PO-0001'])

    def test_paths_in_formulas(self):
        order = self.make_order([('R1', 10, '0.10'), ('C1', 2, '1.50')])
        data = Data(self.user)
        rec = data.record(order.pk)
        self.assertEqual(data.evaluate('{Supplier.Name}', rec), 'Acme')
        self.assertEqual(data.evaluate('SUM({Lines.Quantity})', rec), Decimal(12))
        self.assertEqual(data.evaluate('JOIN({Lines.Part.Part number})', rec), 'R1, C1')
        self.assertEqual(data.render('Order {Number} from {Supplier}', rec), 'Order PO-0001 from Acme')

    def test_readonly_and_transitions(self):
        order = self.make_order([('R1', 1, 1)])
        with self.assertRaises(ValidationError):
            service.update_record(order, {'Status': 'Placed'}, self.user)  # set by automations only
        with self.assertRaises(ValidationError):
            service.update_record(order, {'Status': 'Received'}, self.user, force=True)  # Draft can't jump to Received
        service.update_record(order, {'Status': 'Placed'}, self.user, force=True)
        self.assertEqual(self.value(order, 'Status'), 'Placed')

    def test_single_link_moves_the_record(self):
        a = self.make_order([('R1', 1, 1)])
        b = service.create_record(self.orders, {}, self.user)
        line = Record.objects.filter(table=self.lines).first()
        service.update_record(b, {'Lines': [line.pk]}, self.user)
        self.assertEqual(self.value(a, 'Line count'), Decimal(0))
        self.assertEqual(self.value(b, 'Line count'), Decimal(1))
        self.assertEqual(Link.objects.filter(field=self.line_order).count(), 1)

    def test_history(self):
        order = self.make_order([('R1', 1, 1)])
        service.update_record(order, {'Status': 'Placed'}, self.user, force=True)
        change = Change.objects.filter(record_id=order.pk, action='update').first()
        self.assertEqual(change.changes['Status'], ['Draft', 'Placed'])

    def test_rename_keeps_formulas(self):
        qty = self.lines.fields.get(name='Quantity')
        schema.update_field(qty, name='Qty')
        total = self.lines.fields.get(name='Total')
        self.assertEqual(total.opt('expression'), '{Qty} * {Unit price}')
        order = self.make_order([('R1', 3, 2)])
        self.assertEqual(self.value(order, 'Total'), Decimal(6))

    def test_type_change_converts(self):
        f = schema.add_field(self.vendors, 'Rating', 'text')
        v = service.create_record(self.vendors, {'Name': 'X', 'Rating': '4'}, self.user)
        service.create_record(self.vendors, {'Name': 'Y', 'Rating': 'great'}, self.user)
        schema.update_field(f, ftype='number')
        self.assertEqual(self.value(v, 'Rating'), Decimal(4))

    def test_delete_field_and_link_pair(self):
        schema.delete_field(self.supplier)
        self.assertFalse(self.vendors.fields.filter(name='Orders').exists())


class AutomationTests(WorkspaceTestCase):
    def test_button_runs_steps_for_each_line(self):
        place = Automation.objects.create(table=self.orders, name='Place', trigger='button', actions=[
            {'type': 'block_if_empty'} if False else {'type': 'update_record', 'target': 'this', 'values': {self.status.key: 'Placed'}},
        ])
        receive = Automation.objects.create(table=self.orders, name='Receive', trigger='button',
                                            conditions={'rules': [{'field': self.status.key, 'op': 'is', 'value': 'Placed'}]},
                                            actions=[
            {'type': 'create_record', 'table': self.moves.pk, 'for_each': self.order_lines.key,
             'values': {self.move_part.key: '={item.Part}', 'quantity': '={item.Quantity}',
                        'note': 'Received with {Number}'}},
            {'type': 'update_record', 'target': 'this', 'values': {self.status.key: 'Received'}},
        ])
        b1 = schema.add_field(self.orders, 'Place', 'button', {'label': 'Place', 'automation': place.pk})
        b2 = schema.add_field(self.orders, 'Receive', 'button', {'label': 'Receive', 'automation': receive.pk})
        order = self.make_order([('R1', 10, '0.10'), ('C1', 2, '1.50')])
        run = service.press_button(order, b2, self.user)
        self.assertEqual(run.status, 'skipped')  # still a draft
        self.assertEqual(service.press_button(order, b1, self.user).status, 'ok')
        run = service.press_button(order, b2, self.user)
        self.assertEqual(run.status, 'ok', run.log)
        self.assertEqual(self.value(order, 'Status'), 'Received')
        r1 = Data().find_by_label(self.parts.pk, 'R1')
        self.assertEqual(self.value(r1, 'On hand'), Decimal(10))
        note = Record.objects.filter(table=self.moves).first().data['note']
        self.assertEqual(note, 'Received with PO-0001')

    def test_block_undoes_the_change(self):
        Automation.objects.create(table=self.moves, name='No negative stock', trigger='record_created',
                                  conditions={'formula': '{Part.On hand} < 0'},
                                  actions=[{'type': 'block', 'message': 'Only {Part.On hand} left would be negative.'}])
        part = service.create_record(self.parts, {'Part number': 'R1'}, self.user)
        service.create_record(self.moves, {'Part': [part.pk], 'Quantity': 5}, self.user)
        with self.assertRaises(service.Blocked):
            service.create_record(self.moves, {'Part': [part.pk], 'Quantity': -8}, self.user)
        self.assertEqual(self.value(part, 'On hand'), Decimal(5))
        self.assertEqual(Record.objects.filter(table=self.moves).count(), 1)

    def test_failed_automation_keeps_the_change(self):
        Automation.objects.create(table=self.vendors, name='Broken', trigger='record_created',
                                  actions=[{'type': 'update_record', 'values': {'nope': 1}}])
        v = service.create_record(self.vendors, {'Name': 'Z'}, self.user)
        self.assertTrue(Record.objects.filter(pk=v.pk).exists())
        run = AutomationRun.objects.get()
        self.assertEqual(run.status, 'failed')

    def test_changed_to_and_watched_fields(self):
        Automation.objects.create(table=self.orders, name='Tell', trigger='record_updated',
                                  trigger_config={'fields': [self.status.key]},
                                  conditions={'rules': [{'field': self.status.key, 'op': 'changed_to', 'value': 'Placed'}]},
                                  actions=[{'type': 'notify', 'users': [self.user.pk], 'message': '{Number} placed'}])
        order = self.make_order([('R1', 1, 1)])
        service.update_record(order, {'Status': 'Placed'}, self.user, force=True)
        self.assertEqual(Notification.objects.get().message, 'PO-0001 placed')

    def test_condition_met_runs_once_when_all_lines_arrive(self):
        f = schema.add_field(self.lines, 'Arrived', 'checkbox')
        open_count = schema.add_field(self.orders, 'Open lines', 'rollup', {
            'link': self.order_lines.pk, 'func': 'count', 'filter': 'NOT({Arrived})'})
        auto = Automation.objects.create(table=self.orders, name='All in', trigger='condition_met',
                                         conditions={'formula': '{Line count} > 0 && {Open lines} = 0'},
                                         actions=[{'type': 'notify', 'users': [self.user.pk], 'message': '{Number} complete'}])
        order = self.make_order([('R1', 1, 1), ('C1', 1, 1)])
        lines = list(Record.objects.filter(table=self.lines))
        service.update_record(lines[0], {f.key: True}, self.user)
        self.assertEqual(Notification.objects.count(), 0)
        service.update_record(lines[1], {f.key: True}, self.user)
        self.assertEqual(Notification.objects.count(), 1)
        service.update_record(lines[1], {'Quantity': 3}, self.user)  # still met: no second run
        self.assertEqual(Notification.objects.count(), 1)

    def test_find_or_create(self):
        Automation.objects.create(table=self.moves, name='Vendor per note', trigger='record_created', actions=[
            {'type': 'find_or_create', 'table': self.vendors.pk, 'match': {'name': '{Note}'}},
        ])
        service.create_record(self.moves, {'Note': 'Acme'}, self.user)
        service.create_record(self.moves, {'Note': 'Acme'}, self.user)
        self.assertEqual(Record.objects.filter(table=self.vendors).count(), 1)

    def test_runaway_chain_stops(self):
        Automation.objects.create(table=self.vendors, name='Loop', trigger='record_updated',
                                  actions=[{'type': 'update_record', 'values': {'name': '={Name} & "x"'}}])
        v = service.create_record(self.vendors, {'Name': 'A'}, self.user)
        service.update_record(v, {'Name': 'B'}, self.user)
        self.assertLessEqual(len(self.value(v, 'Name')), 1 + automation.MAX_DEPTH + 1)

    def test_date_reached(self):
        due = schema.add_field(self.vendors, 'Review', 'date')
        Automation.objects.create(table=self.vendors, name='Review due', trigger='date_reached',
                                  trigger_config={'field': due.key, 'offset': 0},
                                  actions=[{'type': 'notify', 'users': [self.user.pk], 'message': 'Review {Name}'}])
        service.create_record(self.vendors, {'Name': 'A', 'Review': timezone.localdate().isoformat()}, self.user)
        service.create_record(self.vendors, {'Name': 'B', 'Review': (timezone.localdate() + timedelta(days=2)).isoformat()}, self.user)
        automation.tick()
        automation.tick()  # once a day only
        self.assertEqual(list(Notification.objects.values_list('message', flat=True)), ['Review A'])
