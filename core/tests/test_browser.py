"""Osmia in a real browser: every feature clicked through as people use it.

Each test starts a fresh workspace behind a live server, drives it with
Playwright (Edge, Chrome, or Playwright's Chromium) and checks both what the
page shows and what ended up in the database. A JavaScript error on any page
fails the test.

Slow (a minute or two), so it is tagged: ``manage.py test --tag browser`` runs
only these, ``manage.py test --exclude-tag browser`` everything else. Without
Playwright (``pip install -r requirements-dev.txt``) or a browser they're skipped.
"""
import os
import re
import tempfile
import time
from pathlib import Path
from unittest import SkipTest

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag

from core import access, blueprints, schema, service
from core.data import Data
from core.models import (AccessGrant, App, Attachment, Automation, Comment, Field, Layout, Record, Star, Table, Tag,
                         View)

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:   # the fast suite runs without it
    sync_playwright = None

TIMEOUT = 10_000   # ms: how long a page may take to show something


@tag('browser')
class BrowserTestCase(StaticLiveServerTestCase):
    """A live Osmia, a browser, and helpers to drive it."""
    templates = []          # app templates to install for each test (with their sample records)

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise SkipTest('Playwright is not installed: pip install -r requirements-dev.txt')
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'   # Playwright's sync API runs an event loop in this thread
        super().setUpClass()
        cls._playwright = sync_playwright().start()
        cls.browser = None
        for options in ({'channel': 'msedge'}, {'channel': 'chrome'}, {}, {'executable_path': '/opt/pw-browsers/chromium'}):
            try:
                cls.browser = cls._playwright.chromium.launch(**options)
                break
            except Exception:
                continue
        if cls.browser is None:
            cls._playwright.stop()
            super().tearDownClass()
            raise SkipTest('No browser to test with: install Edge or Chrome, or run "playwright install chromium".')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()
        super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw', first_name='Ada', last_name='Admin')
        self.alice = User.objects.create_user('alice', password='pw', first_name='Alice', last_name='Martin')
        self.bob = User.objects.create_user('bob', password='pw', first_name='Bob', last_name='Jansen')
        self.carla = User.objects.create_user('carla', password='pw', first_name='Carla', last_name='Rossi')
        if self.templates:
            blueprints.install_many(self.templates, user=self.admin, sample=True)
        self.context = None
        self.errors = []
        self.dialogs = []
        self.accept_dialogs = True
        self.log_in(self.admin)

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        self.assertEqual(self.errors, [], 'The pages had JavaScript errors')

    # -- the browser ---------------------------------------------------------------------

    def log_in(self, user):
        """A fresh browser window logged in as ``user``."""
        if self.context is not None:
            self.context.close()
        self.client.force_login(user)
        self.context = self.browser.new_context(viewport={'width': 1400, 'height': 900}, accept_downloads=True)
        self.context.add_cookies([{'name': 'sessionid', 'value': self.client.cookies['sessionid'].value,
                                   'url': self.live_server_url}])
        self.page = self.context.new_page()
        self.page.set_default_timeout(TIMEOUT)
        self.page.on('pageerror', lambda e: self.errors.append(f'{self.page.url}: {e}'))
        self.page.on('dialog', self._dialog)
        return self.page

    def _dialog(self, dialog):
        self.dialogs.append(dialog.message)
        if self.accept_dialogs:
            dialog.accept()
        else:
            dialog.dismiss()

    def go(self, path):
        self.page.goto(self.live_server_url + path)
        self.page.wait_for_load_state('networkidle')
        return self.page

    def settle(self):
        self.page.wait_for_load_state('networkidle')

    def see(self, text):
        expect(self.page.locator('body')).to_contain_text(text)

    def dont_see(self, text):
        expect(self.page.locator('body')).not_to_contain_text(text)

    def eventually(self, check, message='', timeout=TIMEOUT / 1000):
        """Wait until ``check()`` is true (the page saves in the background)."""
        from django.db import OperationalError
        end = time.time() + timeout
        while True:
            try:
                value = check()
            except OperationalError:   # the server is writing just now ("table is locked")
                value = None
            if value:
                return value
            if time.time() > end:
                self.fail(message or 'It never happened')
            self.page.wait_for_timeout(100)   # not time.sleep: the browser's events (dialogs) are handled meanwhile

    # -- the data -----------------------------------------------------------------------

    def record(self, table, label):
        data = Data()
        return next((r for r in data.records(table) if data.label(r) == label), None)

    def value(self, record, field):
        data = Data()
        return data.value(data.record(record.pk), field)

    def text(self, record, field):
        data = Data()
        rec = data.record(record.pk)
        return data.text(rec, field) if rec is not None else None

    def cell(self, record, field):
        return self.page.locator(f'.cell[data-record="{record.pk}"][data-field="{field.pk}"]').first

    def edit_cell(self, record, field, typed):
        """Open a text, number or date cell's editor, type, and press Enter."""
        self.cell(record, field).dblclick()
        box = self.page.locator('.editor input, .editor textarea').first
        box.fill(typed)
        box.press('Control+Enter' if field.type == 'longtext' else 'Enter')

    def pick_option(self, record, field, label):
        self.cell(record, field).dblclick()
        self.page.locator('.editor .option', has_text=label).first.click()

    def open_menu(self, details):
        """Open a ⋯ menu (a <details>), unless it already is."""
        menu = self.page.locator(details).first
        if menu.get_attribute('open') is None:
            menu.locator('summary').first.click()

    def toast(self, text):
        expect(self.page.locator('.toast')).to_contain_text(text)

    # -- a small app every record test uses ------------------------------------------------

    def make_library(self):
        """Library: Books (every kind of field) linked to Authors."""
        app = schema.create_app('Library', self.admin, icon='📚', color='#7c3aed')
        authors = schema.create_table(app, 'Authors')
        books = schema.create_table(app, 'Books', primary='Title')
        f = {'title': books.fields.get(name='Title')}
        f['pages'] = schema.add_field(books, 'Pages', 'number')
        f['genre'] = schema.add_field(books, 'Genre', 'select',
                                      {'choices': [{'value': 'Novel', 'color': '#dbeafe'}, {'value': 'Poetry', 'color': '#fde68a'},
                                                   {'value': 'Essay', 'color': '#dcfce7'}]})
        f['read'] = schema.add_field(books, 'Read', 'checkbox')
        f['started'] = schema.add_field(books, 'Started', 'date')
        f['notes'] = schema.add_field(books, 'Notes', 'longtext')
        f['rating'] = schema.add_field(books, 'Rating', 'rating', {'max': 5})
        f['reader'] = schema.add_field(books, 'Reader', 'user')
        f['shelves'] = schema.add_field(books, 'Shelves', 'multiselect', {'choices': [{'value': 'Home'}, {'value': 'Office'}]})
        f['price'] = schema.add_field(books, 'Price', 'currency', {'symbol': '€', 'decimals': 2})
        f['author'] = schema.add_field(books, 'Author', 'link', {'target': authors.pk, 'multiple': False}, inverse_name='Books')
        f['double'] = schema.add_field(books, 'Double pages', 'formula', {'expression': '{Pages} * 2', 'format': 'number'})
        for name in ('Ursula Le Guin', 'Italo Calvino', 'Wislawa Szymborska'):
            service.create_record(authors, {'Name': name}, user=self.admin)
        data = Data()
        ursula = next(r for r in data.records(authors) if data.label(r) == 'Ursula Le Guin')
        for title, pages, genre in (('The Dispossessed', 387, 'Novel'), ('Invisible Cities', 165, 'Novel'),
                                    ('View with a Grain of Sand', 220, 'Poetry')):
            values = {'Title': title, 'Pages': pages, 'Genre': genre}
            if title == 'The Dispossessed':
                values['Author'] = [ursula.pk]
            service.create_record(books, values, user=self.admin)
        View.objects.create(table=books, name='By genre', type='kanban', config={'group_field': 'genre'}, position=1)
        View.objects.create(table=books, name='Reading calendar', type='calendar', config={'date_field': 'started'}, position=2)
        View.objects.create(table=books, name='Add a book', type='form', position=3)
        self.app, self.books, self.authors, self.f = app, books, authors, f
        self.grid = books.views.get(type='grid')
        return app


# =========================================================================================
# Records: adding one, adding many, changing them, deleting them
# =========================================================================================

