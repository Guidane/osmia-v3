"""What the AI assistant adds to Osmia (see core.extensions)."""
from django.urls import reverse


def nav(request, space):
    return [('✨', 'AI assistant', reverse('assistant:index') + f'?space={space.key}')]


def register(registry):
    registry.page('AI', 'assistant:index', '✨')
    registry.space_nav(nav)
