"""Spaces are records of trees; everyone lands in their home space; pages are made of blocks;
access tags decide who sees what; nothing is removed while something uses it."""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from core import access, blueprints, dependencies, schema, service
from core import space as spaces
from core.data import Data
from core.models import AccessGrant, App, Change, Field, Layout, Notification, Record, Table


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.alice = User.objects.create_user('alice', password='pw', first_name='Alice')
        cls.bob = User.objects.create_user('bob', password='pw', first_name='Bob')
        cls.carla = User.objects.create_user('carla', password='pw', first_name='Carla')
        blueprints.install_many(['departments', 'projects', 'stock'], user=cls.admin, sample=True)
        cls.org = Table.objects.get(app__blueprint='departments', key='departments')
        cls.projects = Table.objects.get(app__blueprint='projects', key='projects')
        cls.tasks = Table.objects.get(app__blueprint='tasks', key='tasks')
        for app in App.objects.all():   # everyone may edit records, so access tags are what's tested
            app.default_role = 'editor'
            app.save()

    def node(self, table, label):
        data = Data()
        return next(r for r in data.records(table) if data.label(r) == label)

    def api(self, url, body):
        return self.client.post(url, json.dumps(body), content_type='application/json')


class HomeSpaceTests(Base):
    def test_everyone_lands_in_their_home_space(self):
        self.client.force_login(self.alice)
        response = self.client.get('/')
        self.assertContains(response, 'your home space')
        self.assertContains(response, 'My work')       # the default home page's blocks
        home = spaces.home_node(self.alice)
        self.assertEqual(home.table, self.org)
        self.assertEqual(Data().label(home), 'Alice Martin')   # the sample record naming her
        self.assertEqual(Tree_parent_label(home), 'Engineering')

    def test_a_home_space_is_made_for_someone_new(self):
        dan = get_user_model().objects.create_user('dan', password='pw', first_name='Dan')
        self.client.force_login(dan)
        self.assertContains(self.client.get('/'), 'your home space')
        home = spaces.home_node(dan, create=False)
        self.assertIsNotNone(home)
        data = Data()
        self.assertEqual(data.text(home, data.field_named(self.org, 'Kind')), 'Person')
        self.assertEqual(spaces.home_node(dan).pk, home.pk)   # made once

    def test_edit_a_space_page_with_blocks(self):
        self.client.force_login(self.alice)
        home = spaces.home_node(self.alice)
        self.assertEqual(self.client.get(reverse('core:space_edit', args=[home.pk])).status_code, 200)
        body = ('<h2>Mine</h2><div class="grid-block" data-cols="2"><div class="grid-cell">'
                '<div class="live-block" data-block="notifications">🔔</div></div>'
                '<div class="grid-cell"><a class="app-card" data-app="tasks" href="/a/tasks/">Tasks</a></div></div>'
                '<script>alert(1)</script>')
        self.client.post(reverse('core:space_edit', args=[home.pk]), {'body': body})
        layout = Layout.objects.get(record=home)
        self.assertNotIn('script', layout.body)
        self.assertIn('data-cols="2"', layout.body)
        response = self.client.get('/')
        self.assertContains(response, 'Mine')
        self.assertContains(response, 'Notifications')
        self.assertContains(response, 'app-card live')
        self.client.post(reverse('core:space_edit', args=[home.pk]), {'reset': '1'})
        self.assertFalse(Layout.objects.filter(record=home).exists())

    def test_only_its_people_and_editors_change_a_space_page(self):
        team = self.node(self.org, 'Warehouse')
        App.objects.filter(blueprint='departments').update(default_role='viewer')
        self.client.force_login(self.bob)   # Bob's home is under Warehouse, but he isn't named on it
        self.assertEqual(self.client.get(reverse('core:space', args=[team.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:space_edit', args=[team.pk])).status_code, 403)
        home = spaces.home_node(self.bob)
        self.assertEqual(self.client.get(reverse('core:space_edit', args=[home.pk])).status_code, 200)

    def test_app_home_page(self):
        self.client.force_login(self.admin)
        app = App.objects.get(blueprint='projects')
        response = self.client.get(reverse('core:app', args=[app.slug]))
        self.assertContains(response, 'Tables of this app')
        self.assertContains(response, 'app-tabs')
        self.client.post(reverse('core:app_home_edit', args=[app.slug]), {'body': '<p>Our dashboard</p>'})
        self.assertContains(self.client.get(reverse('core:app', args=[app.slug])), 'Our dashboard')

    def test_launcher(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse('core:launcher'))
        self.assertContains(response, 'Projects')
        self.assertContains(response, 'Product development')


def Tree_parent_label(record):
    from core.trees import Tree
    data = Data()
    t = Tree(data, record.table_id)
    return data.label(t.ancestors(record.pk)[-1])


class TreeTests(Base):
    def test_a_space_shows_what_links_to_it_and_under_it(self):
        self.client.force_login(self.alice)
        programme = self.node(self.projects, 'Product development')
        response = self.client.get(reverse('core:space', args=[programme.pk]))
        self.assertContains(response, 'Burn-in test bench')      # a project under it
        self.assertContains(response, 'Build the burn-in rack')  # a task of that project

    def test_no_circles(self):
        programme = self.node(self.projects, 'Product development')
        project = self.node(self.projects, 'Burn-in test bench')
        parent = Field.objects.get(table=self.projects, key='parent')
        with self.assertRaises(ValidationError):
            service.update_record(programme, {parent.pk: [project.pk]}, user=self.admin)
        with self.assertRaises(ValidationError):
            service.update_record(project, {parent.pk: [project.pk]}, user=self.admin)

    def test_make_a_table_a_tree_of_spaces(self):
        locations = Table.objects.get(app__blueprint='stock', key='locations')
        self.assertTrue(locations.tree_field_id)
        self.assertFalse(locations.is_space)
        self.client.force_login(self.admin)
        url = reverse('core:table_settings', args=[locations.app.slug, locations.slug])
        self.client.post(url, {'name': locations.name, 'tree_field': locations.tree_field_id, 'is_space': '1'})
        locations.refresh_from_db()
        self.assertTrue(locations.is_space)
        record = Record.objects.filter(table=locations).first()
        self.assertEqual(self.client.get(reverse('core:space', args=[record.pk])).status_code, 200)


class AccessTagTests(Base):
    def setUp(self):
        self.tag = access.create_tag('Payroll', self.carla)
        self.project = self.node(self.projects, 'Burn-in test bench')
        self.task = self.node(self.tasks, 'Write the test procedure')   # a subtask, with none of its own

    def test_a_tag_hides_a_record_from_who_does_not_hold_it(self):
        access.set_tags(self.task, [self.tag.pk], self.carla)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.task.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(f'/api/records/{self.task.pk}/').status_code, 404)
        view = self.tasks.views.filter(type='grid').first()
        self.assertNotContains(self.client.get(view.get_absolute_url()), 'Write the test procedure')
        self.assertNotContains(self.client.get('/search/?q=test procedure'), 'Write the test procedure')
        # and in counts: the project's task count leaves it out for Bob, not for Carla
        count = Field.objects.get(table=self.projects, key='task_count')
        self.assertEqual(Data(self.bob).value(Data(self.bob).record(self.project.pk), count), 3)
        self.assertEqual(Data(self.carla).value(Data(self.carla).record(self.project.pk), count), 4)

    def test_administrators_are_no_exception(self):
        access.set_tags(self.task, [self.tag.pk], self.carla)
        self.assertIsNone(Data(self.admin).record(self.task.pk))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.task.get_absolute_url()).status_code, 404)

    def test_every_tag_is_needed(self):
        other = access.create_tag('Board', self.carla)
        access.set_tags(self.task, [self.tag.pk, other.pk], self.carla)
        access.grant(self.tag, self.alice, self.carla)
        self.assertIsNone(Data(self.alice).record(self.task.pk))
        access.grant(other, self.alice, self.carla)
        self.assertIsNotNone(Data(self.alice).record(self.task.pk))

    def test_tags_come_down_the_tree_and_along_links_to_spaces(self):
        rack = self.node(self.tasks, 'Build the burn-in rack')
        access.set_tags(rack, [self.tag.pk], self.carla)    # its subtasks carry it too
        self.task.refresh_from_db()
        self.assertEqual(self.task.access, [self.tag.pk])
        access.set_tags(rack, [], self.carla)
        self.task.refresh_from_db()
        self.assertEqual(self.task.access, [])
        programme = self.node(self.projects, 'Product development')
        access.set_tags(programme, [self.tag.pk], self.carla)
        self.project.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.project.access, [self.tag.pk])   # under it in the tree
        self.assertEqual(self.task.access, [self.tag.pk])      # linked to that project
        self.assertIsNone(Data(self.bob).record(self.task.pk))
        # a project moved out from under the programme loses them, and so do its tasks
        parent = Field.objects.get(table=self.projects, key='parent')
        service.update_record(self.project, {parent.pk: []}, user=self.carla)
        self.project.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual((self.project.access, self.task.access), ([], []))

    def test_only_holders_put_tags_on(self):
        with self.assertRaises(ValidationError):
            access.set_tags(self.task, [self.tag.pk], self.bob)
        self.client.force_login(self.bob)
        self.client.post(reverse('core:record_tags', args=[self.task.pk]), {'tags': [self.tag.pk]})
        self.task.refresh_from_db()
        self.assertEqual(self.task.tags, [])

    def test_only_owners_give_a_tag_and_the_others_are_told(self):
        with self.assertRaises(ValidationError):
            access.grant(self.tag, self.bob, self.bob)
        access.add_owner(self.tag, self.alice, self.carla)
        access.grant(self.tag, self.bob, self.alice)
        self.assertTrue(self.tag.members.filter(pk=self.bob.pk).exists())
        self.assertTrue(Notification.objects.filter(user=self.carla, message__contains='gave the access tag').exists())
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('core:tag', args=[self.tag.pk]), {'action': 'grant', 'user': self.bob.pk}).status_code, 403)

    def test_assigning_someone_who_cant_see_it_asks_to_share(self):
        access.set_tags(self.task, [self.tag.pk], self.carla)
        assignee = Field.objects.get(table=self.tasks, key='assignee')
        self.client.force_login(self.carla)
        response = self.api(f'/api/records/{self.task.pk}/', {'values': {assignee.pk: self.bob.pk}})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()['needs_share'])
        self.assertIsNone(Data(self.bob).record(self.task.pk))
        response = self.api(f'/api/records/{self.task.pk}/', {'values': {assignee.pk: self.bob.pk}, 'share': True})
        self.assertEqual(response.status_code, 200, response.content)
        access.forget(self.bob)
        self.assertIsNotNone(Data(self.bob).record(self.task.pk))   # this one record only
        self.assertTrue(AccessGrant.objects.filter(record=self.task, user=self.bob).exists())
        # done: the share ends
        status = Field.objects.get(table=self.tasks, key='status')
        service.update_record(self.task, {status.pk: 'Done'}, user=self.carla)
        self.assertFalse(AccessGrant.objects.filter(record=self.task).exists())
        access.forget(self.bob)
        self.assertIsNone(Data(self.bob).record(self.task.pk))

    def test_hidden_links_stay_when_someone_edits(self):
        access.set_tags(self.task, [self.tag.pk], self.carla)
        tasks_field = Field.objects.get(table=self.projects, key='tasks')
        before = set(Data().all_linked_ids(self.project, tasks_field))
        data = Data(self.bob)
        visible = data.linked_ids(data.record(self.project.pk), tasks_field)
        self.assertNotIn(self.task.pk, visible)
        service.update_record(self.project, {tasks_field.pk: visible[:-1]}, user=self.bob, data=data)
        after = set(Data().all_linked_ids(self.project, tasks_field))
        self.assertIn(self.task.pk, after)
        self.assertEqual(before - after, {visible[-1]})

    def test_history_and_notifications_keep_it_hidden(self):
        access.set_tags(self.task, [self.tag.pk], self.carla)
        title = Field.objects.get(table=self.tasks, key='title')
        service.update_record(self.task, {title.pk: 'Build the secret rack'}, user=self.carla)
        self.assertTrue(Change.objects.filter(record_id=self.task.pk, access=[self.tag.pk]).exists())
        self.client.force_login(self.bob)
        app = self.tasks.app
        self.assertNotContains(self.client.get(reverse('core:app_history', args=[app.slug])), 'secret rack')