class RecordTests(BrowserTestCase):
    def setUp(self):
        super().setUp()
        self.make_library()

    def count(self):
        return Record.objects.filter(table=self.books).count()

    def test_add_one_record_in_the_grid(self):
        self.go(self.grid.get_absolute_url())
        rows = self.page.locator('#grid tbody tr[data-record]')
        expect(rows).to_have_count(3)
        self.page.click('#add-record')
        expect(rows).to_have_count(4)
        new = Record.objects.filter(table=self.books).order_by('-pk').first()
        self.edit_cell(new, self.f['title'], 'The Left Hand of Darkness')
        self.eventually(lambda: self.text(new, self.f['title']) == 'The Left Hand of Darkness', 'the title was not saved')
        expect(self.cell(new, self.f['title'])).to_contain_text('The Left Hand of Darkness')
        self.edit_cell(new, self.f['pages'], '304')
        self.eventually(lambda: self.text(new, self.f['pages']) == '304')
        expect(self.cell(new, self.f['double'])).to_contain_text('608')   # the formula follows

    def test_add_one_record_with_the_form_and_every_kind_of_field(self):
        self.go(self.grid.get_absolute_url())
        self.page.click('a.btn:has-text("New")')
        self.page.fill(f'#f_{self.f["title"].pk}', 'Mr Palomar')
        self.page.fill(f'#f_{self.f["pages"].pk}', '126')
        self.page.select_option(f'#f_{self.f["genre"].pk}', 'Novel')
        self.page.check(f'#f_{self.f["read"].pk}')
        self.page.fill(f'#f_{self.f["started"].pk}', '2026-10-01')
        self.page.fill(f'#f_{self.f["notes"].pk}', 'Short pieces.\nWatching the waves.')
        self.page.fill(f'#f_{self.f["rating"].pk}', '4')
        self.page.select_option(f'#f_{self.f["reader"].pk}', str(self.alice.pk))
        self.page.check(f'input[name="f_{self.f["shelves"].pk}"][value="Office"]')
        self.page.fill(f'#f_{self.f["price"].pk}', '12.50')
        box = self.page.locator(f'.link-input[data-field="{self.f["author"].pk}"]')
        box.locator('button:has-text("Choose")').click()
        self.page.fill('.o-modal input[type=search]', 'Calvino')
        self.page.locator('.o-modal .picker-list a', has_text='Italo Calvino').click()
        expect(box).to_contain_text('Italo Calvino')
        self.page.click('#record-form button.primary')
        self.settle()
        self.see('Mr Palomar is added')
        book = self.record(self.books, 'Mr Palomar')
        self.assertIsNotNone(book)
        got = {k: self.text(book, f) for k, f in self.f.items()}
        self.assertEqual(got['pages'], '126')
        self.assertEqual(got['genre'], 'Novel')
        self.assertEqual(got['read'], 'Yes')
        self.assertEqual(self.value(book, self.f['started']).isoformat(), '2026-10-01')
        self.assertEqual(got['notes'], 'Short pieces.\nWatching the waves.')
        self.assertEqual(self.value(book, self.f['rating']), 4)
        self.assertEqual(got['reader'], 'Alice Martin')
        self.assertEqual(got['shelves'], 'Office')
        self.assertIn('12.50', got['price'])
        self.assertEqual(got['author'], 'Italo Calvino')
        self.assertEqual(got['double'], '252')
        # it is on its page, and the author's page lists it
        self.see('Mr Palomar')
        calvino = self.record(self.authors, 'Italo Calvino')
        self.go(calvino.get_absolute_url())
        expect(self.page.locator(f'#section-{self.f["author"].opt("inverse")}')).to_contain_text('Mr Palomar')

    def test_add_several_records_one_after_another(self):
        url = self.go(self.grid.get_absolute_url()).url
        self.page.click('a.btn:has-text("New")')
        for title in ('Earthsea', 'The Lathe of Heaven', 'Always Coming Home'):
            self.page.fill(f'#f_{self.f["title"].pk}', title)
            self.page.click('button[name="add_another"]')
            self.settle()
            self.see(f'{title} is added')
            expect(self.page.locator(f'#f_{self.f["title"].pk}')).to_have_value('')   # an empty form for the next one
        self.assertEqual(self.count(), 6)
        self.go(url.replace(self.live_server_url, ''))
        expect(self.page.locator('#grid tbody tr[data-record]')).to_have_count(6)
        for title in ('Earthsea', 'The Lathe of Heaven', 'Always Coming Home'):
            self.see(title)

    def test_add_several_records_in_the_grid(self):
        self.go(self.grid.get_absolute_url())
        for n in range(3):
            self.page.click('#add-record')
            expect(self.page.locator('#grid tbody tr[data-record]')).to_have_count(4 + n)
        self.assertEqual(self.count(), 6)

    def test_add_many_records_from_a_csv_file(self):
        path = Path(tempfile.mkdtemp()) / 'books.csv'
        path.write_text('Title,Pages,Genre,Author\nA Wizard of Earthsea,183,Novel,Ursula Le Guin\n'
                        'Cosmicomics,153,Novel,Italo Calvino\nPeople on a Bridge,80,Poetry,\nBad row,lots,Novel,\n', 'utf-8')
        self.go(self.grid.get_absolute_url())
        self.page.click('details.toolbar-menu summary')
        self.page.click('a:has-text("Import CSV")')
        self.page.set_input_files('#file', str(path))
        self.page.click('button.primary:has-text("Import")')
        self.settle()
        self.see('3')            # added
        self.see('Row 5')        # the bad one, with why
        self.assertEqual(self.count(), 6)
        cosmi = self.record(self.books, 'Cosmicomics')
        self.assertEqual(self.text(cosmi, self.f['author']), 'Italo Calvino')
        self.assertIsNone(self.record(self.books, 'Bad row'))

    def test_change_every_kind_of_field_in_the_grid(self):
        book = self.record(self.books, 'Invisible Cities')
        self.go(self.grid.get_absolute_url())
        # text
        self.edit_cell(book, self.f['title'], 'Le città invisibili')
        self.eventually(lambda: self.text(book, self.f['title']) == 'Le città invisibili')
        # number: a mistake is refused and says why
        self.edit_cell(book, self.f['pages'], 'many')
        self.toast('number')
        expect(self.cell(book, self.f['pages'])).to_have_class(re.compile('bad'))
        self.assertEqual(self.text(book, self.f['pages']), '165')
        self.edit_cell(book, self.f['pages'], '170')
        self.eventually(lambda: self.text(book, self.f['pages']) == '170')
        expect(self.cell(book, self.f['double'])).to_contain_text('340')
        # single select
        self.pick_option(book, self.f['genre'], 'Essay')
        self.eventually(lambda: self.text(book, self.f['genre']) == 'Essay')
        # checkbox: one click on the box ticks it, another unticks it
        self.cell(book, self.f['read']).locator('.check').click()
        self.eventually(lambda: self.value(book, self.f['read']) is True)
        self.cell(book, self.f['read']).locator('.check').click()
        self.eventually(lambda: self.value(book, self.f['read']) is False)
        # date
        self.cell(book, self.f['started']).dblclick()
        self.page.locator('.editor input[type=date]').fill('2026-09-30')
        self.eventually(lambda: self.text(book, self.f['started']) and self.value(book, self.f['started']).isoformat() == '2026-09-30')
        # long text (Ctrl+Enter saves)
        self.edit_cell(book, self.f['notes'], 'Marco Polo\nand Kublai Khan')
        self.eventually(lambda: self.text(book, self.f['notes']) == 'Marco Polo\nand Kublai Khan')
        # rating: click the third star
        self.cell(book, self.f['rating']).dblclick()
        self.page.locator('.editor .stars span').nth(2).click()
        self.eventually(lambda: self.value(book, self.f['rating']) == 3)
        # user
        self.pick_option(book, self.f['reader'], 'Bob Jansen')
        self.eventually(lambda: self.text(book, self.f['reader']) == 'Bob Jansen')
        # multiple select: tick two, click outside to save
        self.cell(book, self.f['shelves']).dblclick()
        self.page.locator('.editor .option', has_text='Home').click()
        self.page.locator('.editor .option', has_text='Office').click()
        self.page.mouse.click(5, 300)
        self.eventually(lambda: self.text(book, self.f['shelves']) == 'Home, Office')
        # currency
        self.edit_cell(book, self.f['price'], '9.9')
        self.eventually(lambda: self.value(book, self.f['price']) is not None and float(self.value(book, self.f['price'])) == 9.9)
        # link, through the picker
        self.cell(book, self.f['author']).dblclick()
        self.page.locator('.o-modal .picker-list a', has_text='Italo Calvino').click()
        self.eventually(lambda: self.text(book, self.f['author']) == 'Italo Calvino')
        expect(self.cell(book, self.f['author'])).to_contain_text('Italo Calvino')
        # formulas can't be edited
        self.cell(book, self.f['double']).dblclick()
        expect(self.page.locator('.editor')).to_have_count(0)

    def test_keyboard_in_the_grid(self):
        book = self.record(self.books, 'The Dispossessed')
        self.go(self.grid.get_absolute_url())
        self.cell(book, self.f['title']).click()                 # select
        self.page.keyboard.press('ArrowRight')                    # → Pages
        expect(self.cell(book, self.f['pages'])).to_have_class(re.compile('selected'))
        self.page.keyboard.type('4')                              # typing starts editing
        self.page.keyboard.type('00')
        self.page.keyboard.press('Enter')
        self.eventually(lambda: self.text(book, self.f['pages']) == '400')
        self.cell(book, self.f['pages']).click()
        self.page.keyboard.press('Enter')                         # Enter opens the editor
        self.page.keyboard.type('999')
        self.page.keyboard.press('Escape')                        # Escape: nothing changes
        self.page.wait_for_timeout(400)
        self.assertEqual(self.text(book, self.f['pages']), '400')
        self.page.keyboard.press('Delete')                        # Delete empties it
        self.eventually(lambda: self.text(book, self.f['pages']) == '')

    def test_change_a_record_on_its_page(self):
        book = self.record(self.books, 'The Dispossessed')
        self.go(book.get_absolute_url())
        expect(self.page.locator('#record-title')).to_have_text('The Dispossessed')
        self.cell(book, self.f['title']).click()
        box = self.page.locator('.editor input')
        box.fill('The Dispossessed (1974)')
        box.press('Enter')
        expect(self.page.locator('#record-title')).to_have_text('The Dispossessed (1974)')   # the title follows
        self.cell(book, self.f['genre']).click()
        self.page.locator('.editor .option', has_text='Essay').click()
        self.eventually(lambda: self.text(book, self.f['genre']) == 'Essay')
        # the history says what changed
        self.page.reload()
        self.page.click('.side-tabs button[data-side="history"]')
        expect(self.page.locator('[data-pane="history"]')).to_contain_text('Essay')
        # previous and next
        self.page.click('a[title="Next"]')
        self.settle()
        expect(self.page.locator('#record-title')).to_have_text('Invisible Cities')
        self.page.click('a[title="Previous"]')
        self.settle()
        expect(self.page.locator('#record-title')).to_have_text('The Dispossessed (1974)')

    def test_delete_one_record(self):
        book = self.record(self.books, 'Invisible Cities')
        self.go(book.get_absolute_url())
        self.accept_dialogs = False                               # "Delete …?" → Cancel keeps it
        self.open_menu('.record-head details.toolbar-menu')
        self.page.click('.record-head button:has-text("Delete")')
        self.page.wait_for_timeout(400)
        self.assertTrue(Record.objects.filter(pk=book.pk).exists())
        self.assertIn('Delete Invisible Cities?', self.dialogs[-1])
        self.accept_dialogs = True                                # → OK deletes it
        self.open_menu('.record-head details.toolbar-menu')
        self.page.click('.record-head button:has-text("Delete")')
        self.settle()
        self.see('Invisible Cities is deleted')
        self.assertFalse(Record.objects.filter(pk=book.pk).exists())
        expect(self.page.locator('#grid tbody tr[data-record]')).to_have_count(2)
        self.assertEqual(self.count(), 2)

    def test_delete_several_records(self):
        for title in ('The Dispossessed', 'Invisible Cities', 'View with a Grain of Sand'):
            book = self.record(self.books, title)
            self.go(self.grid.get_absolute_url())
            row = self.page.locator(f'tr[data-record="{book.pk}"]')
            row.hover()
            row.locator('a.open').click()
            self.settle()
            self.open_menu('.record-head details.toolbar-menu')
            self.page.click('.record-head button:has-text("Delete")')
            self.settle()
            self.see(f'{title} is deleted')
        self.assertEqual(self.count(), 0)
        self.go(self.grid.get_absolute_url())
        self.see('No records')
        # and they stay in the history
        self.go(f'/a/{self.app.slug}/history/')
        for title in ('The Dispossessed', 'Invisible Cities', 'View with a Grain of Sand'):
            self.see(title)

    def test_links_on_a_record_page(self):
        ursula = self.record(self.authors, 'Ursula Le Guin')
        inverse = Field.objects.get(pk=self.f['author'].opt('inverse'))
        self.go(ursula.get_absolute_url())
        section = self.page.locator(f'#section-{inverse.pk}')
        expect(section).to_contain_text('The Dispossessed')
        # link two more books
        section.locator('.link-add').click()
        self.page.locator('.o-modal .picker-list a', has_text='Invisible Cities').click()
        self.page.locator('.o-modal .picker-list a', has_text='View with a Grain of Sand').click()
        self.page.click('.o-modal header button:has-text("Done")')
        self.settle()
        expect(self.page.locator(f'#section-{inverse.pk} tbody tr')).to_have_count(3)
        self.assertEqual(self.text(self.record(self.books, 'Invisible Cities'), self.f['author']), 'Ursula Le Guin')
        # unlink one
        book = self.record(self.books, 'Invisible Cities')
        self.page.locator(f'#section-{inverse.pk} tr[data-record="{book.pk}"] .unlink').click()
        self.settle()
        expect(self.page.locator(f'#section-{inverse.pk} tbody tr')).to_have_count(2)
        self.assertEqual(self.text(book, self.f['author']), '')
        # a new linked row
        self.page.locator(f'#section-{inverse.pk} .quick-add').click()
        self.settle()
        expect(self.page.locator(f'#section-{inverse.pk} tbody tr')).to_have_count(3)
        self.assertEqual(self.count(), 4)

    def test_comments_stars_and_files(self):
        files = schema.add_field(self.books, 'Cover', 'attachment')
        book = self.record(self.books, 'The Dispossessed')
        self.go(book.get_absolute_url())
        # star, and it's on the home space; unstar
        self.page.click('.star-form button')
        self.settle()
        self.assertTrue(Star.objects.filter(user=self.admin, record=book).exists())
        self.page.click('.star-form button')
        self.settle()
        self.assertFalse(Star.objects.filter(user=self.admin, record=book).exists())
        # comment
        self.page.fill('.comment-form textarea', 'A book about walls.')
        self.page.click('.comment-form button')
        self.settle()
        expect(self.page.locator('[data-pane="comments"]')).to_contain_text('A book about walls.')
        self.assertEqual(Comment.objects.get(record=book).text, 'A book about walls.')
        # a file, then remove it
        path = Path(tempfile.mkdtemp()) / 'notes.txt'
        path.write_text('anarres', 'utf-8')
        self.page.set_input_files('.upload-form input[type=file]', str(path))
        self.settle()
        self.see('notes.txt')
        attachment = Attachment.objects.get(record=book, field=files)
        response = self.page.request.get(self.live_server_url + f'/files/{attachment.pk}/')
        self.assertEqual(response.body(), b'anarres')
        self.page.locator('.files .file').first.hover()
        self.page.click(f'form[action="/files/{attachment.pk}/delete/"] button')
        self.settle()
        self.assertFalse(Attachment.objects.filter(pk=attachment.pk).exists())

    def test_toolbar_search_filter_sort_group_and_fields(self):
        self.go(self.grid.get_absolute_url())
        rows = self.page.locator('#grid tbody tr[data-record]')
        # search
        self.page.fill('#search-form input[name=q]', 'cities')
        self.page.press('#search-form input[name=q]', 'Enter')
        self.settle()
        expect(rows).to_have_count(1)
        self.go(self.grid.get_absolute_url())
        # filter: Genre is Poetry
        self.page.click('[data-pop="filter"]')
        self.page.click('.popover button:has-text("Add a filter")')
        row = self.page.locator('.popover .row').nth(1)
        row.locator('select').nth(0).select_option('genre')
        row.locator('select').nth(1).select_option('is')
        row.locator('input').fill('Poetry')
        with self.page.expect_navigation():
            self.page.click('.popover button:has-text("Apply")')
        self.settle()
        expect(rows).to_have_count(1)
        self.see('View with a Grain of Sand')
        with self.page.expect_navigation():
            self.page.click('#save-view')                   # keep it for everyone
        self.settle()
        self.grid.refresh_from_db()
        self.assertEqual(self.grid.config['filters']['rules'][0]['value'], 'Poetry')
        expect(rows).to_have_count(1)
        # remove the filter again
        self.page.click('[data-pop="filter"]')
        self.page.click('.popover .row .btn.ghost')
        with self.page.expect_navigation():
            self.page.click('.popover button:has-text("Save for everyone")')
        self.settle()
        expect(rows).to_have_count(3)
        # sort by pages, largest first
        self.page.click('[data-pop="sort"]')
        self.page.click('.popover button:has-text("Sort by")')
        sort = self.page.locator('.popover .row').first
        sort.locator('select').nth(0).select_option('pages')
        sort.locator('select').nth(1).select_option('desc')
        with self.page.expect_navigation():
            self.page.click('.popover button:has-text("Apply")')
        self.settle()
        expect(rows.first).to_contain_text('The Dispossessed')
        expect(rows.last).to_contain_text('Invisible Cities')
        # group by genre
        self.page.click('[data-pop="group"]')
        self.page.locator('.popover select').select_option('genre')
        with self.page.expect_navigation():
            self.page.click('.popover button:has-text("Apply")')
        self.settle()
        expect(self.page.locator('#grid tr.group')).to_have_count(2)
        # hide a field for everyone
        self.go(self.grid.get_absolute_url())
        self.page.click('[data-pop="fields"]')
        self.page.locator('.popover .field-list label', has_text='Notes').locator('input').uncheck()
        with self.page.expect_navigation():
            self.page.click('.popover button:has-text("Save for everyone")')
        self.settle()
        expect(self.page.locator('#grid thead th', has_text='Notes')).to_have_count(0)
        self.page.click('[data-pop="fields"]')
        with self.page.expect_navigation():
            self.page.click('.popover button:has-text("Show all")')
        self.settle()
        expect(self.page.locator('#grid thead th', has_text='Notes')).to_have_count(1)

    def test_kanban_drag_a_card_to_another_column(self):
        book = self.record(self.books, 'Invisible Cities')
        self.go(self.books.views.get(type='kanban').get_absolute_url())
        card = self.page.locator(f'.kcard[data-record="{book.pk}"]')
        target = self.page.locator('.column[data-value="Essay"]')
        card.drag_to(target)
        self.eventually(lambda: self.text(book, self.f['genre']) == 'Essay', 'dragging the card did not change the genre')
        expect(target.locator('header .n')).to_have_text('1')
        self.go(self.books.views.get(type='kanban').get_absolute_url())
        expect(self.page.locator(f'.column[data-value="Essay"] .kcard[data-record="{book.pk}"]')).to_have_count(1)

    def test_calendar_drag_to_another_day(self):
        book = self.record(self.books, 'Invisible Cities')
        service.update_record(book, {'Started': '2026-10-05'}, user=self.admin)
        view = self.books.views.get(type='calendar')
        self.go(view.get_absolute_url() + '?month=2026-10')
        self.page.locator(f'.ev[data-record="{book.pk}"]').drag_to(self.page.locator('.day[data-date="2026-10-08"]'))
        self.eventually(lambda: self.value(book, self.f['started']).isoformat() == '2026-10-08')

    def test_the_form_view(self):
        view = self.books.views.get(type='form')
        self.go(view.get_absolute_url())
        self.page.fill(f'#f_{self.f["title"].pk}', 'The Baron in the Trees')
        self.page.fill(f'#f_{self.f["pages"].pk}', '217')
        self.page.click('#record-form button.primary')
        self.settle()
        self.see('The Baron in the Trees is added')
        self.assertIsNotNone(self.record(self.books, 'The Baron in the Trees'))

    def test_csv_download(self):
        self.go(self.grid.get_absolute_url())
        self.page.click('details.toolbar-menu summary')
        with self.page.expect_download() as info:
            self.page.click('a:has-text("Download CSV")')
        text = Path(info.value.path()).read_text('utf-8-sig')
        self.assertIn('Title,Pages,Genre', text)
        self.assertIn('Invisible Cities,165,Novel', text)
        self.assertEqual(len(text.strip().splitlines()), 4)

    def test_a_record_someone_may_only_look_at(self):
        self.app.default_role = 'viewer'
        self.app.save()
        self.log_in(self.bob)
        book = self.record(self.books, 'Invisible Cities')
        self.go(self.grid.get_absolute_url())
        self.see('You can look at Library but not change it')
        expect(self.page.locator('#add-record')).to_have_count(0)
        self.cell(book, self.f['title']).dblclick()
        expect(self.page.locator('.editor')).to_have_count(0)
        self.go(book.get_absolute_url())
        expect(self.page.locator('.comment-form')).to_have_count(0)


