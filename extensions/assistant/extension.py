"""What the AI prompt generator adds to Osmia (see core.extensions)."""


def register(registry):
    registry.app('AI prompt generator', 'assistant:index', '✨', 'Describe a change; any AI chat writes it, Osmia checks it.',
                 color='#a855f7', extension='assistant', group='Workspace')
