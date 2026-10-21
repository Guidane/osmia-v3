import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import access, blueprints, service
from core.data import Data
from core.models import App, AppAccess, Change, Record, Table

from . import plan as plans
from .models import Run
from .prompt import build


def answer(*changes, summary='Test'):
    return 'Sure! Here it is:\n```json\n' + json.dumps({'osmia': 1, 'summary': summary, 'changes': list(changes)}) + '\n```\nAnything else?'


SUPPLIERS = {
    'do': 'create_app', 'own': True, 'name': 'Suppliers', 'icon': '🏭',
    'tables': [
        {'name': 'Suppliers', 'fields': [
            {'name': 'Name', 'type': 'text'},
            {'name': 'Status', 'type': 'select', 'choices': ['Active', 'Paused']},
            {'name': 'Order total', 'type': 'rollup', 'link': 'Orders', 'field': 'Amount', 'func': 'sum'}],
         'views': [{'name': 'Board', 'type': 'kanban', 'group_by': 'Status'}],
         'records': [{'Name': 'Acme', 'Status': 'Active'}, {'Name': 'Globex', 'Status': 'Paused'}]},
        {'name': 'Orders', 'fields': [
            {'name': 'Number', 'type': 'text'},
            {'name': 'Supplier', 'type': 'link', 'target': 'Suppliers', 'multiple': False, 'inverse_name': 'Orders'},
            {'name': 'Amount', 'type': 'currency'}],
         'records': [{'Number': 'PO-1', 'Supplier': 'Acme', 'Amount': 100}, {'Number': 'PO-2', 'Supplier': 'Acme', 'Amount': 50}]},
    ],
}


class ParseTests(TestCase):
    def test_finds_the_json_in_an_answer(self):
        plan = plans.parse(answer({'do': 'add_records', 'app': 'x', 'table': 'y', 'records': []}))
        self.assertEqual(plan['changes'][0]['do'], 'add_records')
        self.assertEqual(plans.parse('{"osmia": 1, "changes": [{"do": "create_page"}]}')['changes'][0]['do'], 'create_page')

    def test_says_what_is_wrong(self):
        for text, says in (('', 'Paste'), ('no json here', 'no JSON'), ('```json\n{"changes": [1,]}\n```', 'mistake'),
                           ('{"osmia": 1}', 'no "changes"'), ('{"changes": [{"do": "delete_app"}]}', '"do" must be one of'),
                           ('{"changes": [' + ','.join(['{"do": "create_page"}'] * 51) + ']}', 'at most 50')):
            with self.assertRaisesMessage(plans.PlanError, says):
                plans.parse(text)

    def test_a_question(self):
        self.assertEqual(plans.parse('{"osmia": 1, "question": "Which space?"}')['question'], 'Which space?')


class PlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.ann = User.objects.create_user('ann', password='pw')
        blueprints.install_many(['departments', 'tasks'], user=cls.admin, sample=True)
        cls.org = Table.objects.get(app__blueprint='departments', key='departments')

    def run_plan(self, *changes, user=None, apply=False):
        return plans.run(plans.parse(answer(*changes)), user or self.ann, apply=apply)

    def test_checking_changes_nothing(self):
        before = (App.objects.count(), Table.objects.count(), Record.objects.count())
        steps = self.run_plan(SUPPLIERS)
        self.assertTrue(all(s.ok for s in steps), [s.error for s in steps])
        self.assertIn('Make the app Suppliers (your own app)', steps[0].text)
        self.assertIn('Suppliers (4 fields, 2 records), Orders (3 fields, 2 records)', steps[0].text)   # + the link's pair
        self.assertEqual((App.objects.count(), Table.objects.count(), Record.objects.count()), before)
        self.assertEqual(steps[0].url, '')

    def test_making_an_app(self):
        steps = self.run_plan(SUPPLIERS, apply=True)
        self.assertTrue(all(s.ok for s in steps), [s.error for s in steps])
        app = App.objects.get(name='Suppliers')
        self.assertEqual(app.owner, self.ann)
        self.assertEqual(app.default_role, 'none')
        suppliers = app.tables.get(name='Suppliers')
        data = Data(self.ann)
        acme = next(r for r in data.records(suppliers) if data.label(r) == 'Acme')
        self.assertEqual(data.text(acme, data.field_named(suppliers, 'Order total')), '150')
        self.assertEqual(suppliers.views.get(name='Board').config, {'group_field': 'status'})
        self.assertTrue(Change.objects.filter(source='AI prompt generator', table=suppliers).exists())   # the history says so

    def test_automations_only_run_when_applying(self):
        with mock.patch('core.automation._automations', return_value=[]) as autos:
            self.run_plan({'do': 'add_records', 'app': 'Tasks', 'table': 'Tasks', 'records': [{'Title': 'From AI'}]}, user=self.admin)
            autos.assert_not_called()
            self.run_plan({'do': 'add_records', 'app': 'Tasks', 'table': 'Tasks', 'records': [{'Title': 'From AI'}]},
                          user=self.admin, apply=True)
            autos.assert_called()

    def test_all_or_nothing(self):
        steps = self.run_plan(SUPPLIERS, {'do': 'add_field', 'app': 'Suppliers', 'table': 'Nope', 'field': {'name': 'X'}}, apply=True)
        self.assertTrue(steps[0].ok)
        self.assertIn('has no table "Nope"', steps[1].error)
        self.assertFalse(App.objects.filter(name='Suppliers').exists())

    def test_later_changes_use_earlier_ones(self):
        steps = self.run_plan(
            SUPPLIERS,
            {'do': 'add_field', 'app': 'Suppliers', 'table': 'Suppliers', 'field': {'name': 'Country', 'type': 'text'}},
            {'do': 'change_field', 'app': 'Suppliers', 'table': 'Suppliers', 'field': 'Status', 'name': 'State',
             'choices': ['Active', 'Paused', 'Blocked']},
            {'do': 'update_records', 'app': 'Suppliers', 'table': 'Suppliers', 'where': {'Name': 'Globex'},
             'set': {'State': 'Blocked', 'Country': 'NL'}},
            {'do': 'add_view', 'app': 'Suppliers', 'table': 'Orders', 'name': 'Big ones', 'type': 'grid'}, apply=True)
        self.assertTrue(all(s.ok for s in steps), [s.error for s in steps])
        table = Table.objects.get(app__name='Suppliers', name='Suppliers')
        data = Data(self.ann)
        globex = next(r for r in data.records(table) if data.label(r) == 'Globex')
        self.assertEqual(data.text(globex, data.field_named(table, 'State')), 'Blocked')
        self.assertEqual(data.text(globex, data.field_named(table, 'Country')), 'NL')
        self.assertIn('renamed to State, new choices', steps[2].text)

    def test_mistakes_are_explained(self):
        steps = self.run_plan(
            {'do': 'add_records', 'app': 'Tasks', 'table': 'Tasks', 'records': [{'Titel': 'x'}]},
            {'do': 'update_records', 'app': 'Tasks', 'table': 'Tasks', 'where': {'Title': 'No such task'}, 'set': {'Status': 'Done'}},
            {'do': 'add_field', 'app': 'Tasks', 'table': 'Tasks', 'field': {'name': 'Size', 'type': 'bigness'}},
            {'do': 'create_app', 'own': True, 'name': 'X', 'tables': 'not a list'},
            user=self.admin)
        self.assertIn('Record 1: Tasks has no field "Titel"', steps[0].error)
        self.assertIn('No record of Tasks has Title = No such task', steps[1].error)
        self.assertIn('no field type "bigness"', steps[2].error)
        self.assertIn('"tables" should be a list', steps[3].error)
        message = plans.fix_message(steps)
        self.assertIn('- Change 2 (update_records)', message)

    def test_only_what_they_may_do(self):
        steps = self.run_plan(
            {'do': 'add_space', 'tree': 'Organisation', 'name': 'Ops', 'parent': 'Company'},          # ann only looks at it
            {'do': 'add_records', 'app': 'Tasks', 'table': 'Tasks', 'records': [{'Title': 'x'}]},     # ann only looks at Tasks
            {'do': 'create_page', 'space': 'Engineering', 'title': 'Hi', 'body': '<p>x</p>'})
        self.assertIn('You may not add to', steps[0].error)
        self.assertIn('You may not change records of Tasks', steps[1].error)
        self.assertIn('You may not write in the space Engineering', steps[2].error)
        # a space whose tags she doesn't hold isn't there for her, not even its name
        tag = access.create_tag('Secret', self.admin)
        data = Data()
        secret = service.create_record(self.org, {'Name': 'Secret plans'}, user=self.admin, tags=[tag.pk])
        steps = self.run_plan({'do': 'create_page', 'space': 'Secret plans', 'title': 'Hi'})
        self.assertIn('There is no space "Secret plans" you can see', steps[0].error)
        AppAccess.objects.create(app=self.org.app, user=self.ann, role='editor')
        from django.contrib.auth import get_user_model
        ann = get_user_model().objects.get(pk=self.ann.pk)   # fresh permission caches
        steps = self.run_plan({'do': 'create_page', 'space': 'Engineering', 'title': 'Hi', 'body': '<p>x</p>'}, user=ann, apply=True)
        self.assertTrue(steps[0].ok, steps[0].error)
        self.assertIsNotNone(secret and data)

    def test_spaces_and_pages(self):
        steps = self.run_plan(
            {'do': 'add_space', 'tree': 'Organisation', 'name': 'Operations 2', 'parent': 'Company', 'values': {'Kind': 'Department'}},
            {'do': 'create_page', 'space': 'Operations 2', 'title': 'Handbook', 'emoji': '📘', 'body': '<h2>Start</h2><script>x()</script><p>Hi</p>'},
            {'do': 'create_page', 'space': 'Operations 2', 'title': 'Returns', 'parent': 'Handbook', 'body': '<p>R</p>'},
            {'do': 'update_page', 'space': 'Operations 2', 'page': 'Handbook', 'append': '<div class="panel info"><p>New</p></div>'},
            user=self.admin, apply=True)
        self.assertTrue(all(s.ok for s in steps), [s.error for s in steps])
        from extensions.docs.models import Page
        data = Data()
        space = next(r for r in data.records(self.org) if data.label(r) == 'Operations 2')
        self.assertEqual(data.text(space, data.field_named(self.org, 'Kind')), 'Department')
        handbook = Page.objects.get(space=space, title='Handbook')
        self.assertNotIn('script', handbook.body)
        self.assertIn('<div class="panel info"><p>New</p></div>', handbook.body)
        self.assertEqual(handbook.version, 2)
        self.assertEqual(Page.objects.get(title='Returns').parent, handbook)


class PromptTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.ann = User.objects.create_user('ann', password='pw')
        blueprints.install_many(['departments', 'tasks'], user=cls.admin, sample=True)
        tag = access.create_tag('Secret', cls.admin)
        org = Table.objects.get(app__blueprint='departments', key='departments')
        service.create_record(org, {'Name': 'Secret plans'}, user=cls.admin, tags=[tag.pk])

    def test_the_prompt(self):
        tasks = App.objects.get(name='Tasks')
        text = build(self.ann, 'Add a priority board', app=tasks, with_records=True)
        for part in ('Add a priority board', '"do": "create_app"', 'select (Single select)', 'Table "Tasks"',
                     'Status (select: To do, In progress, Blocked, Done)', 'Count the shelves', 'they may: only look',
                     'Trees of spaces', '"Organisation"', 'Engineering', '"do": "add_space"'):
            self.assertIn(part, text)
        self.assertNotIn('<<', text)
        self.assertNotIn('Secret plans', text)                         # a space whose tags they don't hold
        self.assertNotIn('Count the shelves', build(self.ann, 'x', app=tasks))   # records only when asked


class FlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        User.objects.create_superuser('admin', 'a@example.com', 'pw')   # past the first-run setup
        cls.ann = User.objects.create_user('ann', password='pw')
        cls.ben = User.objects.create_user('ben', password='pw')

    def test_ask_check_and_make(self):
        self.client.force_login(self.ann)
        self.assertContains(self.client.get(reverse('assistant:index')), 'What do you want?')
        response = self.client.post(reverse('assistant:index'), {'request': 'An app for suppliers'})
        run = Run.objects.get()
        self.assertRedirects(response, run.get_absolute_url())
        self.assertIn('An app for suppliers', run.prompt)
        self.assertContains(self.client.get(run.get_absolute_url()), 'Copy the prompt')

        self.client.post(reverse('assistant:check', args=[run.pk]), {'answer': 'Sorry, I can\'t.'})
        run.refresh_from_db()
        self.assertEqual(run.status, Run.Status.PROBLEMS)
        self.assertContains(self.client.get(run.get_absolute_url()), 'Osmia could not use your answer')

        self.client.post(reverse('assistant:check', args=[run.pk]), {'answer': '{"osmia": 1, "question": "Which fields?"}'})
        run.refresh_from_db()
        self.assertEqual((run.status, run.problem), (Run.Status.QUESTION, 'Which fields?'))

        self.client.post(reverse('assistant:check', args=[run.pk]), {'answer': answer(SUPPLIERS)})
        run.refresh_from_db()
        self.assertEqual(run.status, Run.Status.READY, run.results)
        self.assertFalse(App.objects.filter(name='Suppliers').exists())
        self.assertContains(self.client.get(run.get_absolute_url()), 'Make 1 change')

        self.client.force_login(self.ben)   # someone else's request
        self.assertEqual(self.client.get(run.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse('assistant:apply', args=[run.pk])).status_code, 404)

        self.client.force_login(self.ann)
        self.client.post(reverse('assistant:apply', args=[run.pk]))
        run.refresh_from_db()
        self.assertEqual(run.status, Run.Status.DONE)
        app = App.objects.get(name='Suppliers')
        self.assertContains(self.client.get(run.get_absolute_url()), app.get_absolute_url())

    def test_apply_needs_a_checked_answer(self):
        self.client.force_login(self.ann)
        run = Run.objects.create(user=self.ann, request='x', prompt='p', answer=answer(SUPPLIERS))
        self.client.post(reverse('assistant:apply', args=[run.pk]))
        self.assertFalse(App.objects.filter(name='Suppliers').exists())