# =========================================================================================
# Building apps: apps, tables, fields, views, automations
# =========================================================================================

class BuilderTests(BrowserTestCase):
    def new_app(self, name='Workshop', table='Machines'):
        self.go('/')
        self.page.click('#launcher > summary')
        self.page.click('.launcher-foot a:has-text("New app")')
        self.page.fill('#name', name)
        self.page.fill('#icon', '🔧')
        self.page.fill('#description', 'Our machines and their service.')
        self.page.fill('#table', table)
        self.page.click('form button.primary')
        self.settle()
        return App.objects.get(name=name)

    def new_field(self, name, kind, fill=None):
        self.page.click('a.btn:has-text("New field")')
        self.page.fill('#name', name)
        self.page.click(f'.type-pick label:has(input[value="{kind}"])')
        if fill:
            fill()
        self.page.click('#field-form button.primary')
        self.settle()
        self.see(f'The field {name} is added')

    def test_make_an_app_with_fields_of_every_kind(self):
        app = self.new_app()
        self.assertEqual(app.owner, None)          # an administrator's app is for everyone
        table = app.tables.get(name='Machines')
        self.see('Fields')
        self.new_field('Serial number', 'text')
        self.new_field('Hours run', 'number')
        self.new_field('In service', 'checkbox')
        self.new_field('Next service', 'date')

        def choices():
            for value in ('Running', 'Down', 'Retired'):
                self.page.click('#add-choice')
                self.page.locator('#choices input[name=choice_value]').last.fill(value)
        self.new_field('State', 'select', choices)
        self.new_field('Keeper', 'user')
        self.new_field('Hours left', 'formula', lambda: self.page.fill('#expression', '1000 - {Hours run}'))
        # a second table, linked to the first
        self.page.click('.app-tabs a.add')
        self.page.fill('#name', 'Services')
        self.page.click('form button.primary')
        self.settle()
        services = app.tables.get(name='Services')

        def link():
            self.page.select_option('#target', str(table.pk))
        self.new_field('Machine', 'link', link)
        self.new_field('Hours', 'number')
        self.go(f'/a/{app.slug}/{table.slug}/fields/')
        through = table.fields.get(name='Services')   # the other half of Services' Machine link
        self.new_field('Service count', 'rollup', lambda: (self.page.select_option('#link', str(through.pk)),
                                                             self.page.select_option('#func', 'count')))
        names = list(table.fields.values_list('name', flat=True))
        for name in ('Name', 'Serial number', 'Hours run', 'In service', 'Next service', 'State', 'Keeper', 'Hours left',
                     'Services', 'Service count'):
            self.assertIn(name, names)
        self.assertEqual(Field.objects.get(table=services, name='Machine').opt('target'), table.pk)
        self.assertNotIn('max', Field.objects.get(table=table, name='Hours run').options)   # no limit nobody set
        # it works: add a machine, two services
        lathe = service.create_record(table, {'Name': 'Lathe', 'Hours run': 400}, user=self.admin)
        machine = Field.objects.get(table=services, name='Machine')
        for hours in (2, 3):
            service.create_record(services, {'Name': f'{hours} h', 'Machine': [lathe.pk], 'Hours': hours}, user=self.admin)
        self.go(lathe.get_absolute_url())
        self.see('600')       # hours left
        expect(self.cell(lathe, Field.objects.get(table=table, name='Service count'))).to_contain_text('2')
        self.assertIsNotNone(machine)

    def test_rename_and_delete_fields(self):
        app = self.new_app()
        table = app.tables.get()
        self.new_field('Hours', 'number')
        self.new_field('Double', 'formula', lambda: self.page.fill('#expression', '{Hours} * 2'))
        hours = table.fields.get(name='Hours')
        # rename: the formula follows
        self.go(f'/a/{app.slug}/{table.slug}/fields/{hours.pk}/')
        self.page.fill('#name', 'Hours run')
        self.page.click('#field-form button.primary')
        self.settle()
        self.assertEqual(table.fields.get(name='Double').opt('expression'), '{Hours run} * 2')
        # deleting a field something uses is refused, and says what uses it
        self.go(f'/a/{app.slug}/{table.slug}/fields/{hours.pk}/')
        self.page.click('#field-form button[name=delete]')
        self.settle()
        self.see("can't be removed while something uses it")
        self.see('Double')
        self.assertTrue(Field.objects.filter(pk=hours.pk).exists())
        # delete the formula first, then it goes
        double = table.fields.get(name='Double')
        self.go(f'/a/{app.slug}/{table.slug}/fields/{double.pk}/')
        self.page.click('#field-form button[name=delete]')
        self.settle()
        self.see('The field Double is deleted')
        self.go(f'/a/{app.slug}/{table.slug}/fields/{hours.pk}/')
        self.page.click('#field-form button[name=delete]')
        self.settle()
        self.see('The field Hours run is deleted')
        self.assertFalse(Field.objects.filter(pk=hours.pk).exists())

    def test_views_of_every_kind(self):
        app = self.new_app()
        table = app.tables.get()
        schema.add_field(table, 'State', 'select', {'choices': [{'value': 'Running'}, {'value': 'Down'}]})
        schema.add_field(table, 'Start', 'date')
        schema.add_field(table, 'End', 'date')
        schema.add_field(table, 'Part of', 'link', {'target': table.pk, 'multiple': False}, inverse_name='Under it')
        service.create_record(table, {'Name': 'Lathe', 'State': 'Down', 'Start': '2026-10-01', 'End': '2026-10-09'}, user=self.admin)
        for kind, label in (('kanban', 'Kanban'), ('calendar', 'Calendar'), ('gantt', 'Gantt'), ('gallery', 'Gallery'),
                            ('tree', 'Tree'), ('form', 'Form'), ('detail', 'Detail')):
            self.go(table.get_absolute_url())
            self.settle()
            self.page.click('.tabs details summary:has-text("View")')
            self.page.click(f'.tabs .menu-panel button[title]:has-text("{label}")')
            self.settle()
            view = table.views.order_by('-pk').first()
            self.assertEqual(view.type, kind)
            if '/settings/' in self.page.url:   # some ask for settings first (a form, or what's missing)
                self.page.click('form button.primary:has-text("Save")')
                self.settle()
            self.go(view.get_absolute_url())
            self.dont_see('Traceback')
        self.assertEqual(table.views.count(), 8)
        kanban = table.views.get(type='kanban')
        self.go(kanban.get_absolute_url())
        expect(self.page.locator('.column[data-value="Down"] .kcard')).to_have_count(1)
        # rename, duplicate and delete a view
        self.go(f'/a/{app.slug}/{table.slug}/v/{kanban.pk}/settings/')
        self.page.fill('#name', 'Board')
        self.page.click('form button.primary:has-text("Save")')
        self.settle()
        self.see('The view Board is saved')
        self.go(f'/a/{app.slug}/{table.slug}/v/{kanban.pk}/settings/')
        self.page.click('button[name=duplicate]')
        self.settle()
        self.assertTrue(table.views.filter(name='Board (copy)').exists())
        copy = table.views.get(name='Board (copy)')
        self.go(f'/a/{app.slug}/{table.slug}/v/{copy.pk}/settings/')
        self.page.click('button[name=delete]')
        self.settle()
        self.assertFalse(View.objects.filter(pk=copy.pk).exists())

    def test_the_last_view_stays(self):
        app = self.new_app()
        table = app.tables.get()
        view = table.views.get()
        self.go(f'/a/{app.slug}/{table.slug}/v/{view.pk}/settings/')
        self.page.click('button[name=delete]')
        self.settle()
        self.see('A table keeps at least one view')
        self.assertTrue(View.objects.filter(pk=view.pk).exists())

    def test_an_automation_made_in_the_builder(self):
        app = self.new_app()
        table = app.tables.get()
        schema.add_field(table, 'State', 'select', {'choices': [{'value': 'New'}, {'value': 'Running'}]})
        self.go(f'/a/{app.slug}/automations/new/')
        self.page.fill('#a-name', 'Every machine starts as New')
        self.page.locator('#trigger select').select_option('record_created')
        self.page.select_option('#add-step', 'update_record')
        step = self.page.locator('.auto-step').first
        step.locator('select', has_text='Set a field').select_option(label='State')
        step.locator('.values-row input').fill('New')
        self.page.click('#automation-form button.primary')
        self.settle()
        self.see('The automation Every machine starts as New is saved')
        auto = Automation.objects.get(name='Every machine starts as New')
        self.assertEqual(auto.actions[0]['values'], {'state': 'New'})
        # it runs: a machine made in the grid gets the state
        self.go(table.get_absolute_url())
        self.settle()
        self.page.click('#add-record')
        self.settle()
        record = self.eventually(lambda: Record.objects.filter(table=table).first())
        self.eventually(lambda: self.text(record, table.fields.get(name='State')) == 'New')
        self.go(f'/a/{app.slug}/automations/runs/')
        self.see('Every machine starts as New')
        # and it can be deleted
        self.go(f'/a/{app.slug}/automations/{auto.pk}/')
        self.page.click('button[name=delete]')
        self.settle()
        self.assertFalse(Automation.objects.filter(pk=auto.pk).exists())

    def test_my_own_app_and_sharing_it(self):
        self.log_in(self.alice)
        app = self.new_app('My plants', 'Plants')
        self.assertEqual(app.owner, self.alice)
        self.log_in(self.bob)
        self.go('/apps/')
        self.dont_see('My plants')
        self.assertEqual(self.page.goto(self.live_server_url + app.get_absolute_url()).status, 403)
        self.log_in(self.alice)
        self.go(f'/a/{app.slug}/settings/')
        self.page.select_option('#default_role', 'viewer')
        self.page.click('form button.primary:has-text("Save")')
        self.settle()
        self.log_in(self.bob)
        self.go('/apps/')
        self.see('My plants')

    def test_delete_an_app(self):
        app = self.new_app()
        self.go(f'/a/{app.slug}/settings/')
        self.page.fill('#confirm', 'wrong name')
        self.page.click('button[name=delete]')
        self.settle()
        self.see('to delete it')
        self.assertTrue(App.objects.filter(pk=app.pk).exists())
        self.page.fill('#confirm', app.name)
        self.page.click('button[name=delete]')
        self.settle()
        self.see('Workshop and all its records are deleted')
        self.assertFalse(App.objects.filter(pk=app.pk).exists())


