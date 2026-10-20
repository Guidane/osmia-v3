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
