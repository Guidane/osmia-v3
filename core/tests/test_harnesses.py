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
        labels = sorted(data.label(r) for r in data.records(self.connectors))
        # the connectors with their designator, part and gender; the other parts (contacts, wire, ties) by their part
        self.assertEqual([l for l in labels if ' · ' in l],
                         ['X1 · DSUB-9-PLUG · male', 'Y1 · DSUB-9-RECEPT · female', 'Y2 · DSUB-9-RECEPT · female'])
        self.assertEqual([l for l in labels if ' · ' not in l], ['DSUB-9-CONTACT', 'TIE-100', 'WIRE-22-BLK', 'WIRE-22-RED'])

    def test_the_build_time_is_the_time_per_wire_times_the_wires(self):
        data = Data()
        loom = data.record(self.loom().pk)
        self.assertEqual(data.text(loom, data.field_named(self.harnesses, 'Build time (min)')), '21')   # 7 wires × 3 min
        html = self.client.get(loom.get_absolute_url()).content.decode()
        self.assertIn('<h3>Parts ', html)
        self.assertIn('<h3>Pinout ', html)

    def test_the_harness_page_groups_its_wires_by_pair_of_connectors(self):
        html = self.client.get(self.loom().get_absolute_url()).content.decode()
        heads = html.count('class="sub-group-head')
        self.assertEqual(heads, 2)   # X1 → Y1 and X1 → Y2
        first, second = html.index('<span>Y1 · female</span>'), html.index('<span>Y2 · female</span>')
        self.assertLess(first, second)
        # the pinout first, then colour, AWG and length
        section = html[html.index('class="sub-bands"'):]
        # A | B | Wire details above the columns; the pinout in the middle: function, contact, contact, function
        bands = [section.index(b) for b in ('>A<', '>B<', '>Wire details<')]
        self.assertEqual(bands, sorted(bands))
        cols = ('A function', 'A contact', 'B contact', 'B function', 'Set', 'Set type', 'Colour', 'AWG', 'Length (mm)', 'Part')
        positions = [section.index(f'>{c}<') for c in cols]
        self.assertEqual(positions, sorted(positions))
        # X1 heads the first group only: the second has the same A connector
        heads = section[section.index('sub-group-head'):]
        # each connector on two lines: its part, then its designator and gender
        self.assertEqual(heads.count('<span>DSUB-9-PLUG</span><span>X1 · male</span></a>'), 1)

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
        block = html[html.index('<span>Y1 · female</span>'):html.index('<span>Y2 · female</span>')]
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
        inverse = Data().field_named(self.harnesses, 'Pinout')
        url = reverse('core:field_edit', args=[self.harnesses.app.slug, self.harnesses.slug, inverse.pk])
        self.assertContains(self.client.get(url), "On the record's page")
        self.client.post(url, {'name': 'Pinout', 'type': 'link', 'multiple': '1', 'target': inverse.opt('target'),
                               'show_editing': '1', 'show_fields': ['source_contact', 'target_contact'],
                               'show_sort': 'source_contact', 'show_group': ['from'], 'show_join': '·'})
        inverse.refresh_from_db()
        self.assertEqual(inverse.opt('show'), {'fields': ['source_contact', 'target_contact'], 'sort': ['source_contact'],
                                               'group_by': ['from'], 'group_join': ' · '})
        self.assertEqual(self.client.get(self.loom().get_absolute_url()).content.decode().count('class="sub-group-head"'), 1)

    def test_a_line_runs_where_each_band_starts(self):
        html = self.client.get(self.loom().get_absolute_url()).content.decode()
        colgroup = html[html.index('<colgroup>'):html.index('</colgroup>')]
        cols = colgroup.split('<col')[2:]
        # A function, A contact | B contact, B function | set, set type, colour, AWG, length, part | (the ⤢ column)
        self.assertEqual([i for i, c in enumerate(cols) if 'band-edge' in c], [2, 4])


class HarnessSetsAndBuildsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['parts', 'harnesses'], user=cls.admin, sample=True)
        cls.harnesses = Table.objects.get(app__blueprint='harnesses', key='harnesses')
        cls.wires = Table.objects.get(app__blueprint='harnesses', key='wires')
        cls.builds = Table.objects.get(app__blueprint='harnesses', key='builds')
        cls.checks = Table.objects.get(app__blueprint='harnesses', key='checks')

    def setUp(self):
        self.client.force_login(self.admin)

    def loom(self):
        data = Data()
        return next(r for r in data.records(self.harnesses) if data.label(r) == 'Burn-in rack loom')

    def pinout(self, html):
        start = html.index('<h3>Pinout ')
        return html[start:html.index('</table>', start)]

    def test_the_wires_of_a_set_stay_together_with_an_outline(self):
        data = Data()
        loom = self.loom()
        fields = {f.key: f for f in data.fields(self.wires)}
        enable = next(r for r in data.linked(loom, data.field_named(self.harnesses, 'Pinout'))
                      if data.text(r, fields['a_function']) == 'Enable')
        service.update_record(enable, {fields['set'].pk: 'P2'}, user=self.admin)   # pin 3 joins pin 6 and 7's set
        html = self.pinout(self.client.get(loom.get_absolute_url()).content.decode())
        y1 = html[html.index('<span>Y1 · female</span>'):html.index('<span>Y2 · female</span>')]
        y2 = html[html.index('<span>Y2 · female</span>'):]
        self.assertEqual(y1.count('set-row'), 2)   # P1; Enable is alone in its group: no outline
        self.assertEqual(y2.count('set-first'), 1)
        self.assertEqual(y2.count('set-row'), 3)   # CAN H, CAN L and the shield, together: CAN GND (9) after them
        self.assertLess(y2.index('>Shield<'), y2.index('>CAN GND<'))

    def test_a_shielded_set_has_its_shield_on_contacts(self):
        data = Data()
        fields = {f.key: f for f in data.fields(self.wires)}
        shield = next(r for r in data.records(self.wires) if data.text(r, fields['set_type']) == 'Shield')
        self.assertEqual((data.text(shield, fields['set']), data.text(shield, fields['source_contact']),
                          data.text(shield, fields['target_contact'])), ('P2', '8', '8'))

    def test_build_harness_makes_a_build_with_its_id_and_a_checklist(self):
        data = Data()
        loom = self.loom()
        before = list(data.records(self.builds))
        self.assertEqual([data.label(r) for r in before], ['SN-00001'])   # the demo's
        button = data.field_named(self.harnesses, 'Build')
        response = self.client.post(reverse('core:api_button', args=[loom.pk, button.pk]), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = Data()
        build = next(r for r in data.records(self.builds) if data.label(r) == 'SN-00002')
        self.assertEqual(data.text(build, data.field_named(self.builds, 'Harness')), 'Burn-in rack loom')
        checks = data.linked(build, data.field_named(self.builds, 'Checklist'))
        self.assertEqual(len(checks), 7)
        self.assertEqual(data.text(build, data.field_named(self.builds, 'Progress')), 'Not started')
        placed, verified = data.field_named(self.checks, 'Placed'), data.field_named(self.checks, 'Verified')
        for check in checks[:2]:
            service.update_record(check, {placed.pk: True}, user=self.admin)
        service.update_record(checks[0], {verified.pk: True}, user=self.admin)
        build = Data().record(build.pk)
        self.assertEqual(Data().text(build, data.field_named(self.builds, 'Progress')), '2 of 7 placed, 1 verified')
        # its page: the checklist like the pinout, with nothing to add by hand
        html = self.client.get(build.get_absolute_url()).content.decode()
        self.assertIn('<h3>Checklist ', html)
        self.assertNotIn('＋ New', html[html.index('<h3>Checklist '):])
        self.assertIn('set-row', html)

    def test_a_harness_without_a_pinout_cannot_be_built(self):
        data = Data()
        empty = service.create_record(self.harnesses, {data.field_named(self.harnesses, 'Name').pk: 'Empty'}, user=self.admin)
        button = data.field_named(self.harnesses, 'Build')
        self.client.post(reverse('core:api_button', args=[empty.pk, button.pk]), content_type='application/json')
        self.assertFalse(any(Data().text(r, data.field_named(self.builds, 'Harness')) == 'Empty'
                             for r in Data().records(self.builds)))

    def test_buttons_at_the_bottom_add_a_connector_on_a_or_b_and_a_wire(self):
        html = self.pinout(self.client.get(self.loom().get_absolute_url()).content.decode())
        foot = html[html.index('<tfoot>'):]
        for label in ('Connector on A', 'Connector on B', 'Wire'):
            self.assertIn(f'＋ {label}</a>', foot)
        head = html[:html.index('<table')]
        self.assertNotIn('＋ New', head)   # adding a wire is at the bottom
        data = Data()
        connectors = Table.objects.get(app__blueprint='harnesses', key='connectors')
        side = data.field_named(connectors, 'Side')
        on_b = foot[:foot.index('＋ Connector on B')]
        on_b = on_b[on_b.rindex('href="') + 6:].split('"')[0].replace('&amp;', '&')
        self.assertIn(f'f_{side.pk}=B', on_b)
        self.assertContains(self.client.get(on_b), '<option selected>B</option>')


class HarnessSetsMigrationTests(TestCase):
    def test_an_installed_harnesses_app_gets_sets_and_builds(self):
        import json
        from django.apps import apps
        admin = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['parts'], user=admin, sample=True)
        bp = json.loads(json.dumps(blueprints.available()['harnesses']))   # as it was: no sets, no builds
        bp['tables'] = [tb for tb in bp['tables'] if tb['key'] not in ('builds', 'checks')]
        tables = {tb['key']: tb for tb in bp['tables']}
        tables['wires']['fields'] = [f for f in tables['wires']['fields'] if f['key'] not in ('set', 'id')]
        tables['harnesses']['fields'] = [f for f in tables['harnesses']['fields'] if f['key'] != 'build']
        set_type = next(f for f in tables['wires']['fields'] if f['key'] == 'set_type')
        set_type['options']['choices'] = [c for c in set_type['options']['choices'] if c['value'] != 'Shield']
        show = next(f for f in tables['wires']['fields'] if f['key'] == 'harness')['options']['inverse']['show']
        for k in ('keep_together', 'group_lines', 'add_below'):
            show.pop(k)
        show['fields'].remove('set')
        next(g for g in show['column_groups'] if g['label'] == 'Wire details')['fields'].remove('set')
        tables['wires']['views'][0]['config']['fields'].remove('set')
        bp['automations'] = [a for a in bp.get('automations') or [] if a['key'] != 'build']
        bp['after_records'] = []
        bp['records']['wires'] = [{k: v for k, v in w.items() if k != 'Set'} for w in bp['records']['wires']
                                  if w.get('Set type') != 'Shield']
        blueprints.install(bp, user=admin, sample=True)
        importlib.import_module('core.migrations.0012_harness_sets_builds').sets_and_builds(apps, None)
        data = Data()
        harnesses = Table.objects.get(app__blueprint='harnesses', key='harnesses')
        wires = Table.objects.get(app__blueprint='harnesses', key='wires')
        loom = harnesses.records.first()
        pinout = data.linked(loom, data.field_named(harnesses, 'Pinout'))
        sets = sorted((data.text(r, data.field_named(wires, 'A contact')), data.text(r, data.field_named(wires, 'Set'))) for r in pinout)
        self.assertEqual(sets, [('1', 'P1'), ('2', 'P1'), ('3', ''), ('6', 'P2'), ('7', 'P2'), ('8', 'P2'), ('9', '')])
        response = service.press_button(loom, data.field_named(harnesses, 'Build'), admin, data)
        self.assertIsNotNone(response)
        builds = Table.objects.get(app__blueprint='harnesses', key='builds')
        build = Data().records(builds)[0]
        self.assertEqual(Data().label(build), 'SN-00001')
        self.assertEqual(len(Data().linked(build, Data().field_named(builds, 'Checklist'))), 7)
        self.client.force_login(admin)
        page = self.client.get(loom.get_absolute_url()).content.decode()
        self.assertIn('set-row', page)
        self.assertIn('＋ Connector on A', page)


class HarnessSidesTests(TestCase):
    def test_an_installed_harnesses_app_gets_sides_a_and_b(self):
        import json
        from django.apps import apps
        admin = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['parts'], user=admin, sample=True)
        bp = json.loads(json.dumps(blueprints.available()['harnesses']))   # as it was: Source and Target, a Signal
        bp['tables'] = [tb for tb in bp['tables'] if tb['key'] not in ('builds', 'checks')]   # and no builds yet
        bp['automations'] = [a for a in bp.get('automations') or [] if a['key'] != 'build']
        bp['after_records'] = []
        tables = {tb['key']: tb for tb in bp['tables']}
        tables['harnesses']['fields'] = [f for f in tables['harnesses']['fields'] if f['key'] != 'build']
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

