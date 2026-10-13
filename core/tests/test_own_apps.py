"""People make apps of their own; other apps they may only read until an administrator allows more."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import blueprints, schema, service
from core.data import Data
from core.models import App, AppAccess, Automation, AutomationRun, Record, Table


class OwnAppTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.ann = User.objects.create_user('ann', password='pw', first_name='Ann')
        cls.ben = User.objects.create_user('ben', password='pw', first_name='Ben')
        blueprints.install_many(['vendors'], user=cls.admin, sample=True)
        cls.vendors = Table.objects.get(app__blueprint='vendors', key='vendors')

    def setUp(self):
        self.client.force_login(self.ann)

    def api(self, url, body):
        return self.client.post(url, json.dumps(body), content_type='application/json')

    def make_app(self):
        response = self.client.post(reverse('core:app_create'), {'name': 'My books', 'table': 'Books'})
        app = App.objects.get(name='My books')
        self.assertEqual(response.status_code, 302)
        return app, app.tables.get()

    def test_home_page_has_my_apps(self):
        response = self.client.get('/')
        self.assertContains(response, 'My apps')
        self.assertContains(response, 'read only')  # the vendors app

    def test_a_person_makes_and_builds_an_app_of_their_own(self):
        app, books = self.make_app()
        self.assertEqual(app.owner, self.ann)
        self.assertEqual(app.default_role, 'none')
        self.client.post(reverse('core:field_create', args=[app.slug, books.slug]), {'name': 'Pages', 'type': 'number'})
        self.assertTrue(books.fields.filter(name='Pages').exists())
        response = self.api(f'/api/tables/{books.pk}/create/', {'values': {'Name': 'Dune', 'Pages': 412}})
        self.assertEqual(response.status_code, 200)
        self.client.get(reverse('core:automation_create', args=[app.slug]))
        self.assertEqual(self.client.get(reverse('core:app_settings', args=[app.slug])).status_code, 200)
        # others don't see it, until Ann lets them look
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(app.get_absolute_url()).status_code, 403)
        self.client.force_login(self.ann)
        self.client.post(reverse('core:app_settings', args=[app.slug]), {'name': 'My books', 'default_role': 'viewer'})
        app.refresh_from_db()
        self.assertEqual(app.default_role, 'viewer')
        # ... but she can't let them change it
        self.client.post(reverse('core:app_settings', args=[app.slug]), {'name': 'My books', 'default_role': 'editor'})
        app.refresh_from_db()
        self.assertEqual(app.default_role, 'viewer')
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(books.views.first().get_absolute_url()).status_code, 200)
        dune = Record.objects.get(table=books)
        self.assertEqual(self.api(f'/api/records/{dune.pk}/', {'values': {'Pages': 1}}).status_code, 403)

    def test_other_apps_are_read_only(self):
        self.assertEqual(self.client.get(self.vendors.views.first().get_absolute_url()).status_code, 200)
        acme = Record.objects.filter(table=self.vendors).first()
        self.assertEqual(self.api(f'/api/records/{acme.pk}/', {'values': {'City': 'X'}}).status_code, 403)
        self.assertEqual(self.api(f'/api/tables/{self.vendors.pk}/create/', {'values': {'Name': 'X'}}).status_code, 403)
        self.assertEqual(self.client.post(reverse('core:record_comment', args=[acme.pk]), {'text': 'hi'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:fields', args=[self.vendors.app.slug, self.vendors.slug])).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:record_new', args=[self.vendors.app.slug, self.vendors.slug])).status_code, 403)

    def test_an_administrator_allows_writing(self):
        acme = Record.objects.filter(table=self.vendors).first()
        AppAccess.objects.create(app=self.vendors.app, user=self.ann, role='editor')
        self.assertEqual(self.api(f'/api/records/{acme.pk}/', {'values': {'City': 'Delft'}}).status_code, 200)

    def test_no_links_into_apps_she_cant_build(self):
        app, books = self.make_app()
        response = self.client.post(reverse('core:field_create', args=[app.slug, books.slug]),
                                    {'name': 'Seller', 'type': 'link', 'target': self.vendors.pk})
        self.assertContains(response, 'can&#x27;t change')
        self.assertFalse(self.vendors.fields.filter(name='Books').exists())

    def test_automations_cant_write_to_other_apps(self):
        app, books = self.make_app()
        spec = {'table': books.pk, 'name': 'Sneaky', 'trigger': 'record_created', 'conditions': {}, 'active': True,
                'actions': [{'type': 'create_record', 'table': self.vendors.pk, 'values': {'name': 'Hacked'}}]}
        response = self.client.post(reverse('core:automation_create', args=[app.slug]), {'spec': json.dumps(spec)})
        self.assertContains(response, 'you can only look at Vendors')
        self.assertFalse(Automation.objects.filter(name='Sneaky').exists())
        # and if one is there anyway (e.g. access was taken away later), it can't write when it runs
        Automation.objects.create(table=books, name='Sneaky', trigger='record_created', actions=spec['actions'])
        service.create_record(books, {'Name': 'Dune'}, self.ann)
        self.assertFalse(Record.objects.filter(table=self.vendors, data__name='Hacked').exists())
        self.assertEqual(AutomationRun.objects.get(automation__name='Sneaky').status, 'failed')

    def test_owner_can_delete_their_app(self):
        app, books = self.make_app()
        self.client.post(reverse('core:app_settings', args=[app.slug]), {'delete': '1', 'confirm': 'My books'})
        self.assertFalse(App.objects.filter(pk=app.pk).exists())

    def test_cant_delete_a_link_pair_in_a_workspace_app(self):
        app, books = self.make_app()
        link = schema.add_field(self.vendors, 'Books', 'link', {'target': books.pk, 'multiple': True}, inverse_name='Vendor')
        pair = books.fields.get(name='Vendor')
        self.client.post(reverse('core:field_edit', args=[app.slug, books.slug, pair.pk]), {'delete': '1'})
        self.assertTrue(self.vendors.fields.filter(pk=link.pk).exists())