class BuilderWithTemplatesTests(BrowserTestCase):
    templates = ['departments', 'projects', 'stock', 'orders']

    def test_an_app_in_use_cant_be_deleted(self):
        parts = App.objects.get(blueprint='parts')
        self.go(f'/a/{parts.slug}/settings/')
        self.see("can't be deleted while something uses it")
        self.see('Stock')
        self.page.fill('#confirm', parts.name)
        self.page.click('button[name=delete]')
        self.settle()
        self.assertTrue(App.objects.filter(pk=parts.pk).exists())

    def test_a_button_runs_its_automation(self):
        orders = Table.objects.get(app__blueprint='orders', key='orders')
        order = self.record(orders, 'PO-0003')
        status = orders.fields.get(key='status')
        before = self.text(order, status)
        place = orders.fields.get(key='place')
        self.go(order.get_absolute_url())
        self.page.click(f'.run-button[data-field="{place.pk}"]')
        self.toast('')
        self.eventually(lambda: self.text(order, status) != before, 'pressing Place order changed nothing')
        self.page.wait_for_load_state('load')
        self.see(self.text(order, status))
        # the record's history says the button was pressed
        self.go(order.get_absolute_url())
        self.page.click('.side-tabs button[data-side="history"]')
        expect(self.page.locator('[data-pane="history"]')).to_contain_text('pressed')

    def test_a_tree_view_opens_and_closes(self):
        org = Table.objects.get(app__blueprint='departments', key='departments')
        view = org.views.get(type='tree')
        self.go(view.get_absolute_url())
        company = self.record(org, 'Company')
        operations = self.record(org, 'Operations')
        row = self.page.locator(f'tr[data-record="{operations.pk}"]')
        expect(row).to_be_visible()
        self.page.locator(f'tr[data-record="{company.pk}"] .toggle').click()
        expect(row).to_be_hidden()
        self.page.locator(f'tr[data-record="{company.pk}"] .toggle').click()
        expect(row).to_be_visible()

    def test_a_tree_never_goes_round(self):
        projects = Table.objects.get(app__blueprint='projects', key='projects')
        programme = self.record(projects, 'Product development')
        project = self.record(projects, 'Burn-in test bench')
        parent = projects.fields.get(key='parent')
        self.go(programme.get_absolute_url())
        self.cell(programme, parent).click()
        self.page.locator('.o-modal .picker-list a', has_text='Burn-in test bench').click()
        self.toast('under itself')
        self.assertEqual(self.text(programme, parent), '')
        self.assertIsNotNone(project)


