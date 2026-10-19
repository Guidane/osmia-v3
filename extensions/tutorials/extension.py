"""Tutorials: a page per thing Osmia does (see content.py)."""


def register(registry):
    registry.app('Tutorials', 'tutorials:index', '📖', 'How everything in Osmia works, with animations.',
                 color='#0369a1', extension='tutorials', group='Workspace')
