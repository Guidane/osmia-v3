"""Harnesses: connectors (a part and its gender) and the wires between them, contact to contact; a harness's page
lists its wires under a sub-header for each pair of connectors."""
import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import blueprints, schema, service
from core.data import Data
from core.models import App, Table


class HarnessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['parts', 'harnesses'], user=cls.admin, sample=True)
        cls.harnesses = Table.objects.get(app__blueprint='harnesses', key='harnesses')
        cls.connectors = Table.objects.get(app__blueprint='harnesses', key='connectors')
        cls.wires = Table.objects.get(app__blueprint='harnesses', key='wires')

    def setUp(self):
        self.client.force_login(self.admin)

    def loom(self):
        data = Data()
        return next(r for r in data.records(self.harnesses) if data.label(r) == 'Burn-in rack loom')

    def test_a_connector_shows_its_part_and_the_parts_gender(self):
        data = Data()
        self.assertEqual(sorted(data.label(r) for r in data.records(self.connectors)),
                         ['X1 · DSUB-9-PLUG · male', 'Y1 · DSUB-9-RECEPT · female', 'Y2 · DSUB-9-RECEPT · female'])

    def test_the_harness_page_groups_its_wires_by_pair_of_connectors(self):
        html = self.client.get(self.loom().get_absolute_url()).content.decode()
        heads = html.count('class="sub-group-head')
        self.assertEqual(heads, 2)   # X1 → Y1 and X1 → Y2
        first, second = html.index('Y1 · DSUB-9-RECEPT'), html.index('Y2 · DSUB-9-RECEPT')
        self.assertLess(first, second)
        # the pinout first, then colour, AWG and length
        section = html[html.index('class="sub-bands"'):]
        # A | B | Wire details above the columns; the pinout in the middle: function, contact, contact, function
        bands = [section.index(b) for b in ('>A<', '>B<', '>Wire details<')]
        self.assertEqual(bands, sorted(bands))
        cols = ('A function', 'A contact', 'B contact', 'B function', 'Set type', 'Colour', 'AWG', 'Length (mm)', 'Part')
        positions = [section.index(f'>{c}<') for c in cols]
        self.assertEqual(positions, sorted(positions))
        # X1 heads the first group only: the second has the same A connector
        heads = section[section.index('sub-group-head'):]
        self.assertEqual(heads.count('X1 · DSUB-9-PLUG · male</a>'), 1)

    def test_wires_are_in_contact_order_counting_like_people(self):
        loom = self.loom()
        data = Data()
        from_x1 = next(r for r in data.records(self.connectors) if data.label(r).startswith('X1'))
        to_y1 = next(r for r in data.records(self.connectors) if data.label(r).startswith('Y1'))
        fields = {f.key: f for f in data.fields(self.wires)}
        service.create_record(self.wires, {fields['harness'].pk: [loom.pk], fields['from'].pk: [from_x1.pk],
                                           fields['source_contact'].pk: '10', fields['to'].pk: [to_y1.pk],
                                           fields['target_contact'].pk: '2'}, user=self.admin)
        html = self.client.get(loom.get_absolute_url()).content.decode()
        block = html[html.index('Y1 · DSUB-9-RECEPT'):html.index('Y2 · DSUB-9-RECEPT')]
        self.assertLess(block.index('>3<'), block.index('>10<'))   # 1, 2, 3, 10: not 1, 10, 2, 3

    def test_a_sub_header_adds_a_wire_between_its_connectors(self):
        html = self.client.get(self.loom().get_absolute_url()).content.decode()
        add = html[html.index('class="sub-group-add" href="') + len('class="sub-group-add" href="'):]
        add = add[:add.index('"')].replace('&amp;', '&')
        data = Data()
        fields = {f.key: f for f in data.fields(self.wires)}
        x1 = next(r for r in data.records(self.connectors) if data.label(r).startswith('X1'))
        self.assertIn(f'f_{fields["from"].pk}={x1.pk}', add)
        form = self.client.get(add)
        self.assertContains(form, f'&quot;id&quot;: {x1.pk}')   # the From connector is filled in

    def test_how_a_link_shows_is_a_setting(self):
        inverse = Data().field_named(self.harnesses, 'Wires')
        url = reverse('core:field_edit', args=[self.harnesses.app.slug, self.harnesses.slug, inverse.pk])
        self.assertContains(self.client.get(url), "On the record's page")
        self.client.post(url, {'name': 'Wires', 'type': 'link', 'multiple': '1', 'target': inverse.opt('target'),
                               'show_editing': '1', 'show_fields': ['source_contact', 'target_contact'],
                               'show_sort': 'source_contact', 'show_group': ['from'], 'show_join': '·'})
        inverse.refresh_from_db()
        self.assertEqual(inverse.opt('show'), {'fields': ['source_contact', 'target_contact'], 'sort': ['source_contact'],
                                               'group_by': ['from'], 'group_join': ' · '})
        self.assertEqual(self.client.get(self.loom().get_absolute_url()).content.decode().count('class="sub-group-head"'), 1)