class DependencyTests(Base):
    def test_a_field_in_use_cant_be_deleted(self):
        estimate = Field.objects.get(table=self.tasks, key='estimate')   # projects' "Estimated hours" rolls it up
        with self.assertRaises(ValidationError) as caught:
            schema.delete_field(estimate)
        self.assertIn('Estimated hours', ' '.join(caught.exception.messages))
        self.assertTrue(Field.objects.filter(pk=estimate.pk).exists())

    def test_a_field_nothing_uses_can(self):
        f = schema.add_field(self.tasks, 'Scratch', 'text')
        schema.delete_field(f)
        self.assertFalse(Field.objects.filter(pk=f.pk).exists())

    def test_a_table_others_link_to_cant_be_deleted(self):
        with self.assertRaises(ValidationError):
            schema.delete_table(self.tasks)   # projects link to it
        self.assertTrue(Table.objects.filter(pk=self.tasks.pk).exists())

    def test_an_app_others_need_cant_be_deleted(self):
        parts = App.objects.get(blueprint='parts')
        found = dependencies.blockers(dependencies.app_removal(parts))
        self.assertTrue(any('Stock' in b for b in found), found)

    def test_removing_an_app_leaves_its_plain_fields_behind(self):
        stock = App.objects.get(blueprint='stock')
        parts = Table.objects.get(app__blueprint='parts', key='parts')
        self.assertTrue(Field.objects.filter(table=parts, key='reorder_level', origin='stock').exists())
        # nothing else of the workspace uses Stock here, except what came with it
        found = dependencies.blockers(dependencies.app_removal(stock))
        self.assertEqual(found, [], found)
        schema.delete_app(stock)
        self.assertFalse(App.objects.filter(pk=stock.pk).exists())
        kept = Field.objects.get(table=parts, key='reorder_level')
        self.assertEqual(kept.origin, '')                                            # now Parts' own
        self.assertFalse(Field.objects.filter(table=parts, key='on_hand').exists())  # a rollup of stock: gone
        self.assertTrue(Record.objects.filter(table=parts).exists())

    def test_a_view_on_a_page_cant_be_deleted(self):
        view = self.tasks.views.filter(type='grid').first()
        home = spaces.home_node(self.alice)
        Layout.objects.create(record=home, body=f'<div class="embed-view" data-view="{view.pk}">x</div>')
        with self.assertRaises(ValidationError) as caught:
            schema.delete_view(view)
        self.assertIn('Alice Martin', ' '.join(caught.exception.messages))

    def test_the_settings_page_says_what_is_in_the_way(self):
        self.client.force_login(self.admin)
        app = App.objects.get(blueprint='parts')
        response = self.client.get(reverse('core:app_settings', args=[app.slug]))
        self.assertContains(response, "can't be deleted while something uses it")
        self.client.post(reverse('core:app_settings', args=[app.slug]), {'delete': '1', 'confirm': app.name})
        self.assertTrue(App.objects.filter(pk=app.pk).exists())


