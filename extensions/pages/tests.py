from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core import blueprints, space as spaces
from core.models import SpaceMember, View

from .models import Page, PagePin, PageVersion
from .sanitize import clean


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
        blueprints.install_many(['tasks'], user=cls.admin, sample=True)
        cls.space = spaces.create_space('Engineering', cls.ann, key='ENG', visibility='internal')

    def setUp(self):
        self.client.force_login(self.ann)

    def write(self, title='How we test', body='<p>Hello</p>', parent=None, template='blank'):
        url = reverse('pages:new', args=['ENG']) + f'?template={template}' + (f'&parent={parent.pk}' if parent else '')
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
        self.client.post(reverse('pages:edit', args=[page.pk]), {'title': 'How we test', 'body': '<p>New text</p>', 'note': 'shorter'})
        page.refresh_from_db()
        self.assertEqual(page.version, 2)
        self.assertEqual(PageVersion.objects.filter(page=page).count(), 2)
        self.client.post(reverse('pages:restore', args=[page.pk, 1]))
        page.refresh_from_db()
        self.assertIn('Plug in', page.body)
        self.assertEqual(page.version, 3)

    def test_templates_and_tree(self):
        parent = self.write('Team handbook', template='howto')
        child = self.write('Meeting 1', template='meeting', parent=parent)
        self.assertEqual(child.parent, parent)
        response = self.client.get(child.get_absolute_url())
        self.assertContains(response, 'Team handbook')  # breadcrumbs and tree
        self.assertContains(self.client.get(reverse('pages:new', args=['ENG']) + '?template=meeting'), 'Action items')
        self.client.post(reverse('pages:move', args=[parent.pk]), {'parent': child.pk})  # not under itself
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
        self.client.force_login(self.ben)  # internal space: ben can read and comment, not write
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse('pages:edit', args=[page.pk])).status_code, 403)
        self.client.post(reverse('pages:comment', args=[page.pk]), {'text': 'Nice'})
        self.assertEqual(page.comments.count(), 1)
        self.assertEqual(self.client.post(reverse('pages:delete', args=[page.pk])).status_code, 403)
        SpaceMember.objects.create(space=self.space, user=self.ben, role='editor')
        self.client.force_login(get_user_model().objects.get(pk=self.ben.pk))
        self.assertEqual(self.client.get(reverse('pages:edit', args=[page.pk])).status_code, 200)
        self.space.visibility = 'private'
        self.space.save()
        self.client.force_login(get_user_model().objects.get(username='admin'))
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 200)  # admins see every company space

    def test_pin_search_and_space_overview(self):
        page = self.write('Release checklist')
        self.client.post(reverse('pages:pin', args=[page.pk]))
        self.assertTrue(PagePin.objects.filter(user=self.ann, page=page).exists())
        self.assertContains(self.client.get('/'), 'Release checklist')        # pinned on the home page
        self.assertContains(self.client.get('/search/?q=checklist'), 'Release checklist')
        self.assertContains(self.client.get(self.space.get_absolute_url()), 'Release checklist')
        self.assertContains(self.client.get(reverse('pages:space', args=['ENG']) + '?label=how-to'), 'Release checklist')

    def test_upload_a_picture(self):
        from io import BytesIO

        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (40, 30), 'red').save(buf, 'PNG')
        response = self.client.post(reverse('pages:upload', args=['ENG']), {'file': SimpleUploadedFile('a.png', buf.getvalue(), 'image/png')})
        self.assertEqual(response.status_code, 200, response.content)
        url = response.json()['url']
        page = self.write(body=f'<p><img src="{url}"></p>')
        self.assertIn(url, page.body)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_personal_pages(self):
        self.client.get('/')
        mine = spaces.personal_space(self.ann)
        self.assertContains(self.client.get('/'), 'My pages')
        self.assertEqual(self.client.get(reverse('pages:space', args=[mine.key])).status_code, 200)
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(reverse('pages:space', args=[mine.key])).status_code, 403)
