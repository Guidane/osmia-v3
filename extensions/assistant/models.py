"""A request to the AI prompt generator: what someone asked, the prompt Osmia made of it, the
answer they pasted back, and what checking or applying it did. Also the record of
what the AI changed (the history of each record says "AI prompt generator" too)."""
from django.conf import settings
from django.db import models
from django.urls import reverse


class Run(models.Model):
    class Status(models.TextChoices):
        WAITING = 'waiting', 'Waiting for the answer'
        PROBLEMS = 'problems', 'The answer has problems'
        QUESTION = 'question', 'The AI asks something'
        READY = 'ready', 'Checked, ready to make'
        DONE = 'done', 'Made'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_runs')
    request = models.TextField()
    scope = models.JSONField(default=dict, blank=True)   # {"space": key, "app": slug, "page": id, "records": bool}
    prompt = models.TextField()
    answer = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.WAITING)
    summary = models.CharField(max_length=300, blank=True)
    problem = models.TextField(blank=True)               # why the answer as a whole can't be used, or the AI's question
    results = models.JSONField(default=list, blank=True)  # [{"n", "do", "text", "url", "error"}]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.request[:80]

    def get_absolute_url(self):
        return reverse('assistant:run', args=[self.pk])
