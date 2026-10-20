"""Every page of every app made from the templates opens, and the API changes records."""
import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core import blueprints
from core.data import Data
from core.models import App, AppAccess, Automation, Field, Record, Table, View


class Workspace(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        for name in ['alice', 'bob', 'carla']:
            User.objects.create_user(name, password='demo', first_name=name.title())
        blueprints.install_many(list(blueprints.available()), user=cls.admin, sample=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def ok(self, url, status=200):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, f'{url} answered {response.status_code}')
        return response

    def table(self, app_key, table_key):
        return Table.objects.get(app__blueprint=app_key, key=table_key)

    def record(self, table, label):
        data = Data()
        return next(r for r in data.records(table) if data.label(r) == label)


class PageTests(Workspace):
    def test_home_and_admin_pages(self):
        for url in ['/', '/search/?q=dsub', '/notifications/', reverse('core:templates'), reverse('core:extensions'),
                    reverse('core:app_create'), reverse('accounts:user_list'), reverse('accounts:team_list'),
                    reverse('accounts:team_create'), reverse('accounts:user_create'), reverse('accounts:profile'),
                    reverse('accounts:password_change'), reverse('core:launcher'), reverse('core:trees'),
                    reverse('core:tags'), reverse('core:space_edit', args=[Record.objects.filter(table__is_space=True).first().pk])]:
            self.ok(url)
        for ext in ['docs', 'assistant', 'tutorials']:
            self.ok(reverse('core:extension_switch', args=[ext]))

    def test_every_space_and_app_home(self):
        self.assertContains(self.ok('/'), 'your own page')
        for record in Record.objects.filter(table__is_space=True):
            response = self.ok(reverse('core:space', args=[record.pk]))
            self.assertNotContains(response, 'could not be shown', msg_prefix=str(record.pk))
        for app in App.objects.all():
            self.ok(reverse('core:app', args=[app.slug]))
            self.ok(reverse('core:app_home_edit', args=[app.slug]))

    def test_every_view_of_every_table(self):
        for view in View.objects.select_related('table__app'):
            response = self.ok(view.get_absolute_url())
            self.assertNotContains(response, '#ERROR', msg_prefix=view.get_absolute_url())
            self.ok(reverse('core:view_settings', args=[view.table.app.slug, view.table.slug, view.pk]))

    def test_view_toolbar_options(self):
        view = View.objects.filter(type='grid', table__key='tasks').first()
        url = view.get_absolute_url()
        filters = json.dumps({'match': 'all', 'rules': [{'field': 'status', 'op': 'is', 'value': 'Done'}]})
        response = self.ok(f'{url}?filters={filters}&sorts={json.dumps([{"field": "title", "dir": "desc"}])}&group_by=status&q=wire')
        self.assertContains(response, 'Wire the power distribution')
        self.assertNotContains(response, 'Label the new bins')
        gantt = View.objects.filter(type='gantt').first()
        for zoom in ['day', 'week', 'month']:
            self.ok(f'{gantt.get_absolute_url()}?zoom={zoom}')
        calendar = View.objects.filter(type='calendar').first()
        self.ok(f'{calendar.get_absolute_url()}?month=2026-02')

    def test_every_record_page(self):
        for record in Record.objects.select_related('table__app'):
            response = self.ok(record.get_absolute_url())
            self.assertNotContains(response, '#ERROR', msg_prefix=record.get_absolute_url())

    def test_builder_pages(self):
        for app in App.objects.all():
            for name in ['app_settings', 'automations', 'automation_runs', 'app_history', 'table_create', 'automation_create']:
                self.ok(reverse(f'core:{name}', args=[app.slug]))
            for table in app.tables.all():
                for name in ['fields', 'field_create', 'table_settings', 'record_new', 'table_import', 'table_csv']:
                    self.ok(reverse(f'core:{name}', args=[app.slug, table.slug]))
                for field in table.fields.all():
                    self.ok(reverse('core:field_edit', args=[app.slug, table.slug, field.pk]))
        for auto in Automation.objects.select_related('table__app'):
            self.ok(reverse('core:automation_edit', args=[auto.table.app.slug, auto.pk]))
        self.ok(reverse('core:template_export', args=[App.objects.first().slug]) + '?records=1')


class ApiTests(Workspace):
    def post(self, url, body):
        return self.client.post(url, json.dumps(body), content_type='application/json')

    def test_edit_a_cell(self):
        tasks = self.table('tasks', 'tasks')
        task = self.record(tasks, 'Label the new bins')
        status = Field.objects.get(table=tasks, key='status')
        response = self.post(f'/api/records/{task.pk}/', {'values': {status.pk: 'In progress'}})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('In progress', response.json()['cells'][str(status.pk)]['html'])
        bad = self.post(f'/api/records/{task.pk}/', {'values': {status.pk: 'Nope'}})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('not one of the choices', bad.json()['error'])

    def test_place_and_receive_an_order_with_buttons(self):
        orders = self.table('orders', 'orders')
        order = self.record(orders, 'PO-0003')
        place = Field.objects.get(table=orders, key='place')
        receive = Field.objects.get(table=orders, key='receive_all')
        response = self.post(f'/api/records/{order.pk}/button/{place.pk}/', {})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['ok'], response.json())
        response = self.post(f'/api/records/{order.pk}/button/{receive.pk}/', {})
        self.assertTrue(response.json()['ok'], response.json())
        data = Data()
        rec = data.record(order.pk)
        self.assertEqual(data.text(rec, data.field_named(orders, 'Status')), 'Received')
        part = self.record(self.table('parts', 'parts'), 'RES-10K-0603')
        self.assertEqual(data.text(data.record(part.pk), data.field_named(part.table_id, 'On hand')), '6000')

    def test_blocked_issue_is_refused(self):
        moves = self.table('stock', 'moves')
        part = self.record(self.table('parts', 'parts'), 'DSUB-9-PLUG')
        response = self.post(f'/api/tables/{moves.pk}/create/', {'values': {'type': 'Issue', 'part': [part.pk], 'quantity': 5000}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("isn't enough", response.json()['error'])

    def test_lines_of_placed_orders_are_locked(self):
        lines = self.table('orders', 'lines')
        line = next(r for r in Data().records(lines) if 'PO-0001' in Data().label(r))
        response = self.post(f'/api/records/{line.pk}/', {'values': {'quantity': 99}})
        self.assertEqual(response.status_code, 400)

    def test_move_stock(self):
        levels = self.table('stock', 'levels')
        locations = self.table('stock', 'locations')
        level = self.record(levels, 'DSUB-9-PLUG @ WA2')
        lab = self.record(locations, 'Test lab')
        response = self.post(f'/api/records/{level.pk}/', {'values': {'move_to': [lab.pk]}})
        self.assertEqual(response.status_code, 200, response.content)
        labels = [Data().label(r) for r in Data().records(levels)]
        self.assertIn('DSUB-9-PLUG @ T', labels)

    def test_link_picker_and_links(self):
        parts = self.table('parts', 'parts')
        response = self.ok(f'/api/tables/{parts.pk}/records/?q=dsub')
        self.assertEqual(len(response.json()['records']), 3)
        plug = self.record(parts, 'DSUB-9-PLUG')
        accepts = Field.objects.get(table=parts, key='accepts')
        wire = self.record(parts, 'WIRE-22-RED')
        response = self.post(f'/api/records/{plug.pk}/link/{accepts.pk}/', {'add': wire.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn('WIRE-22-RED', response.json()['cells'][str(accepts.pk)]['html'])

    def test_save_view_config(self):
        view = View.objects.filter(type='grid').first()
        response = self.post(f'/api/views/{view.pk}/config/', {'widths': {'title': 300}, 'sorts': [{'field': 'x', 'dir': 'asc'}]})
        self.assertEqual(response.status_code, 200)
        view.refresh_from_db()
        self.assertEqual(view.config['widths'], {'title': 300})


class FormTests(Workspace):
    def test_new_record_form_with_link_and_file(self):
        tasks = self.table('tasks', 'tasks')
        title = Field.objects.get(table=tasks, key='title')
        status = Field.objects.get(table=tasks, key='status')
        group = Field.objects.get(table=tasks, key='group')
        files = Field.objects.get(table=tasks, key='files')
        inventory = self.record(self.table('tasks', 'groups'), 'Inventory')
        url = reverse('core:record_new', args=[tasks.app.slug, tasks.slug])
        response = self.client.post(url, {f'f_{title.pk}': 'Check the forklift', f'f_{status.pk}': 'To do',
                                          f'f_{group.pk}': [inventory.pk],
                                          f'f_{files.pk}': SimpleUploadedFile('notes.txt', b'hello', 'text/plain')})
        self.assertEqual(response.status_code, 302, response.content[:2000])
        record = self.record(tasks, 'Check the forklift')
        self.assertEqual(record.attachments.count(), 1)
        self.ok(f'/files/{record.attachments.first().pk}/')

    def test_required_field_errors(self):
        tasks = self.table('tasks', 'tasks')
        response = self.client.post(reverse('core:record_new', args=[tasks.app.slug, tasks.slug]), {})
        self.assertContains(response, 'Fill in Title')

    def test_form_view(self):
        view = View.objects.get(table__key='tasks', type='form')
        title = Field.objects.get(table=view.table, key='title')
        response = self.client.post(view.get_absolute_url(), {f'f_{title.pk}': 'From the form'})
        self.assertEqual(response.status_code, 302)
        self.record(view.table, 'From the form')

    def test_make_an_app_table_field_view_and_automation(self):
        response = self.client.post(reverse('core:app_create'), {'name': 'Maintenance', 'icon': '🔧', 'table': 'Machines'})
        app = App.objects.get(name='Maintenance')
        table = app.tables.get()
        self.assertRedirects(response, reverse('core:fields', args=[app.slug, table.slug]))
        url = reverse('core:field_create', args=[app.slug, table.slug])
        self.client.post(url, {'name': 'State', 'type': 'select', 'choice_value': ['Running', 'Broken'], 'choice_color': ['#bbf7d0', '#fecaca']})
        self.client.post(url, {'name': 'Next service', 'type': 'date'})
        self.client.post(url, {'name': 'Hours', 'type': 'number', 'decimals': '1'})
        self.client.post(url, {'name': 'Hours left', 'type': 'formula', 'expression': '500 - {Hours}', 'format': 'number'})
        parts = self.table('parts', 'parts')
        self.client.post(url, {'name': 'Spare parts', 'type': 'link', 'target': parts.pk, 'multiple': '1', 'inverse_name': 'Machines', 'inverse_multiple': '1'})
        self.assertEqual(table.fields.count(), 6)
        self.assertTrue(parts.fields.filter(name='Machines').exists())
        bad = self.client.post(url, {'name': 'Broken formula', 'type': 'formula', 'expression': '1 +'})
        self.assertContains(bad, 'mistake')
        for vtype in ['kanban', 'calendar', 'gantt', 'gallery', 'form', 'detail']:
            self.client.post(reverse('core:view_create', args=[app.slug, table.slug]), {'type': vtype})
        for view in table.views.all():
            self.ok(view.get_absolute_url())
        state = table.fields.get(name='State')
        spec = {'table': table.pk, 'name': 'Tell when broken', 'active': True, 'trigger': 'record_updated',
                'trigger_config': {'fields': [state.key]},
                'conditions': {'match': 'all', 'rules': [{'field': state.key, 'op': 'changed_to', 'value': 'Broken'}]},
                'actions': [{'type': 'notify', 'users': [str(self.admin.pk)], 'message': '{Name} is broken'}]}
        response = self.client.post(reverse('core:automation_create', args=[app.slug]), {'spec': json.dumps(spec)})
        self.assertEqual(response.status_code, 302)
        data = Data(self.admin)
        from core import service
        machine = service.create_record(table, {'Name': 'Lathe', 'State': 'Running', 'Hours': '120'}, self.admin)
        service.update_record(machine, {'State': 'Broken'}, self.admin)
        self.assertTrue(self.admin.notifications.filter(message='Lathe is broken').exists())
        self.assertEqual(data.text(data.record(machine.pk), table.fields.get(name='Hours left')), '380')

    def test_csv_import_and_export(self):
        vendors = self.table('vendors', 'vendors')
        csv_file = SimpleUploadedFile('v.csv', 'Name,City,Rating\nNew Vendor,Paris,3\n,,\nOther,Lyon,9\n'.encode(), 'text/csv')
        response = self.client.post(reverse('core:table_import', args=[vendors.app.slug, vendors.slug]), {'file': csv_file})
        self.assertContains(response, '<b>2</b> records added')
        response = self.ok(reverse('core:table_csv', args=[vendors.app.slug, vendors.slug]))
        self.assertIn('New Vendor', response.content.decode('utf-8'))


class AccessTests(Workspace):
    def test_viewer_can_look_but_not_change(self):
        alice = get_user_model().objects.get(username='alice')
        app = App.objects.get(blueprint='orders')
        AppAccess.objects.create(app=app, user=alice, role='viewer')
        self.client.force_login(alice)
        orders = self.table('orders', 'orders')
        self.ok(orders.get_absolute_url(), 302)
        self.ok(orders.views.first().get_absolute_url())
        self.ok(reverse('core:record_new', args=[app.slug, orders.slug]), 403)
        self.ok(reverse('core:fields', args=[app.slug, orders.slug]), 403)
        order = self.record(orders, 'PO-0003')
        response = self.client.post(f'/api/records/{order.pk}/', json.dumps({'values': {'notes': 'x'}}), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.ok(reverse('core:templates'), 302)

    def test_no_access_hides_the_app(self):
        bob = get_user_model().objects.get(username='bob')
        app = App.objects.get(blueprint='budgets')
        app.default_role = 'none'
        app.save()
        self.client.force_login(bob)
        response = self.ok('/')
        self.assertNotContains(response, 'Budgets</span>')
        self.ok(app.get_absolute_url(), 403)


class SetupTests(TestCase):
    def test_first_run_goes_to_setup_and_makes_the_admin(self):
        from core import middleware
        middleware._ready = False
        response = self.client.get('/')
        self.assertRedirects(response, '/setup/')
        response = self.client.post('/setup/', {'username': 'boss', 'password1': 'short', 'password2': 'short'})
        self.assertContains(response, 'too short')
        response = self.client.post('/setup/', {'username': 'boss', 'password1': 'a-Long-pass-123', 'password2': 'a-Long-pass-123',
                                                'templates': ['tasks'], 'sample': '1', 'demo_users': '1'})
        self.assertRedirects(response, '/')
        self.assertTrue(get_user_model().objects.get(username='boss').is_superuser)
        self.assertTrue(App.objects.filter(blueprint='tasks').exists())


class CardTests(Workspace):
    def test_cards_have_no_links_inside(self):
        """A card is a link; a link inside it would break the card apart."""
        import re
        for view in View.objects.filter(type__in=['kanban', 'gallery']):
            html = self.ok(view.get_absolute_url()).content.decode()
            for card in re.findall(r'<a class="(?:kcard|gcard)".*?</a>', html, re.S):
                self.assertNotIn('<a ', card[3:], view.get_absolute_url())

    def test_launcher_lists_apps(self):
        response = self.ok('/')
        self.assertContains(response, 'launcher-tile')
        self.assertContains(response, 'data-name="orders"')


class BackAndForwardTests(Workspace):
    """Back and Forward show pages as they are now and never land in an editing screen."""

    def leave_to(self, url):
        html = self.ok(url).content.decode()
        start = html.index('name="osmia-leave-to" content="') + len('name="osmia-leave-to" content="')
        return html[start:html.index('"', start)]

    def test_pages_are_not_kept_by_the_browser(self):
        response = self.ok('/')
        self.assertIn('no-store', response['Cache-Control'])

    def test_editing_screens_name_the_page_they_belong_to(self):
        tasks = self.table('tasks', 'tasks')
        app, view, field = tasks.app, tasks.views.first(), tasks.fields.first()
        self.assertEqual(self.leave_to(reverse('core:app_settings', args=[app.slug])), app.get_absolute_url())
        self.assertEqual(self.leave_to(reverse('core:field_edit', args=[app.slug, tasks.slug, field.pk])),
                         reverse('core:fields', args=[app.slug, tasks.slug]))
        self.assertEqual(self.leave_to(reverse('core:view_settings', args=[app.slug, tasks.slug, view.pk])), view.get_absolute_url())
        self.assertEqual(self.leave_to(reverse('core:app_home_edit', args=[app.slug])), reverse('core:app', args=[app.slug]))
        self.assertEqual(self.leave_to(reverse('core:record_new', args=[app.slug, tasks.slug])), tasks.get_absolute_url())
        self.assertEqual(self.leave_to(reverse('accounts:profile')), '/')
        # what is only looked at stays where it is
        self.assertEqual(self.leave_to(app.get_absolute_url()), '')
        self.assertEqual(self.leave_to(view.get_absolute_url()), '')

    def test_only_a_page_of_this_osmia_comes_next(self):
        tasks = self.table('tasks', 'tasks')
        url = reverse('core:record_new', args=[tasks.app.slug, tasks.slug])
        for outside in ['//evil.example/', 'https://evil.example/', 'javascript:alert(1)']:
            self.assertEqual(self.leave_to(f'{url}?next={outside}'), tasks.get_absolute_url(), outside)
        self.assertEqual(self.leave_to(f'{url}?next=/notifications/'), '/notifications/')
