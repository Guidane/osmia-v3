import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import blueprints
from core.data import Data
from core.models import Record, Table, View

from .drawing import Apps
from .models import DrawingVersion


class HarnessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        User.objects.create_user('alice', password='demo', first_name='Alice')
        blueprints.install_many(list(blueprints.available()), user=cls.admin, sample=True)

    def setUp(self):
        self.client.force_login(self.admin)
        self.base = reverse('harness:api_devices').removesuffix('/devices')

    def post(self, path, body):
        return self.client.post(self.base + path, json.dumps(body), content_type='application/json')

    def device(self, name):
        apps = Apps()
        return next(d for d in apps.data.records(apps.devices) if apps.data.label(d) == name)

    def test_templates_come_with_the_extension(self):
        catalog = blueprints.available()
        self.assertIn('devices', catalog)
        self.assertIn('harness', catalog)
        self.assertTrue(Table.objects.filter(app__blueprint='harness', key='projects').exists())

    def test_designer_page_and_view_tab(self):
        response = self.client.get(reverse('harness:designer'))
        self.assertContains(response, 'id="harness-app"')
        self.assertContains(response, 'harness/designer.js')
        self.assertContains(self.client.get(reverse('harness:designer') + '?embed=1'), 'id="harness-app"')
        view = View.objects.get(type='harness_designer')
        self.assertContains(self.client.get(view.get_absolute_url()), '<iframe')

    def test_devices_in_the_designers_format(self):
        devices = self.client.get(self.base + '/devices').json()
        controller = next(d for d in devices if d['name'] == 'Controller unit')
        self.assertEqual(controller['role'], 'product')
        self.assertEqual(controller['origin'], 'in_house')
        j02 = next(c for c in controller['connectors'] if c['id'] == 'J02')
        self.assertEqual(j02['side'], 'right')
        self.assertEqual(j02['tag_columns'], 2)
        self.assertEqual([p['label'] for p in j02['pins']], ['2', '3', '7'])
        self.assertEqual([p['signal'] for p in j02['pins']], ['CAN_L', 'GND', 'CAN_H'])
        self.assertEqual(j02['pins'][0]['set_type'], 'twisted')
        self.assertEqual(j02['part']['part_number'], 'DSUB-9-RECEPT')
        one = self.client.get(f'{self.base}/devices/{controller["id"]}').json()
        self.assertEqual(one['name'], 'Controller unit')

    def test_save_load_and_version_a_project(self):
        controller = self.device('Controller unit')
        drawing = {'name': 'CAN loop', 'instances': [{'id': 'i1', 'device_id': str(controller.pk), 'x': 10, 'y': 20}],
                   'harnesses': [{'id': 'h1', 'branches': [{'connections': [{'verified': True}, {'verified': False}]}]}]}
        saved = self.post('/projects', drawing).json()
        self.assertEqual(saved['version'], 1)
        record = Record.objects.get(pk=saved['id'])
        apps = Apps()
        self.assertEqual(apps.text(record, 'wire_count'), '2')
        self.assertEqual(apps.text(record, 'verified'), '1')
        saved2 = self.post('/projects', {**saved, 'name': 'CAN loop v2', 'harnesses': []}).json()
        self.assertEqual(saved2['version'], 2)
        self.assertEqual(self.client.get(f'{self.base}/projects/{saved["id"]}/versions').json()['versions'], [1, 2])
        old = self.client.get(f'{self.base}/projects/{saved["id"]}?version=1').json()
        self.assertEqual(len(old['harnesses']), 1)
        back = self.client.post(f'{self.base}/projects/{saved["id"]}/versions/1/activate').json()
        self.assertEqual(back['version'], 1)
        self.assertEqual(back['name'], 'CAN loop')
        self.assertEqual(len(self.client.get(self.base + '/projects').json()), 1)
        page = self.client.get(controller.get_absolute_url())
        self.assertContains(page, 'Used in harness projects')
        self.assertContains(page, 'CAN loop')
        self.assertContains(self.client.get(record.get_absolute_url()), 'Open in the designer')
        response = self.client.delete(f'{self.base}/projects/{saved["id"]}')
        self.assertEqual(response.json(), {'deleted': True})
        self.assertFalse(DrawingVersion.objects.exists())

    def test_signal_rules(self):
        pairs = self.client.get(self.base + '/signal-rules').json()['pairs']
        self.assertIn(['GND', 'GND'], pairs)
        response = self.post('/signal-rules', {'pairs': [['PWR', 'PWR'], ['NEWSIG', 'NEWSIG'], ['pwr', 'PWR']]})
        self.assertEqual(response.json()['pairs'], [['PWR', 'PWR'], ['NEWSIG', 'NEWSIG']])
        apps = Apps()
        self.assertTrue(any(apps.data.label(s) == 'NEWSIG' for s in apps.data.records(apps.signals)))

    def test_extension_device(self):
        controller = self.device('Controller unit')
        ext = self.post('/extensions', {'device_id': controller.pk, 'connector_id': 'J02'}).json()
        self.assertEqual(ext['role'], 'interconnect')
        self.assertEqual([c['id'] for c in ext['connectors']], ['J01', 'J02'])
        self.assertEqual([p['signal'] for p in ext['connectors'][1]['pins']], ['CAN_L', 'GND', 'CAN_H'])
        self.assertEqual(len(ext['pin_map']), 3)
        self.assertEqual(ext['pin_map'][0][0], 'J01')
        missing = self.post('/extensions', {'device_id': controller.pk, 'connector_id': 'J99'})
        self.assertEqual(missing.status_code, 404)

    def test_parts_and_draft_order(self):
        parts = self.client.get(self.base + '/parts').json()['parts']
        self.assertIn('DSUB-9-PLUG', [p['part_number'] for p in parts])
        result = self.post('/order', {'lines': [{'part_number': 'DSUB-9-PLUG', 'quantity': 2}, {'part_number': 'NOPE', 'quantity': 1}],
                                      'note': 'Plugs for CAN loop'}).json()
        self.assertEqual(result['lines'], 1)
        self.assertEqual(result['missing'], ['NOPE'])
        self.assertTrue(result['number'].startswith('PO-'))

    def test_clone_connector_button(self):
        apps = Apps()
        controller = self.device('Controller unit')
        j02 = next(c for c in apps.linked(controller, 'connectors') if apps.text(c, 'designator') == 'J02')
        button = next(f for f in apps.data.fields(apps.connectors) if f.key == 'clone')
        response = self.client.post(f'/api/records/{j02.pk}/button/{button.pk}/', '{}', content_type='application/json')
        self.assertTrue(response.json()['ok'], response.json())
        apps = Apps()
        copy = next(c for c in apps.linked(controller, 'connectors') if apps.text(c, 'designator') == 'J02 copy')
        self.assertEqual(len(apps.linked(copy, 'pins')), 3)

    def test_one_designator_per_device(self):
        apps = Apps()
        controller = self.device('Controller unit')
        response = self.client.post(f'/api/tables/{apps.connectors.pk}/create/',
                                    json.dumps({'values': {'device': [controller.pk], 'designator': 'J01'}}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('already has a connector J01', response.json()['error'])
