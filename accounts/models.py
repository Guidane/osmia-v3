from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse


class User(AbstractUser):
    """A person who logs in. Passwords, permissions and groups are Django's own;
    groups are shown as "teams" and can be given access to apps."""
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['first_name', 'last_name', 'username']

    def __str__(self):
        return self.get_full_name() or self.username

    def get_absolute_url(self):
        return reverse('accounts:user_detail', args=[self.pk])

    @property
    def initials(self):
        name = self.get_full_name() or self.username
        return ''.join(part[0] for part in name.split()[:2]).upper() or '?'