class HarnessSidesTests(TestCase):
    def test_an_installed_harnesses_app_gets_sides_a_and_b(self):
        import json
        from django.apps import apps
        admin = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['parts'], user=admin, sample=True)
        bp = json.loads(json.dumps(blueprints.available()['harnesses']))   # as it was: Source and Target, a Signal
        tables = {tb['key']: tb for tb in bp['tables']}
        next(f for f in tables['connectors']['fields'] if f['key'] == 'side')['options']['choices'] = [
            {'value': 'Source'}, {'value': 'Target'}]
        wires = tables['wires']
        wires['fields'] = [f for f in wires['fields'] if f['key'] not in ('a_function', 'b_function', 'set_type', 'part')]
        names = {'from': 'From', 'source_contact': 'Source contact', 'to': 'To', 'target_contact': 'Target contact'}
        for f in wires['fields']:
            f['name'] = names.get(f['key'], f['name'])
        next(f for f in wires['fields'] if f['key'] == 'label')['options']['expression'] = '{Source contact}'
        wires['fields'].append({'key': 'signal', 'name': 'Signal', 'type': 'text'})
        wires['views'] = []
        bp['records'] = {'harnesses': [{'Name': 'Burn-in rack loom'}],
                         'connectors': [{'Designator': 'X1', 'Harness': 'Burn-in rack loom', 'Side': 'Source', 'Part': 'DSUB-9-PLUG'}]}
        blueprints.install(bp, user=admin, sample=True)
        data = Data()
        wires_table = Table.objects.get(app__blueprint='harnesses', key='wires')
        x1 = Table.objects.get(app__blueprint='harnesses', key='connectors').records.first()
        harness = Table.objects.get(app__blueprint='harnesses', key='harnesses').records.first()
        f = {fd.key: fd for fd in data.fields(wires_table)}
        wire = service.create_record(wires_table, {f['harness'].pk: [harness.pk], f['from'].pk: [x1.pk], f['source_contact'].pk: '1',
                                                   f['target_contact'].pk: '1', f['signal'].pk: '+24 V'}, user=admin)
        importlib.import_module('core.migrations.0008_harness_sides').sides(apps, None)
        data = Data()
        f = {fd.key: fd for fd in data.fields(wires_table)}
        self.assertEqual([f[k].name for k in ('from', 'a_function', 'source_contact', 'to', 'target_contact', 'b_function')],
                         ['A connector', 'A function', 'A contact', 'B connector', 'B contact', 'B function'])
        self.assertNotIn('signal', f)
        wire = data.record(wire.pk)
        self.assertEqual((data.text(wire, f['a_function']), data.text(wire, f['b_function'])), ('+24 V', '+24 V in'))
        self.assertEqual(data.text(wire, f['set_type']), 'Twisted')
        self.assertEqual(data.text(wire, f['part']), 'WIRE-22-RED')
        self.assertEqual(data.text(data.record(x1.pk), data.field_named(x1.table, 'Side')), 'A')


class HarnessDesignerGoneTests(TestCase):
    def test_the_designer_and_its_apps_are_removed(self):
        from django.apps import apps
        admin = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['parts', 'assemblies'], user=admin, sample=True)
        # as the designer left them: a Devices app linking to parts and assemblies, and a Harness app needing it
        devices = schema.create_app('Devices', admin, blueprint='devices')
        table = schema.create_table(devices, 'Devices')
        schema.add_field(table, 'Assembly', 'link', {'target': Table.objects.get(app__blueprint='assemblies', key='assemblies').pk},
                         inverse_name='Devices')
        schema.create_table(schema.create_app('Harness', admin, blueprint='harness'), 'Projects')
        importlib.import_module('core.migrations.0007_remove_harness_designer').remove_harness_designer(apps, _Editor())
        self.assertFalse(App.objects.filter(blueprint__in=['devices', 'harness']).exists())
        self.assertFalse(Table.objects.get(app__blueprint='assemblies', key='assemblies').fields.filter(name='Devices').exists())


class _Editor:
    from django.db import connection


_Editor.connection = _Editor.connection
