"""What the AI assistant adds to Osmia (see core.extensions)."""


def register(registry):
    registry.app('AI assistant', 'assistant:index', '✨', 'Describe a change; any AI chat writes it, Osmia checks it.',
                 color='#a855f7', extension='assistant', group='Workspace')
