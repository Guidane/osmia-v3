from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'
    verbose_name = 'Osmia'

    def ready(self):
        from . import automation, fieldtypes, viewtypes  # noqa: F401  (register the built-in types and actions)
        from .canvas.blocks import register_core_blocks
        register_core_blocks()
