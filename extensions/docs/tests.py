from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core import access, blueprints, space as spaces
from core.canvas.sanitize import clean
from core.data import Data
from core.models import App, AppAccess, Field, Table, View

from .models import Page, PagePin, PageVersion


def engineering():
    """The Engineering space of the Organisation template's sample records."""
    org = Table.objects.get(app__blueprint='departments', key='departments')
    data = Data()
    return next(r for r in data.records(org) if data.label(r) == 'Engineering')


class SanitizeTests(TestCase):
    def test_only_what_the_editor_makes_survives(self):
        dirty = ('<p onclick="x()">Hi <script>alert(1)</script><b>there</b></p><style>p{}</style>'
                 '<a href="javascript:alert(1)">bad</a><a href="/r/3/">good</a><img src="http://evil/x.png">'
                 '<div class="panel info evil"><p>note</p></div><iframe src="x"></iframe><table><tr><td colspan="2">c</td></tr></table>')
        out = clean(dirty)
        for gone in ('script', 'alert', 'onclick', 'style', 'javascript', 'evil', 'iframe', '<img'):
            self.assertNotIn(gone, out)
        for kept in ('<b>there</b>', 'href="/r/3/"', 'class="panel info"', 'colspan="2"'):
            self.assertIn(kept, out)

    def test_unclosed_tags_are_closed(self):
        self.assertEqual(clean('<p><b>bold'), '<p><b>bold</b></p>')


class PageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.ann = User.objects.create_user('ann', password='pw')
        cls.ben = User.objects.create_user('ben', password='pw')
        blueprints.install_many(['departments', 'tasks'], user=cls.admin, sample=True)
        cls.space = engineering()
        # Ann writes in the Organisation's spaces; Ben may only look at them
        AppAccess.objects.create(app=App.objects.get(blueprint='departments'), user=cls.ann, role='editor')

    def setUp(self):
        self.client.force_login(self.ann)

    def write(self, title='How we test', body='<p>Hello</p>', parent=None, template='blank'):
        url = reverse('docs:new', args=[self.space.pk]) + f'?template={template}' + (f'&parent={parent.pk}' if parent else '')
        self.assertEqual(self.client.get(url).status_code, 200)
        data = {'title': title, 'body': body, 'labels': 'how-to, testing'}
        if parent:
            data['parent'] = parent.pk
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.content[:500])
        return Page.objects.get(title=title)

    def test_write_read_and_edit_a_page(self):
        page = self.write(body='<h2>Steps</h2><ul class="tasks"><li class="task" data-checked="true">Plug in</li></ul><script>x</script>')
        self.assertNotIn('script', page.body)
        self.assertEqual(page.label_list, ['how-to', 'testing'])
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, 'Plug in')
        self.assertContains(response, 'How we test')
        self.client.post(reverse('docs:edit', args=[page.pk]), {'title': 'How we test', 'body': '<p>New text</p>', 'note': 'shorter'})
        page.refresh_from_db()
        self.assertEqual(page.version, 2)
        self.assertEqual(PageVersion.objects.filter(page=page).count(), 2)
        self.client.post(reverse('docs:restore', args=[page.pk, 1]))
        page.refresh_from_db()
        self.assertIn('Plug in', page.body)
        self.assertEqual(page.version, 3)

    def test_templates_and_tree(self):
        parent = self.write('Team handbook', template='howto')
        child = self.write('Meeting 1', template='meeting', parent=parent)
        self.assertEqual(child.parent, parent)
        response = self.client.get(child.get_absolute_url())
        self.assertContains(response, 'Team handbook')  # breadcrumbs and tree
        self.assertContains(self.client.get(reverse('docs:new', args=[self.space.pk]) + '?template=meeting'), 'Action items')
        self.client.post(reverse('docs:move', args=[parent.pk]), {'parent': child.pk})  # not under itself
        parent.refresh_from_db()
        self.assertIsNone(parent.parent)

    def test_live_views_and_record_links(self):
        view = View.objects.filter(table__key='tasks', type='grid').first()
        task = view.table.records.first()
        page = self.write(body=f'<div class="embed-view" data-view="{view.pk}">old</div><p><a class="record-ref" data-record="{task.pk}">x</a></p>')
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, '· live')
        self.assertContains(response, 'Count the shelves')  # a record from the view, as it is now
        self.assertContains(response, f'href="/r/{task.pk}/"')

    def test_who_may_do_what(self):
        page = self.write()
        self.client.force_login(self.ben)  # ben can read and comment, not write
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse('docs:edit', args=[page.pk])).status_code, 403)
        self.client.post(reverse('docs:comment', args=[page.pk]), {'text': 'Nice'})
        self.assertEqual(page.comments.count(), 1)
        self.assertEqual(self.client.post(reverse('docs:delete', args=[page.pk])).status_code, 403)
        AppAccess.objects.create(app=App.objects.get(blueprint='departments'), user=self.ben, role='editor')
        self.client.force_login(get_user_model().objects.get(pk=self.ben.pk))
        self.assertEqual(self.client.get(reverse('docs:edit', args=[page.pk])).status_code, 200)

    def test_a_tagged_space_hides_its_pages(self):
        page = self.write()
        tag = access.create_tag('Secret', self.ann)
        access.set_tags(self.space, [tag.pk], self.ann)
        page.refresh_from_db()
        self.assertEqual(page.access, [tag.pk])   # a page carries its space's tags
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 200)
        for who in (self.ben, get_user_model().objects.get(username='admin')):   # administrators too
            self.client.force_login(who)
            self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 404)
            self.assertNotContains(self.client.get('/search/?q=how we test'), 'How we test')

    def test_a_page_with_its_own_tag(self):
        tag = access.create_tag('Payroll', self.ann)
        url = reverse('docs:new', args=[self.space.pk])
        self.client.post(url, {'title': 'Salaries', 'body': '<p>x</p>', 'tags': [tag.pk]})
        page = Page.objects.get(title='Salaries')
        self.assertEqual(page.access, [tag.pk])
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse('docs:space', args=[self.space.pk])), page.get_absolute_url())

    def test_pin_search_and_space_overview(self):
        page = self.write('Release checklist')
        self.client.post(reverse('docs:pin', args=[page.pk]))
        self.assertTrue(PagePin.objects.filter(user=self.ann, page=page).exists())
        self.assertContains(self.client.get('/'), 'Release checklist')        # the Pinned pages block of her home
        self.assertContains(self.client.get('/search/?q=checklist'), 'Release checklist')
        self.assertContains(self.client.get(reverse('core:space', args=[self.space.pk])), 'Release checklist')
        self.assertContains(self.client.get(reverse('docs:space', args=[self.space.pk]) + '?label=how-to'), 'Release checklist')
        self.assertContains(self.client.get(reverse('docs:index')), 'Release checklist')

    def test_upload_a_picture(self):
        from io import BytesIO

        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (40, 30), 'red').save(buf, 'PNG')
        response = self.client.post(reverse('docs:upload', args=[self.space.pk]), {'file': SimpleUploadedFile('a.png', buf.getvalue(), 'image/png')})
        self.assertEqual(response.status_code, 200, response.content)
        url = response.json()['url']
        page = self.write(body=f'<p><img src="{url}"></p>')
        self.assertIn(url, page.body)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_pages_in_a_home_space(self):
        home = spaces.home_node(self.ben)   # Ben may write in his own home space, not in Ann's
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(reverse('docs:new', args=[home.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('docs:new', args=[spaces.home_node(self.ann).pk])).status_code, 403)


class RecordSnippetTests(TestCase):
    """Cards and values of records on pages, and the pages a record is mentioned in."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['departments', 'tasks'], user=cls.admin, sample=True)
        cls.space = engineering()
        cls.table = Table.objects.get(key='tasks')
        cls.task = cls.table.records.first()
        cls.title = cls.table.fields.get(name='Title')
        cls.status = cls.table.fields.get(name='Status')
        cls.other_field = Field.objects.exclude(table=cls.table).first()

    def setUp(self):
        self.client.force_login(self.admin)

    def write(self, body, title='Plan'):
        response = self.client.post(reverse('docs:new', args=[self.space.pk]), {'title': title, 'body': body})
        self.assertEqual(response.status_code, 302, response.content[:500])
        return Page.objects.get(title=title)

    def card(self, *fields):
        return f'<div class="record-card" data-record="{self.task.pk}" data-fields="{",".join(str(f.pk) for f in fields)}">old</div>'

    def value(self, field):
        return f'<p>Now: <span class="record-value" data-record="{self.task.pk}" data-field="{field.pk}">x › y</span></p>'

    def test_sanitize_keeps_cards_and_values(self):
        out = clean(self.card(self.title, self.status) + self.value(self.status)
                    + '<div class="record-card" data-record="1" data-fields="1,x" onclick="y()">z</div>')
        self.assertIn(f'data-fields="{self.title.pk},{self.status.pk}"', out)
        self.assertIn(f'data-field="{self.status.pk}"', out)
        self.assertNotIn('1,x', out)
        self.assertNotIn('onclick', out)

    def test_card_and_value_show_the_record_as_it_is_now(self):
        from core.data import Data
        page = self.write(self.card(self.title, self.status, self.other_field) + self.value(self.title))
        label = Data(self.admin).label(self.task)
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, 'class="record-card live"')
        self.assertContains(response, '<dt>Status</dt>')
        self.assertContains(response, '1 field on this card was deleted')   # a field of another table isn't shown
        self.assertContains(response, f'class="record-value" href="/r/{self.task.pk}/"')
        self.assertContains(response, f'>{label}</a>')
        self.task.data = {**self.task.data, self.title.key: 'Renamed task'}
        self.task.save()
        self.assertContains(self.client.get(page.get_absolute_url()), '>Renamed task</a>')  # live

    def test_what_the_reader_cannot_see(self):
        page = self.write(self.card(self.status) + self.value(self.status))
        with mock.patch('core.canvas.render.can', return_value=False):
            response = self.client.get(page.get_absolute_url())
        self.assertNotContains(response, '<dt>Status</dt>')   # not shown, not even as "locked"
        self.assertNotContains(response, 'class="record-value"')
        self.assertNotContains(response, '🔒')
        tag = access.create_tag('Hidden', self.admin)
        access.set_tags(self.task, [tag.pk], self.admin)
        reader = get_user_model().objects.create_user('reader', password='pw')
        self.client.force_login(reader)
        response = self.client.get(page.get_absolute_url())
        self.assertNotContains(response, 'record-card live')
        self.client.force_login(self.admin)
        self.task.delete()
        self.assertNotContains(self.client.get(page.get_absolute_url()), 'record-card live')

    def test_record_for_the_picker(self):
        response = self.client.get(reverse('core:editor_record', args=[self.task.pk]))
        self.assertEqual(response.status_code, 200)
        names = [f['name'] for f in response.json()['fields']]
        self.assertIn('Status', names)
        with mock.patch('core.canvas.views.can', return_value=False):
            self.assertEqual(self.client.get(reverse('core:editor_record', args=[self.task.pk])).status_code, 404)

    def test_a_record_shows_the_pages_that_mention_it(self):
        page = self.write(self.value(self.status), title='Budget review')
        self.assertEqual(list(page.references.values_list('record_id', flat=True)), [self.task.pk])
        self.assertContains(self.client.get(self.task.get_absolute_url()), 'Mentioned in 1 page')
        self.client.post(reverse('docs:edit', args=[page.pk]), {'title': 'Budget review', 'body': '<p>Nothing live</p>'})
        self.assertFalse(page.references.exists())
        self.assertNotContains(self.client.get(self.task.get_absolute_url()), 'Mentioned in')
        self.client.post(reverse('docs:restore', args=[page.pk, 1]))
        self.assertTrue(page.references.exists())


class CalculationTests(TestCase):
    """Calculations on pages: named records, same-row cells, named results, and the limits."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        blueprints.install_many(['departments', 'tasks'], user=cls.admin, sample=True)
        cls.space = engineering()
        cls.tasks = Table.objects.get(key='tasks')
        cls.task = cls.tasks.records.first()
        cls.estimate = cls.tasks.fields.get(name='Estimate (h)')
        cls.group = Table.objects.get(key='groups').records.get(data__name='Inventory')

    def setUp(self):
        self.client.force_login(self.admin)

    def show(self, body):
        response = self.client.post(reverse('docs:new', args=[self.space.pk]), {'title': 'Sums', 'body': body})
        self.assertEqual(response.status_code, 302, response.content[:300])
        page = Page.objects.get(title='Sums')
        html = self.client.get(page.get_absolute_url()).content.decode()
        page.delete()
        return html

    def names(self):
        return (f'<p><a class="record-ref" data-record="{self.task.pk}" data-name="t">x</a> '
                f'<a class="record-ref" data-record="{self.group.pk}" data-name="g">y</a></p>')

    @staticmethod
    def calc(formula, name=''):
        from html import escape
        return f'<span class="page-calc" data-formula="{escape(formula)}"{f" data-name={chr(34)}{name}{chr(34)}" if name else ""}>ƒ</span>'

    def results(self, html):
        from core.canvas.calc import OUTPUT
        return OUTPUT.findall(html)

    def test_sanitize_keeps_formulas_and_names(self):
        out = clean('<span class="page-calc" data-formula="IF({a} &gt; 1, &quot;big&quot;, \'small\')" data-name="ok">x</span>'
                    '<a class="record-ref" data-record="1" data-name="2bad">y</a>')
        self.assertIn('data-name="ok"', out)
        self.assertNotIn('2bad', out)
        self.assertIn('data-formula="IF({a} &gt; 1, &quot;big&quot;, &#x27;small&#x27;)"', out)

    def test_records_named_on_the_page(self):
        from core.data import Data
        data = Data(self.admin)
        total = sum(data.value(r, self.estimate) or 0 for r in data.linked(data.record(self.group.pk), self.group.table.fields.get(key='tasks')))
        html = self.show(self.names() + '<p>' + self.calc('{t.Estimate (h)} * 2') + ' and ' + self.calc('SUM({g.Tasks.Estimate (h)})')
                         + ' and ' + self.calc('{nope.Total}') + ' and ' + self.calc('10 / 3') + '</p>')
        self.assertEqual(self.results(html)[:2], ['12', str(int(total))])
        self.assertIn('Nothing on this page is called {nope.Total}', self.results(html)[2])
        self.assertEqual(self.results(html)[3], '3.3333')   # long decimals are cut to 4 places

    def test_a_page_table_row(self):
        value = f'<span class="record-value" data-record="{self.task.pk}" data-field="{self.estimate.pk}">v</span>'
        table = ('<table><thead><tr><th>Part</th><th>Qty</th><th>Hours</th><th>Total</th></tr></thead><tbody>'
                 f'<tr><td>Bolts</td><td>40</td><td>{value}</td><td>{self.calc("{t.Estimate (h)} * {Qty} + {Hours}")}</td></tr>'
                 f'<tr><td>Nuts</td><td>2</td><td>1</td><td>{self.calc("{Total} + 1")}</td></tr>'
                 f'<tr><td>Bad</td><td>x</td><td></td><td>{self.calc("{Qty} * 2")}</td></tr></tbody></table>')
        html = self.show(self.names() + table)
        self.assertEqual(self.results(html)[0], '246')   # 6 h * 40 + this row's 6 h (a live value in the Hours cell)
        self.assertIn('{Total} refers to itself', self.results(html)[1])
        self.assertIn('&quot;x&quot; is not a number', html)

    def test_named_results(self):
        html = self.show(self.names() + '<p>' + self.calc('{t.Estimate (h)} * 2', 'hours') + ' ' + self.calc('{hours} * 55')
                         + ' ' + self.calc('{loop} + 1', 'loop') + '</p>')
        self.assertEqual(self.results(html)[:2], ['12', '660'])
        self.assertIn('refers to itself', html)

    def test_what_the_reader_cannot_see(self):
        body = self.names() + '<p>' + self.calc('{t.Estimate (h)} * 2') + '</p>'
        with mock.patch('core.canvas.calc.can', return_value=False):
            html = self.show(body)
        self.assertEqual(self.results(html), [])   # nothing shown, not even a lock
        self.assertNotIn('>12<', html)

    def test_limits(self):
        from core.canvas import calc
        rows = ''.join(f'<tr><td>{n}</td><td>{self.calc("{N} * 2")}</td></tr>' for n in range(3))
        with mock.patch.object(calc, 'MAX_TABLE_ROWS', 2):
            html = self.show(f'<table><tr><th>N</th><th>Twice</th></tr>{rows}</table>')
        self.assertEqual(self.results(html)[:2], ['0', '2'])
        self.assertIn('Only the first 2 rows', self.results(html)[2])
        with mock.patch.object(calc, 'MAX_CALCS', 1):
            html = self.show('<p>' + self.calc('1') + self.calc('2') + '</p>')
        self.assertIn('Only the first 1 calculations', self.results(html)[1])
        with mock.patch.object(calc, 'MAX_LINKED', 1):
            html = self.show(self.names() + '<p>' + self.calc('SUM({g.Tasks.Estimate (h)})') + '</p>')
        self.assertIn('too many to work out on a page', html)

    def test_big_tables_are_not_loaded_whole(self):
        from core.canvas import calc
        body = self.names() + '<p>' + self.calc('COUNTA({g.Tasks})') + '</p>'
        normal = self.results(self.show(body))
        with mock.patch.object(calc, 'BIG_TABLE', 0):   # every table counts as big: links read a record at a time
            self.assertEqual(self.results(self.show(body)), normal)
            view = View.objects.filter(table=self.tasks, type='grid').first()
            self.assertIn('more than the 0 a page shows', self.show(f'<div class="embed-view" data-view="{view.pk}">v</div>'))
            found = self.client.get(reverse('core:editor_records') + '?q=shelves').json()['records']
            self.assertTrue(any(r['id'] == self.task.pk for r in found))

    def test_preview(self):
        body = self.names() + '<p>' + self.calc('1 + 1') + self.calc('{t.Estimate (h)}') + '</p>'
        response = self.client.post(reverse('core:editor_calc'), {'body': body, 'index': 1})
        self.assertEqual(response.json()['html'], '6')
