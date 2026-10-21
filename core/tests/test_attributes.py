"""Attributes fields: name-value pairs (Resistance 10 kΩ, Power 0.1 W), each shown as a tag."""
import importlib
import json

from core import blueprints, schema, service
from core.data import Data
from core.models import Record, Table
from core.tests.test_engine import WorkspaceTestCase
from core.views import fields_meta


class AttributeTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.attrs = schema.add_field(self.parts, 'Attributes', 'attributes')
        self.part = service.create_record(self.parts, {self.attrs.pk: 'Resistance: 10 kΩ\nPower = 0.1 W'}, user=self.user)

    def test_pairs_are_kept_in_order_and_shown_as_tags(self):
        data = Data()
        record = data.record(self.part.pk)
        self.assertEqual(data.raw(record, self.attrs), [{'name': 'Resistance', 'value': '10 kΩ'}, {'name': 'Power', 'value': '0.1 W'}])
        self.assertEqual(data.text(record, self.attrs), 'Resistance: 10 kΩ, Power: 0.1 W')
        self.assertEqual(str(data.html(record, self.attrs)).count('class="attr-tag"'), 2)

    def test_the_editor_saves_a_list_and_a_name_is_used_once(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_superuser('boss', 'b@example.com', 'x'))
        url = f'/api/records/{self.part.pk}/'
        sent = {'values': {self.attrs.pk: [{'name': 'Tolerance', 'value': '1%'}, {'name': 'Package', 'value': '0603'}]}}
        self.assertEqual(self.client.post(url, json.dumps(sent), content_type='application/json').status_code, 200)
        self.assertEqual([p['name'] for p in Record.objects.get(pk=self.part.pk).data[self.attrs.key]], ['Tolerance', 'Package'])
        twice = {'values': {self.attrs.pk: [{'name': 'Package', 'value': 'a'}, {'name': 'package', 'value': 'b'}]}}
        response = self.client.post(url, json.dumps(twice), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('two attributes are called', response.content.decode())
        nameless = {'values': {self.attrs.pk: [{'name': '', 'value': '5 V'}]}}
        self.assertEqual(self.client.post(url, json.dumps(nameless), content_type='application/json').status_code, 400)

    def test_formulas_and_search_read_them(self):
        power = schema.add_field(self.parts, 'Power', 'formula', {'expression': 'ATTRIBUTE({Attributes}, "power")'})
        data = Data()
        record = data.record(self.part.pk)
        self.assertEqual(data.text(record, power), '0.1 W')
        self.assertIn(self.part.pk, [r.pk for r in data.search(self.parts, '10 kΩ')])

    def test_names_used_are_suggested(self):
        service.create_record(self.parts, {self.attrs.pk: 'Voltage: 50 V'}, user=self.user)
        self.assertEqual(self.attrs.kind.names(self.attrs), ['Power', 'Resistance', 'Voltage'])
        self.assertEqual(fields_meta(Data(), [self.parts])[self.attrs.pk]['names'], ['Power', 'Resistance', 'Voltage'])

    def test_changing_a_text_field_to_attributes_and_back(self):
        notes = schema.add_field(self.parts, 'Notes', 'longtext')
        service.update_record(self.part, {notes.pk: 'Colour: red\nLength: 2 m'}, user=self.user)
        schema.update_field(notes, ftype='attributes')
        self.assertEqual(Record.objects.get(pk=self.part.pk).data[notes.key],
                         [{'name': 'Colour', 'value': 'red'}, {'name': 'Length', 'value': '2 m'}])
        schema.update_field(notes, ftype='longtext')
        self.assertEqual(Record.objects.get(pk=self.part.pk).data[notes.key], 'Colour: red\nLength: 2 m')


class PartsTemplateTests(WorkspaceTestCase):
    def test_the_parts_template_keeps_attributes_as_pairs(self):
        blueprints.install_many(['parts'], user=self.user, sample=True)
        table = Table.objects.get(app__blueprint='parts', key='parts')
        data = Data()
        resistor = next(r for r in data.records(table) if data.label(r) == 'RES-10K-0603')
        attrs = data.field_named(table, 'Attributes')
        self.assertEqual(attrs.type, 'attributes')
        self.assertEqual(data.raw(resistor, attrs)[0], {'name': 'Resistance', 'value': '10 kΩ'})

    def test_the_migration_turns_lines_into_pairs(self):
        pairs = importlib.import_module('core.migrations.0004_part_attributes').pairs
        self.assertEqual(pairs('Resistance: 10 kΩ\n\nPower = 0.1 W; Tolerance: 1%\nresistance: again'),
                         [{'name': 'Resistance', 'value': '10 kΩ'}, {'name': 'Power', 'value': '0.1 W'},
                          {'name': 'Tolerance', 'value': '1%'}])

    def test_every_demo_part_fills_in_what_its_category_lists(self):
        blueprints.install_many(['parts'], user=self.user, sample=True)
        parts = Table.objects.get(app__blueprint='parts', key='parts')
        data = Data()
        attrs = data.field_named(parts, 'Attributes')
        self.assertEqual(attrs.opt('names_from'), 'category.attribute_names')
        for part in data.records(parts):
            listed = [e['name'] for e in attrs.kind.expected(attrs, part, data)]
            filled = [p['name'] for p in data.raw(part, attrs)]
            self.assertTrue(listed, data.label(part))
            self.assertEqual(listed, filled, data.label(part))
        resistors = next(r for r in data.records(Table.objects.get(app__blueprint='parts', key='categories'))
                         if data.label(r) == 'Resistors')
        self.assertIn({'name': 'Resistance', 'hint': 'Ω'},
                      attrs.kind.expected(attrs, next(p for p in data.records(parts) if data.label(p) == 'RES-10K-0603'), data))
        self.assertIn('Package', attrs.kind.names(attrs))   # the categories' names are suggested
        self.assertEqual(data.raw(resistors, data.field_named(resistors.table, 'Attributes to fill in'))[0],
                         {'name': 'Resistance', 'value': 'Ω'})

    def test_the_record_tells_the_editor_what_to_fill_in(self):
        from django.contrib.auth import get_user_model
        blueprints.install_many(['parts'], user=self.user, sample=True)
        parts = Table.objects.get(app__blueprint='parts', key='parts')
        data = Data()
        wire = next(r for r in data.records(parts) if data.label(r) == 'WIRE-22-RED')
        attrs = data.field_named(parts, 'Attributes')
        self.client.force_login(get_user_model().objects.create_superuser('boss', 'b@example.com', 'x'))
        cell = self.client.get(f'/api/records/{wire.pk}/').json()['cells'][str(attrs.pk)]
        self.assertEqual([e['name'] for e in cell['expected']], ['Wire size', 'Colour', 'Insulation'])
        self.assertTrue(fields_meta(data, [parts])[attrs.pk]['expects'])

    def test_where_the_names_come_from_is_a_setting(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        blueprints.install_many(['parts'], user=self.user, sample=True)
        parts = Table.objects.get(app__blueprint='parts', key='parts')
        attrs = Data().field_named(parts, 'Attributes')
        self.client.force_login(get_user_model().objects.create_superuser('boss', 'b@example.com', 'x'))
        url = reverse('core:field_edit', args=[parts.app.slug, parts.slug, attrs.pk])
        self.assertContains(self.client.get(url), 'Category › Attributes to fill in')
        self.client.post(url, {'name': 'Attributes', 'type': 'attributes', 'names_from': ''})
        attrs.refresh_from_db()
        self.assertFalse(attrs.opt('names_from'))
        self.assertIsNone(attrs.kind.source(attrs))

    def test_the_migration_brings_the_demo_up_to_date_and_keeps_what_was_changed(self):
        from django.apps import apps
        upgrade = importlib.import_module('core.migrations.0005_category_attributes').upgrade
        blueprints.install_many(['parts'], user=self.user, sample=True)
        parts = Table.objects.get(app__blueprint='parts', key='parts')
        categories = Table.objects.get(app__blueprint='parts', key='categories')
        listed = categories.fields.get(key='attribute_names')
        attrs = parts.fields.get(key='attributes')
        # back to how the demo was before: names as lines of text, parts filled in less, and one changed by someone
        listed.type = 'longtext'
        listed.save()
        attrs.options = {}
        attrs.save()
        for r in Record.objects.filter(table=categories):
            r.data['attribute_names'] = {'Resistors': 'Resistance\nPower\nTolerance', 'Passives': 'Mine\nOurs'}.get(r.data.get('name'), '')
            r.save()
        for r in Record.objects.filter(table=parts):
            r.data['attributes'] = {'RES-10K-0603': [{'name': 'Resistance', 'value': '10 kΩ'}, {'name': 'Power', 'value': '0.1 W'},
                                                     {'name': 'Tolerance', 'value': '1%'}],
                                    'WIRE-22-RED': [{'name': 'Colour', 'value': 'crimson'}]}.get(r.data.get('part_number'), [])
            r.save()
        upgrade(apps, None)
        listed.refresh_from_db()
        attrs.refresh_from_db()
        self.assertEqual(listed.type, 'attributes')
        self.assertEqual(attrs.opt('names_from'), 'category.attribute_names')
        by_name = {r.data.get('name'): r.data['attribute_names'] for r in Record.objects.filter(table=categories)}
        self.assertEqual(by_name['Resistors'][0], {'name': 'Resistance', 'value': 'Ω'})     # the demo, brought up to date
        self.assertEqual(by_name['Passives'], [{'name': 'Mine', 'value': ''}, {'name': 'Ours', 'value': ''}])   # kept
        by_number = {r.data.get('part_number'): r.data['attributes'] for r in Record.objects.filter(table=parts)}
        self.assertEqual(len(by_number['RES-10K-0603']), 4)
        self.assertEqual(by_number['WIRE-22-RED'], [{'name': 'Colour', 'value': 'crimson'}])   # changed by someone: kept
        self.assertEqual(by_number['WIRE-22-BLK'][1], {'name': 'Colour', 'value': 'black'})


class ChoicesToTableTests(WorkspaceTestCase):
    def test_a_select_becomes_a_link_to_a_table_of_its_choices(self):
        kind = schema.add_field(self.parts, 'Kind', 'select', {'choices': [{'value': 'Resistor'}, {'value': 'Wire'}]})
        size = schema.add_field(self.parts, 'Size', 'formula', {'expression': 'UPPER({Kind})'})
        view = self.parts.views.first()
        view.config = {'fields': ['part_number', 'kind'], 'color_field': 'kind'}
        view.save()
        part = service.create_record(self.parts, {kind.pk: 'Wire'}, user=self.user)
        kinds = schema.choices_to_table(kind, 'Kinds', tree=True)
        link = self.parts.fields.get(key='kind')
        self.assertEqual((link.type, link.name, link.position), ('link', 'Kind', kind.position))
        self.assertEqual(kinds.tree_field.key, 'parent')
        data = Data()
        self.assertEqual([data.label(r) for r in data.records(kinds)], ['Resistor', 'Wire'])
        self.assertEqual(data.text(data.record(part.pk), link), 'Wire')          # what it had chosen
        self.assertEqual(data.text(data.record(part.pk), size), 'WIRE')          # formulas keep working
        view.refresh_from_db()
        self.assertEqual(view.config, {'fields': ['part_number', 'kind']})       # colours came from the choices
        self.assertNotIn('kind', Record.objects.get(pk=part.pk).data)

    def test_only_a_single_select(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            schema.choices_to_table(self.parts.fields.get(key='part_number'), 'X')


class ToolsTemplateTests(WorkspaceTestCase):
    def test_tool_types_list_what_each_tool_fills_in(self):
        from django.contrib.auth import get_user_model
        for name in ('alice', 'bob'):
            get_user_model().objects.create_user(name, password='x')
        blueprints.install_many(['tools'], user=self.user, sample=True)
        tools = Table.objects.get(app__blueprint='tools', key='tools')
        types = Table.objects.get(app__blueprint='tools', key='tool_types')
        self.assertEqual(types.tree_field.key, 'parent')
        data = Data()
        attrs = data.field_named(tools, 'Attributes')
        for tool in data.records(tools):
            listed = [e['name'] for e in attrs.kind.expected(attrs, tool, data)]
            self.assertTrue(listed, data.label(tool))
            self.assertEqual(listed, [p['name'] for p in data.raw(tool, attrs)], data.label(tool))

    def test_an_installed_tools_app_is_brought_up_to_date(self):
        from django.apps import apps
        from django.contrib.auth import get_user_model
        for name in ('alice', 'bob'):
            get_user_model().objects.create_user(name, password='x')
        bp = blueprints.available()['tools']
        old = json.loads(json.dumps(bp))   # the template as it was: Type a list of choices, no tool types
        old['tables'] = [t for t in old['tables'] if t['key'] == 'tools']
        tools_def = old['tables'][0]
        tools_def['fields'] = [f for f in tools_def['fields'] if f['key'] != 'attributes']
        type_field = next(f for f in tools_def['fields'] if f['key'] == 'type')
        type_field.clear()
        type_field.update({'key': 'type', 'name': 'Type', 'type': 'select', 'options': {'choices': [
            {'value': v} for v in ['Crimp tool', 'Insertion / extraction', 'Stripper', 'Meter', 'Other']]}})
        tools_def['views'] = [{'name': 'Tools', 'type': 'grid', 'config': {'fields': ['name', 'type', 'kept_at']}}]
        old['records'] = {'tools': [{k: v for k, v in r.items() if k != 'Attributes'} for r in old['records']['tools']]}
        blueprints.install(old, user=self.user, sample=True)
        importlib.import_module('core.migrations.0006_tool_types').tool_types(apps, None)
        tools = Table.objects.get(app__blueprint='tools', key='tools')
        types = Table.objects.get(app__blueprint='tools', key='tool_types')
        data = Data()
        crimp = next(r for r in data.records(tools) if data.label(r) == 'D-sub crimp tool')
        self.assertEqual(data.text(crimp, data.field_named(tools, 'Type')), 'Crimp tool')
        self.assertEqual(data.raw(crimp, data.field_named(tools, 'Attributes'))[0], {'name': 'Wire size', 'value': '20-24 AWG'})
        meter = next(r for r in data.records(types) if data.label(r) == 'Meter')
        from core.trees import Tree
        self.assertEqual(data.label(Tree(data, types).ancestors(meter.pk)[-1]), 'Test equipment')
        self.assertIn('attributes', tools.views.get(name='Tools').config['fields'])


class CopyAndFormTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model
        self.boss = get_user_model().objects.create_superuser('boss', 'b@example.com', 'x')
        blueprints.install_many(['parts'], user=self.boss, sample=True)
        self.table = Table.objects.get(app__blueprint='parts', key='parts')
        self.client.force_login(self.boss)

    def part(self, label):
        data = Data()
        return next(r for r in data.records(self.table) if data.label(r) == label)

    def test_copy_starts_a_new_part_from_one(self):
        from django.urls import reverse
        cap = self.part('CAP-100N-0603')
        page = self.client.get(cap.get_absolute_url())
        url = reverse('core:record_new', args=[self.table.app.slug, self.table.slug]) + f'?copy={cap.pk}'
        self.assertContains(page, url.replace('&', '&amp;'))
        form = self.client.get(url)
        self.assertContains(form, 'value="Capacitor 100 nF 50 V X7R 0603"')
        self.assertContains(form, 'Capacitance: 100 nF')                     # its attributes
        self.assertContains(form, 'A copy of CAP-100N-0603')
        data = Data()
        fields = {f.key: f for f in data.fields(self.table)}
        sent = {f'f_{fields["part_number"].pk}': 'CAP-1U-0603', f'f_{fields["description"].pk}': 'Capacitor 1 µF',
                f'f_{fields["attributes"].pk}': 'Capacitance: 1 µF\nVoltage: 25 V',
                f'f_{fields["category"].pk}': str(data.raw(cap, fields['category'])[0]['id'])
                if isinstance(data.raw(cap, fields['category'])[0], dict) else str(data.raw(cap, fields['category'])[0])}
        self.client.post(url, sent)
        copy = self.part('CAP-1U-0603')
        self.assertEqual(Data().text(copy, fields['category']), 'Capacitors')
        self.assertEqual(self.part('CAP-100N-0603').pk, cap.pk)   # the original stays as it was

    def test_a_new_parts_form_knows_where_its_attributes_to_fill_in_are(self):
        from django.urls import reverse
        data = Data()
        attrs, category = data.field_named(self.table, 'Attributes'), data.field_named(self.table, 'Category')
        listed = Table.objects.get(app__blueprint='parts', key='categories').fields.get(key='attribute_names')
        form = self.client.get(reverse('core:record_new', args=[self.table.app.slug, self.table.slug]))
        self.assertContains(form, f'data-source="{{&quot;link&quot;: {category.pk}, &quot;field&quot;: {listed.pk}}}"')
        self.assertContains(form, f'class="link-input" data-field="{category.pk}"')


class DeliveryDateTests(WorkspaceTestCase):
    def test_placing_an_order_fills_in_the_delivery_date_from_the_lead_time(self):
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        boss = get_user_model().objects.create_superuser('boss', 'b@example.com', 'x')
        blueprints.install_many(['orders', 'parts'], user=boss, sample=True)
        table = Table.objects.get(app__blueprint='orders', key='orders')
        data = Data()
        placed = [r for r in data.records(table) if data.text(r, data.field_named(table, 'Status')) != 'Draft']
        self.assertTrue(placed)
        for r in placed:
            self.assertTrue(data.text(r, data.field_named(table, 'Delivery date')), data.label(r))
        acme = next(r for r in placed if data.text(r, data.field_named(table, 'Supplier')) == 'Acme Components')
        self.assertEqual(data.value(acme, data.field_named(table, 'Delivery date')), timezone.localdate() + timedelta(days=5))
        self.assertTrue(table.views.filter(name='Deliveries', type='calendar').exists())