# =========================================================================================
# Spaces, home spaces and pages made of blocks
# =========================================================================================

class SpaceTests(BrowserTestCase):
    templates = ['departments', 'projects']

    def editor_at_top(self):
        """Put the caret in a new empty paragraph at the top of the editor."""
        self.page.evaluate("""() => { const e = document.getElementById('editor'); const p = document.createElement('p');
            p.innerHTML = '<br>'; e.prepend(p); e.focus(); const r = document.createRange(); r.setStart(p, 0); r.collapse(true);
            const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")

    def slash(self, typed, pick=None):
        self.page.keyboard.type('/' + typed)
        menu = self.page.locator('.slash-menu')
        expect(menu).to_be_visible()
        if pick:
            menu.locator('.slash-item', has_text=pick).first.click()
        else:
            self.page.keyboard.press('Enter')
        expect(menu).to_be_hidden()

    def test_land_in_my_home_space(self):
        self.log_in(self.alice)
        self.go('/')
        self.see('your home space')
        self.see('My work')
        expect(self.page.locator('h1')).to_contain_text('Alice Martin')
        # the crumbs show where it is in the organisation
        expect(self.page.locator('.space-head .crumbs')).to_contain_text('Engineering')
        # my work: assigned, recent, starred
        self.see('Write the test procedure')
        self.page.click('.work-tabs button[data-side="recent"]')
        expect(self.page.locator('[data-pane="recent"]')).to_be_visible()
        expect(self.page.locator('[data-pane="assigned"]')).to_be_hidden()
        self.page.click('.work-tabs button[data-side="starred"]')
        expect(self.page.locator('[data-pane="starred"]')).to_be_visible()

    def test_someone_new_gets_a_home_space(self):
        dan = get_user_model().objects.create_user('dan', password='pw', first_name='Dan', last_name='Brown')
        self.log_in(dan)
        self.go('/')
        self.see('Dan Brown')
        self.see('your home space')
        org = Table.objects.get(app__blueprint='departments', key='departments')
        self.assertIsNotNone(self.record(org, 'Dan Brown'))

    def test_edit_my_home_space_with_the_slash_menu(self):
        self.log_in(self.alice)
        self.go('/')
        self.page.click('a.btn:has-text("Edit page")')
        self.settle()
        self.editor_at_top()
        self.slash('heading 1')
        self.page.keyboard.type('Alice at work')
        self.page.keyboard.press('Enter')
        self.slash('bullet')
        self.page.keyboard.type('Finish the bench')
        self.page.keyboard.press('Enter')
        self.page.keyboard.type('Order fuses')
        self.page.keyboard.press('Enter')
        self.page.keyboard.press('Enter')
        self.slash('info panel')
        self.page.keyboard.type('Back on Monday')
        # a grid with an app in one cell and a block in the other
        self.page.evaluate("""() => { const e = document.getElementById('editor'); const p = document.createElement('p');
            p.innerHTML = '<br>'; e.querySelector('.panel').after(p); const r = document.createRange(); r.setStart(p, 0);
            r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
        grids = self.page.locator('#editor .grid-block[data-cols="2"]')
        before = grids.count()   # the home page starts with one
        self.slash('grid 2')
        expect(grids).to_have_count(before + 1)
        expect(self.page.locator('#editor .panel + .grid-block .grid-cell')).to_have_count(2)
        self.slash('tasks', pick='Tasks')
        self.page.evaluate("""() => { const c = document.querySelectorAll('#editor .panel + .grid-block .grid-cell')[1].querySelector('p');
            const r = document.createRange(); r.setStart(c, 0); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
        self.slash('notifications', pick='Notifications')
        # a live view and a record
        self.page.keyboard.press('End')
        self.slash('view', pick='View…')
        self.page.fill('.o-modal input[type=search]', 'tasks › list')
        self.page.locator('.o-modal .picker-list a').first.click()
        self.slash('record', pick='Record…')
        self.page.fill('.o-modal input[type=search]', 'calibrate')
        self.page.locator('.o-modal .picker-list a', has_text='Calibrate').click()
        self.page.click('.o-modal button[data-do="link"]')
        self.page.click('.edit-foot button.primary')
        self.settle()
        self.see('The page is saved')
        body = Layout.objects.get(record__data__person=self.alice.pk).body
        for part in ('<h1>Alice at work</h1>', '<li>Finish the bench</li>', 'class="panel info"', 'data-cols="2"',
                     'data-app="tasks"', 'data-block="notifications"', 'class="embed-view"', 'class="record-ref"'):
            self.assertIn(part, body)
        self.assertLess(body.index('Alice at work'), body.index('data-cols="2"'))   # in the order typed
        # how it shows
        expect(self.page.locator('.page-body h1')).to_have_text('Alice at work')
        expect(self.page.locator('.page-body .grid-cell a.app-card.live')).to_contain_text('Tasks')
        expect(self.page.locator('.page-body .embed-view.live')).to_be_visible()
        expect(self.page.locator('.page-body a.record-ref')).to_contain_text('Calibrate')
        self.page.click('.page-body .grid-cell a.app-card.live')
        self.settle()
        self.assertIn('/a/tasks/', self.page.url)
        # start over
        self.go('/')
        self.page.click('a.btn:has-text("Edit page")')
        self.page.click('button[name=reset]')
        self.settle()
        self.assertFalse(Layout.objects.filter(record__data__person=self.alice.pk).exists())
        self.see('My work')

    def test_the_slash_menu_by_keyboard_and_the_add_button(self):
        self.go('/')
        self.page.click('a.btn:has-text("Edit page")')
        self.editor_at_top()
        self.page.keyboard.type('/head')
        items = self.page.locator('.slash-menu .slash-item')
        expect(items.first).to_have_class(re.compile('on'))
        self.page.keyboard.press('ArrowDown')
        expect(items.nth(1)).to_have_class(re.compile('on'))
        self.page.keyboard.press('Escape')
        expect(self.page.locator('.slash-menu')).to_be_hidden()
        expect(self.page.locator('#editor')).to_contain_text('/head')       # what was typed stays
        self.page.keyboard.type('zzzzz')
        # the ＋ Add button opens it too, with its own filter
        self.page.click('[data-action="slash"]')
        expect(self.page.locator('.slash-menu')).to_be_visible()
        self.page.keyboard.type('divider')
        expect(items).to_have_count(1)
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#editor hr')).to_have_count(1)
        # bold, by the toolbar
        self.editor_at_top()
        self.page.keyboard.type('plain ')
        self.page.click('button[data-cmd="bold"]')
        self.page.keyboard.type('strong')
        expect(self.page.locator('#editor b, #editor strong')).to_contain_text('strong')

    def test_a_space_page_and_a_new_space_in_the_tree(self):
        projects = Table.objects.get(app__blueprint='projects', key='projects')
        programme = self.record(projects, 'Product development')
        self.go('/apps/')
        self.page.click('.space-row:has-text("Product development")')
        self.settle()
        expect(self.page.locator('h1')).to_contain_text('Product development')
        self.see('Linked to this space')
        self.see('Build the burn-in rack')                     # a task of a project under it
        expect(self.page.locator('.space-card')).to_contain_text('Burn-in test bench')
        # a new project under the programme
        self.go(f'/a/{projects.app.slug}/{projects.slug}/new/')
        self.page.fill(f'#f_{projects.fields.get(key="name").pk}', 'Thermal chamber')
        box = self.page.locator(f'.link-input[data-field="{projects.fields.get(key="parent").pk}"]')
        box.locator('button').click()
        self.page.locator('.o-modal .picker-list a', has_text='Product development').click()
        self.page.click('#record-form button.primary')
        self.settle()
        self.go(f'/s/{programme.pk}/')
        expect(self.page.locator('.space-cards')).to_contain_text('Thermal chamber')
        # the launcher's filter finds spaces
        self.page.click('#launcher > summary')
        self.page.fill('.launcher-filter', 'thermal')
        expect(self.page.locator('.launcher-space:visible')).to_have_count(0)   # only the tops of the trees are there
        self.page.fill('.launcher-filter', 'company')
        expect(self.page.locator('.launcher-space:visible')).to_have_count(1)

    def test_an_app_home_page(self):
        app = App.objects.get(blueprint='tasks')
        self.go(f'/a/{app.slug}/')
        expect(self.page.locator('.app-tabs a.on')).to_contain_text('Home')
        self.see('Tables of this app')
        self.page.click('.app-bar details summary')
        self.page.click('a:has-text("Edit the home page")')
        self.settle()
        self.editor_at_top()
        self.slash('heading 2')
        self.page.keyboard.type('Team board')
        self.page.click('.edit-foot button.primary')
        self.settle()
        self.see(f'The home page of {app.name} is saved')
        expect(self.page.locator('.page-body h2')).to_have_text('Team board')
        # the tabs: a table, and back home
        self.page.locator('.app-tabs a').nth(1).click()   # the first table
        self.settle()
        expect(self.page.locator('.app-tabs a.on')).not_to_contain_text('Home')
        self.page.click('.app-tabs a:has-text("Home")')
        self.see('Team board')

    def test_only_the_people_of_a_space_change_its_page(self):
        App.objects.filter(blueprint='departments').update(default_role='viewer')
        org = Table.objects.get(app__blueprint='departments', key='departments')
        warehouse = self.record(org, 'Warehouse')
        self.log_in(self.bob)
        self.go(f'/s/{warehouse.pk}/')
        expect(self.page.locator('a.btn:has-text("Edit page")')).to_have_count(0)
        self.assertEqual(self.page.goto(self.live_server_url + f'/s/{warehouse.pk}/edit/').status, 403)


# =========================================================================================
# Documentation pages
# =========================================================================================

class DocsTests(BrowserTestCase):
    templates = ['departments', 'tasks']

    def engineering(self):
        return self.record(Table.objects.get(app__blueprint='departments', key='departments'), 'Engineering')

    def write(self, title, template='Blank page', text='Hello'):
        self.go(f'/x/docs/s/{self.engineering().pk}/')
        self.page.click(f'.template-pick:has-text("{template}")')
        self.page.fill('.title-input', title)
        self.page.click('#editor')
        self.page.keyboard.press('Control+End')
        self.page.keyboard.type(text)
        self.page.click('.edit-foot button.primary')
        self.settle()
        self.see(f'"{title}" is saved')
        from extensions.docs.models import Page
        return Page.objects.get(title=title)

    def test_write_change_restore_and_delete_a_page(self):
        from extensions.docs.models import Page
        self.go('/x/docs/')
        self.page.click('.page-tree .tree-row:has-text("Engineering")')
        self.settle()
        page = self.write('Bench safety', template='How-to', text='Wear glasses.')
        self.assertIn('Wear glasses.', page.body)
        self.see('Bench safety')
        # change it
        self.page.click('a.btn:has-text("Edit")')
        self.page.click('#editor')
        self.page.keyboard.press('Control+End')
        self.page.keyboard.type(' And gloves.')
        self.page.fill('input[name=note]', 'gloves')
        self.page.click('.edit-foot button.primary')
        self.settle()
        page.refresh_from_db()
        self.assertEqual(page.version, 2)
        self.assertIn('gloves', page.body)
        # back to version 1
        self.page.click('a:has-text("Version 1")')
        self.settle()
        self.see("You're looking at version 1")
        self.page.click('button:has-text("Restore this version")')
        self.settle()
        page.refresh_from_db()
        self.assertEqual(page.version, 3)
        self.assertNotIn('gloves', page.body)
        # comment, pin, then delete
        self.page.fill('.comment-form textarea', 'Thanks!')
        self.page.click('.comment-form button')
        self.settle()
        self.see('Thanks!')
        self.page.click('.page-actions .star')
        self.settle()
        self.go('/')
        expect(self.page.locator('.page-body')).to_contain_text('Bench safety')      # the Pinned pages block
        self.go(page.get_absolute_url())
        self.page.click('.page-actions details summary')
        self.page.click('button:has-text("Delete")')
        self.settle()
        self.assertFalse(Page.objects.filter(pk=page.pk).exists())

    def test_pages_under_pages_and_moving_them(self):
        handbook = self.write('Handbook')
        self.page.click('a.btn:has-text("Page under it")')
        self.page.fill('.title-input', 'Onboarding')
        self.page.click('.edit-foot button.primary')
        self.settle()
        from extensions.docs.models import Page
        child = Page.objects.get(title='Onboarding')
        self.assertEqual(child.parent, handbook)
        expect(self.page.locator('.crumbs')).to_contain_text('Handbook')
        # move it to the top
        self.page.click('.page-actions details summary')
        with self.page.expect_navigation():
            self.page.locator('.page-actions select[name=parent]').select_option(index=1)
        self.settle()
        child.refresh_from_db()
        self.assertIsNone(child.parent)
        # a page can't go under its own child
        self.go(child.get_absolute_url())
        self.page.click('.page-actions details summary')
        self.page.click('a.btn:has-text("Page under it")') if False else None
        self.go(handbook.get_absolute_url())
        self.page.click('.page-actions details summary')
        options = self.page.locator('.page-actions select[name=parent] option').all_inner_texts()
        self.assertNotIn('Handbook', options)

    def test_live_data_on_a_page(self):
        tasks = Table.objects.get(app__blueprint='tasks', key='tasks')
        self.go(f'/x/docs/new/' if False else f'/x/docs/s/{self.engineering().pk}/new/')
        self.page.fill('.title-input', 'Status')
        self.page.click('#editor')
        self.page.keyboard.type('Now: ')
        self.page.keyboard.type('@')
        self.page.fill('.o-modal input[type=search]', 'calibrate')
        self.page.locator('.o-modal .picker-list a', has_text='Calibrate').click()
        status = tasks.fields.get(key='status')
        self.page.locator(f'.o-modal button[data-value="{status.pk}"]').click()          # one live value
        self.page.keyboard.type(' ')
        self.page.click('[data-action="slash"]')
        self.page.keyboard.type('calculation')
        self.page.keyboard.press('Enter')
        self.page.fill('.calc-dialog textarea', '6 * 7')
        expect(self.page.locator('.calc-out')).to_have_text('42')
        self.page.click('.calc-dialog button[data-do="save"]')
        self.page.click('.edit-foot button.primary')
        self.settle()
        task = self.record(tasks, 'Calibrate the electronic load')
        expect(self.page.locator('.page-body a.record-value')).to_have_text(self.text(task, status))
        expect(self.page.locator('.page-body .calc-result')).to_have_text('42')
        # the value is live
        service.update_record(task, {status.pk: 'Done'}, user=self.admin)
        self.page.reload()
        expect(self.page.locator('.page-body a.record-value')).to_have_text('Done')
        # and the record knows the page mentions it
        self.go(task.get_absolute_url())
        self.see('Mentioned in 1 page')

    def test_a_picture_on_a_page(self):
        from io import BytesIO

        from PIL import Image
        path = Path(tempfile.mkdtemp()) / 'bench.png'
        buf = BytesIO()
        Image.new('RGB', (60, 40), 'teal').save(buf, 'PNG')
        path.write_bytes(buf.getvalue())
        self.go(f'/x/docs/s/{self.engineering().pk}/new/')
        self.page.fill('.title-input', 'Photos')
        self.page.click('#editor')
        self.page.set_input_files('#image-file', str(path))
        expect(self.page.locator('#editor img')).to_have_count(1)
        self.page.click('.edit-foot button.primary')
        self.settle()
        src = self.page.locator('.page-body img').get_attribute('src')
        self.assertEqual(self.page.request.get(self.live_server_url + src).status, 200)


# =========================================================================================
# Access tags
# =========================================================================================

class AccessTests(BrowserTestCase):
    templates = ['departments', 'projects']

    def setUp(self):
        super().setUp()
        App.objects.update(default_role='editor')
        self.tasks = Table.objects.get(app__blueprint='tasks', key='tasks')
        self.task = self.record(self.tasks, 'Write the test procedure')
        self.grid = self.tasks.views.filter(type='grid').first()

    def make_tag(self):
        self.go('/admin/tags/')
        self.page.fill('#name', 'Payroll')
        self.page.fill('#description', 'Pay and contracts')
        self.page.click('form button.primary:has-text("Make the tag")')
        self.settle()
        self.see('The tag Payroll is made')
        tag = Tag.objects.get(name='Payroll')
        self.page.select_option('form:has(input[value=grant]) select[name=user]', str(self.alice.pk))
        self.page.click('button:has-text("Give the tag")')
        self.settle()
        self.assertTrue(tag.members.filter(pk=self.alice.pk).exists())
        return tag

    def test_a_tagged_record_is_hidden(self):
        tag = self.make_tag()
        self.log_in(self.alice)
        self.go(self.task.get_absolute_url())
        self.page.check(f'input[name=tags][value="{tag.pk}"]')
        self.page.click('form:has(input[name=tags]) button:has-text("Save")')
        self.settle()
        self.see('The access tags are saved')
        expect(self.page.locator('.record-head .tag-chip')).to_contain_text('Payroll')
        self.task.refresh_from_db()
        self.assertEqual(self.task.access, [tag.pk])
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'pw')
        for who in (self.bob, root):                 # an administrator who doesn't hold the tag too
            self.log_in(who)
            self.go(self.grid.get_absolute_url())
            self.dont_see('Write the test procedure')
            self.go('/search/?q=test+procedure')
            self.dont_see('Write the test procedure')
            self.assertEqual(self.page.goto(self.live_server_url + self.task.get_absolute_url()).status, 404)

    def test_tags_follow_the_tree(self):
        tag = self.make_tag()
        projects = Table.objects.get(app__blueprint='projects', key='projects')
        programme = self.record(projects, 'Product development')
        access.set_tags(programme, [tag.pk], self.admin)
        self.log_in(self.bob)
        self.go('/apps/')
        self.dont_see('Product development')
        self.go(self.grid.get_absolute_url())
        self.dont_see('Build the burn-in rack')       # a task of a project under the programme
        self.see('Count the shelves')                 # a task of another project

    def test_assigning_someone_who_cant_see_it(self):
        tag = self.make_tag()
        access.set_tags(self.task, [tag.pk], self.alice)
        assignee = self.tasks.fields.get(key='assignee')
        self.log_in(self.alice)
        self.go(self.task.get_absolute_url())
        self.accept_dialogs = False                    # no: nothing changes
        self.cell(self.task, assignee).click()
        self.page.locator('.editor .option', has_text='Bob Jansen').click()
        self.toast("can't see")
        self.assertIn('Share it with them?', self.dialogs[-1])
        self.assertNotEqual(self.text(self.task, assignee), 'Bob Jansen')
        self.accept_dialogs = True                     # yes: shared, this one record
        self.cell(self.task, assignee).click()
        self.page.locator('.editor .option', has_text='Bob Jansen').click()
        self.eventually(lambda: self.text(self.task, assignee) == 'Bob Jansen')
        self.assertTrue(AccessGrant.objects.filter(record=self.task, user=self.bob).exists())
        self.log_in(self.bob)
        self.go(self.task.get_absolute_url())
        expect(self.page.locator('#record-title')).to_have_text('Write the test procedure')
        self.see('Shared with')
        # the tag's owner was told
        self.log_in(self.admin)
        self.go('/notifications/')
        self.see('shared')

    def test_only_owners_give_a_tag(self):
        tag = self.make_tag()
        self.log_in(self.alice)
        self.go(f'/admin/tags/{tag.pk}/')
        self.see('Only its owners change who holds it')
        expect(self.page.locator('button:has-text("Give the tag")')).to_have_count(0)


# =========================================================================================
# Administration, the AI assistant and the tutorials
# =========================================================================================

class AdminTests(BrowserTestCase):
    def test_install_a_template_and_what_it_needs(self):
        self.go('/admin/templates/')
        self.page.check('input[name=templates][value=orders]')
        self.page.click('button:has-text("Install the ticked templates")')
        self.settle()
        self.see('needs these')
        self.see('Vendors')
        self.assertFalse(App.objects.filter(blueprint='orders').exists())
        self.page.click('button:has-text("Install them all")')
        self.settle()
        self.see('Installed')
        for key in ('orders', 'vendors', 'parts'):
            self.assertTrue(App.objects.filter(blueprint=key).exists(), key)
        self.go('/apps/')
        self.see('Orders')

    def test_users_and_passwords(self):
        self.go('/accounts/users/new/')
        self.page.fill('#id_username', 'erin')
        self.page.fill('#id_first_name', 'Erin')
        self.page.fill('#id_password1', 'a long pass phrase 42')
        self.page.fill('#id_password2', 'a long pass phrase 42')
        self.page.click('form button.primary')
        self.settle()
        erin = get_user_model().objects.get(username='erin')
        self.assertTrue(erin.check_password('a long pass phrase 42'))
        self.go(f'/accounts/users/{erin.pk}/password/')
        self.page.fill('#id_password1', 'another pass phrase 7')
        self.page.fill('#id_password2', 'another pass phrase 7')
        self.page.click('form button.primary')
        self.settle()
        erin.refresh_from_db()
        self.assertTrue(erin.check_password('another pass phrase 7'))
        # she logs in with it, through the login page
        self.context.close()
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.go('/accounts/login/')
        self.page.fill('#id_username', 'erin')
        self.page.fill('#id_password', 'another pass phrase 7')
        self.page.click('button.primary')
        self.settle()
        self.assertEqual(self.page.url, self.live_server_url + '/')
        expect(self.page.locator('.me-name')).to_contain_text('Erin')

    def test_teams(self):
        self.go('/accounts/teams/new/')
        self.page.fill('#id_name', 'Warehouse crew')
        self.page.check(f'input[name=members][value="{self.bob.pk}"]')
        self.page.click('form button.primary')
        self.settle()
        self.see('Warehouse crew')
        self.assertTrue(self.bob.groups.filter(name='Warehouse crew').exists())

    def test_extensions_say_what_they_need_and_what_uses_them(self):
        self.go('/admin/extensions/')
        self.see('Documentation')
        self.go('/admin/extensions/docs/')
        self.dont_see('Traceback')
        self.go('/admin/trees/')
        self.dont_see('Traceback')


class AssistantTests(BrowserTestCase):
    def test_ask_paste_check_and_make(self):
        import json
        self.go('/x/assistant/')
        self.page.fill('#request', 'An app for our suppliers')
        self.page.click('button:has-text("Write the prompt")')
        self.settle()
        expect(self.page.locator('#prompt')).to_contain_text('An app for our suppliers')
        answer = {'osmia': 1, 'summary': 'Suppliers', 'changes': [{'do': 'create_app', 'name': 'Suppliers', 'tables': [
            {'name': 'Suppliers', 'fields': [{'name': 'Name', 'type': 'text'},
                                             {'name': 'Status', 'type': 'select', 'choices': ['Active', 'Paused']}],
             'records': [{'Name': 'Acme', 'Status': 'Active'}]}]}]}
        self.page.fill('textarea[name=answer]', 'Here it is:\n```json\n' + json.dumps(answer) + '\n```')
        self.page.click('button:has-text("Check the answer")')
        self.settle()
        self.see('Make 1 change')
        self.assertFalse(App.objects.filter(name='Suppliers').exists())
        self.page.click('button:has-text("Make 1 change")')
        self.settle()
        self.see('Done')
        app = App.objects.get(name='Suppliers')
        self.assertEqual(Record.objects.filter(table__app=app).count(), 1)


class TutorialTests(BrowserTestCase):
    def test_tutorials(self):
        self.go('/apps/')
        self.page.click('.app-card:has-text("Tutorials")')
        self.settle()
        self.see('A tour of Osmia')
        self.page.fill('.content input[name=q]', 'access tags')   # the tutorials' own search, not the top bar's
        self.page.press('.content input[name=q]', 'Enter')
        self.settle()
        self.page.click('a:has-text("Access tags: who sees what")')
        self.settle()
        self.see('holding every one')