class InstallTests(Base):
    def test_installing_lists_what_comes_with_it(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('core:templates'), {'templates': ['orders'], 'sample': '1'})
        self.assertContains(response, 'Vendors')            # orders needs vendors, which isn't there
        self.assertFalse(App.objects.filter(blueprint='orders').exists())
        self.client.post(reverse('core:templates'), {'templates': ['orders'], 'confirmed': '1'})
        self.assertTrue(App.objects.filter(blueprint='orders').exists())
        self.assertTrue(App.objects.filter(blueprint='vendors').exists())

    def test_switching_an_extension_on_and_off(self):
        from core.extensions import all_extensions, in_use, missing, to_install
        harness = next(e for e in all_extensions() if e.name == 'harness')
        self.assertIn('devices', to_install(harness))
        self.assertTrue(any(req == 'devices' for req, _, _ in missing(harness)))
        with tempfile.TemporaryDirectory() as d, override_settings(EXTENSIONS_STATE=Path(d) / 'extensions.json'):
            self.client.force_login(self.admin)
            # "on" for this test run already: switching it off is refused while its view type is used
            blueprints.install_many(['devices', 'harness'], user=self.admin)
            self.assertTrue(in_use('harness'))
            self.client.post(reverse('core:extension_switch', args=['harness']))
            self.assertFalse((Path(d) / 'extensions.json').exists())
            # its apps can't be removed while it's on
            devices = App.objects.get(blueprint='devices')
            self.assertTrue(any('Harness designer' in b for b in dependencies.blockers(dependencies.app_removal(devices))))
