"""Spaces, personal spaces and the home page."""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core import blueprints, service, space as spaces
from core.models import App, RecentView, Record, Space, SpaceApp, SpaceLink, SpaceMember, Star, Table


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.ann = User.objects.create_user('ann', password='pw', first_name='Ann')
        cls.ben = User.objects.create_user('ben', password='pw', first_name='Ben')
        blueprints.install_many(['tasks'], user=cls.admin, sample=False)
        cls.tasks = Table.objects.get(app__blueprint='tasks', key='tasks')

    def setUp(self):
        self.client.force_login(self.ann)

    def api(self, url, body):
        return self.client.post(url, json.dumps(body), content_type='application/json')


class PersonalSpaceTests(Base):
    def test_the_home_page_makes_my_space(self):
        response = self.client.get('/')
        self.assertContains(response, 'Good ')
        self.assertContains(response, 'Your work')
        space = Space.objects.get(owner=self.ann)
        self.assertTrue(space.is_personal)
        todo_app = space.apps.get(is_space=True)
        self.assertEqual(sorted(todo_app.tables.values_list('key', flat=True)), ['bookmarks', 'todos'])
        self.assertContains(response, 'Read the tutorials')
        self.client.get('/')
        self.assertEqual(Space.objects.filter(owner=self.ann).count(), 1)

    def test_my_to_dos_are_mine_alone(self):
        self.client.get('/')
        todo = Record.objects.filter(table__app=spaces.todo_app(self.ann)).first()
        for other in (self.ben, self.admin):
            self.client.force_login(other)
            self.assertEqual(self.client.get(todo.get_absolute_url()).status_code, 403)
        space = spaces.personal_space(self.ann)  # even when Ann lets everyone look at her space
        space.visibility = 'internal'
        space.save()
        self.assertEqual(self.client.get(todo.get_absolute_url()).status_code, 403)
        self.assertNotIn('personal', blueprints.available())

    def test_add_and_finish_a_todo(self):
        self.client.get('/')
        todos = spaces.todo_app(self.ann).tables.get(key='todos')
        self.assertEqual(self.api(f'/api/tables/{todos.pk}/create/', {'values': {'title': 'Call the supplier'}}).status_code, 200)
        self.assertContains(self.client.get('/'), 'Call the supplier')
        rec = Record.objects.get(table=todos, data__title='Call the supplier')
        self.api(f'/api/records/{rec.pk}/', {'values': {todos.fields.get(key='done').pk: True}})
        self.assertNotContains(self.client.get('/'), 'Call the supplier')

    def test_assigned_recent_and_starred(self):
        mine = service.create_record(self.tasks, {'Title': 'Fix the door', 'Assignee': self.ann.pk, 'Due': '2026-01-05'}, self.admin)
        service.create_record(self.tasks, {'Title': 'Done already', 'Assignee': self.ann.pk, 'Status': 'Done'}, self.admin)
        service.create_record(self.tasks, {'Title': 'Not mine', 'Assignee': self.ben.pk}, self.admin)
        html = self.client.get('/').content.decode()
        pane = html.split('data-pane="assigned"', 1)[1].split('data-pane="recent"', 1)[0]
        self.assertIn('Fix the door', pane)
        self.assertNotIn('Done already', pane)
        self.assertNotIn('Not mine', pane)
        self.client.get(mine.get_absolute_url())
        self.assertTrue(RecentView.objects.filter(user=self.ann, record=mine).exists())
        self.client.post(reverse('core:record_star', args=[mine.pk]))
        self.assertTrue(Star.objects.filter(user=self.ann, record=mine).exists())
        self.client.post(reverse('core:record_star', args=[mine.pk]))
        self.assertFalse(Star.objects.exists())

    def test_choose_what_the_home_page_shows(self):
        self.client.get('/')
        space = spaces.personal_space(self.ann)
        self.client.post(reverse('core:space_settings', args=[space.key]),
                         {'action': 'save', 'name': 'Ann', 'visibility': 'private', 'home': ['todos', 'work']})
        space.refresh_from_db()
        self.assertEqual(space.config['home'], ['todos', 'work'])
        response = self.client.get('/')
        self.assertContains(response, 'My to-dos')
        self.assertNotContains(response, 'Other apps')

    def test_launcher_lists_spaces(self):
        response = self.client.get('/')
        self.assertContains(response, 'Spaces</div>')
        self.assertContains(response, 'My space</span>')