class DependencyTests(TestCase):
    """AIs don't put computed fields in the order they depend on each other."""

    @classmethod
    def setUpTestData(cls):
        cls.ann = get_user_model().objects.create_user('ann', password='pw')

    def test_a_rollup_of_a_rollup_in_a_later_table(self):
        app = {'do': 'create_app', 'own': True, 'name': 'Purchasing', 'tables': [
            {'name': 'Suppliers', 'fields': [{'name': 'Name', 'type': 'text'},
                                             {'name': 'Total spend', 'type': 'rollup', 'link': 'Orders', 'field': 'Total', 'func': 'sum'}],
             'records': [{'Name': 'Acme'}]},
            {'name': 'Orders', 'fields': [{'name': 'Number', 'type': 'text'},
                                          {'name': 'Supplier', 'type': 'link', 'target': 'Suppliers', 'multiple': False, 'inverse_name': 'Orders'},
                                          {'name': 'Total', 'type': 'rollup', 'link': 'Lines', 'field': 'Line total', 'func': 'sum'}],
             'records': [{'Number': 'PO-1', 'Supplier': 'Acme'}]},
            {'name': 'Lines', 'fields': [{'name': 'Part', 'type': 'text'},
                                         {'name': 'Order', 'type': 'link', 'target': 'Orders', 'multiple': False, 'inverse_name': 'Lines'},
                                         {'name': 'Quantity', 'type': 'number'}, {'name': 'Unit price', 'type': 'currency'},
                                         {'name': 'Line total', 'type': 'formula', 'expression': '{Quantity} * {Unit price}'}],
             'records': [{'Part': 'Bolt', 'Order': 'PO-1', 'Quantity': 200, 'Unit price': 0.12},
                         {'Part': 'Plate', 'Order': 'PO-1', 'Quantity': 4, 'Unit price': 38.5}]}]}
        steps = plans.run(plans.parse(answer(app)), self.ann, apply=True)
        self.assertTrue(steps[0].ok, steps[0].error)
        suppliers = Table.objects.get(app__name='Purchasing', name='Suppliers')
        data = Data(self.ann)
        self.assertEqual(data.text(data.records(suppliers)[0], data.field_named(suppliers, 'Total spend')), '178')

    def test_a_field_that_never_exists(self):
        app = {'do': 'create_app', 'own': True, 'name': 'X', 'tables': [
            {'name': 'A', 'fields': [{'name': 'Name', 'type': 'text'},
                                     {'name': 'Sum', 'type': 'rollup', 'link': 'Nothing', 'field': 'Total', 'func': 'sum'}]}]}
        steps = plans.run(plans.parse(answer(app)), self.ann)
        self.assertIn('A has no field "Nothing"', steps[0].error)
