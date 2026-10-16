import re

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from .content import BY_SLUG, CATEGORIES, TUTORIALS


class TutorialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        cls.ann = User.objects.create_user('ann', password='pw')

    def test_every_tutorial_opens_for_an_administrator(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('tutorials:index'))
        self.assertEqual(response.status_code, 200)
        for t in TUTORIALS:
            self.assertContains(response, t.title.replace("'", '&#x27;'))
            page = self.client.get(reverse('tutorials:detail', args=[t.slug]))
            self.assertEqual(page.status_code, 200, t.slug)
            if t.gif:
                self.assertContains(page, f'tutorials/{t.gif}.gif')

    def test_administrators_tutorials_are_for_administrators(self):
        self.client.force_login(self.ann)
        admin_only = [t for t in TUTORIALS if t.audience == 'admins']
        self.assertTrue(admin_only)
        response = self.client.get(reverse('tutorials:index'))
        self.assertNotContains(response, admin_only[0].title)
        self.assertEqual(self.client.get(reverse('tutorials:detail', args=[admin_only[0].slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse('tutorials:detail', args=['tour'])).status_code, 200)

    def test_search(self):
        self.client.force_login(self.ann)
        response = self.client.get(reverse('tutorials:index') + '?q=gantt')
        self.assertContains(response, 'Gantt charts')
        self.assertNotContains(response, 'Your account and password')

    def test_content_is_complete(self):
        categories = {k for k, _ in CATEGORIES}
        for t in TUTORIALS:
            self.assertIn(t.category, categories, t.slug)
            if t.gif:
                self.assertTrue(finders.find(f'tutorials/{t.gif}.gif'), f'{t.gif}.gif is missing: run make_tutorial_gifs')
            if t.try_url:
                try:
                    reverse(t.try_url)
                except NoReverseMatch:
                    self.fail(f'{t.slug}: no page called {t.try_url}')
            for slug in t.related:
                self.assertIn(slug, BY_SLUG, f'{t.slug} refers to {slug}')
            for slug in re.findall(r'/tutorials/([\w-]+)/', ' '.join(t.steps)):
                self.assertIn(slug, BY_SLUG, f'{t.slug} links to {slug}')

    def test_launcher_link(self):
        self.client.force_login(self.ann)
        self.assertContains(self.client.get(reverse('core:launcher')), reverse('tutorials:index'))