class SpaceTests(Base):
    def test_making_spaces_needs_permission(self):
        self.assertEqual(self.client.get(reverse('core:space_create')).status_code, 403)
        self.ann.user_permissions.add(Permission.objects.get(codename='add_space'))
        self.client.force_login(get_user_model().objects.get(pk=self.ann.pk))
        response = self.client.post(reverse('core:space_create'), {'name': 'Engineering', 'kind': 'department',
                                                                   'visibility': 'private', 'description': 'We build things.'})
        space = Space.objects.get(name='Engineering')
        self.assertEqual(space.key, 'ENG')
        self.assertRedirects(response, space.get_absolute_url())
        self.assertTrue(SpaceMember.objects.filter(space=space, user=self.ann, role='admin').exists())
        self.assertContains(self.client.get(space.get_absolute_url()), 'We build things.')

    def test_members_build_apps_and_private_spaces_hide_them(self):
        space = spaces.create_space('Lab', self.ann, visibility='private')
        response = self.client.post(reverse('core:app_create') + f'?space={space.key}',
                                    {'name': 'Experiments', 'table': 'Runs', 'space': space.key})
        app = App.objects.get(name='Experiments')
        self.assertEqual(app.space, space)
        self.assertEqual(response.status_code, 302)
        runs = app.tables.get()
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(space.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.get(runs.get_absolute_url()).status_code, 403)
        SpaceMember.objects.create(space=space, user=self.ben, role='editor')
        self.client.force_login(get_user_model().objects.get(pk=self.ben.pk))
        self.assertEqual(self.client.get(runs.get_absolute_url()).status_code, 302)
        self.assertEqual(self.api(f'/api/tables/{runs.pk}/create/', {'values': {'Name': 'Run 1'}}).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:fields', args=[app.slug, runs.slug])).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:space_settings', args=[space.key])).status_code, 403)

    def test_internal_spaces_can_be_looked_at(self):
        space = spaces.create_space('Ops', self.admin, visibility='internal')
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(space.get_absolute_url()).status_code, 200)

    def test_shortcuts_and_links(self):
        space = spaces.create_space('Projects', self.ann)
        SpaceApp.objects.create(space=space, app=self.tasks.app)
        task = service.create_record(self.tasks, {'Title': 'Kick-off'}, self.admin)
        self.client.post(reverse('core:space_settings', args=[space.key]), {'action': 'add_link', 'label': 'Main task', 'record': task.pk})
        self.assertTrue(SpaceLink.objects.filter(space=space, label='Main task').exists())
        response = self.client.get(space.get_absolute_url())
        self.assertContains(response, 'from Company')  # the shortcut
        self.assertContains(response, 'Kick-off')       # the link
        self.assertContains(self.client.get(self.tasks.views.first().get_absolute_url()), 'Company')

    def test_delete_a_space_moves_its_apps(self):
        space = spaces.create_space('Temp', self.ann)
        self.client.post(reverse('core:app_create') + f'?space={space.key}', {'name': 'Scratch', 'space': space.key})
        self.client.post(reverse('core:space_settings', args=[space.key]), {'action': 'delete', 'confirm': 'Temp', 'apps': 'move'})
        self.assertFalse(Space.objects.filter(name='Temp').exists())
        self.assertEqual(App.objects.get(name='Scratch').space.kind, 'company')
