from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core import blueprints


class Command(BaseCommand):
    help = 'Install app templates (all, or the ones named), e.g. "install_templates tasks orders --sample".'

    def add_arguments(self, parser):
        parser.add_argument('keys', nargs='*', help='Template keys; none: all of them.')
        parser.add_argument('--sample', action='store_true', help='With their sample records.')

    def handle(self, *args, keys=(), sample=False, **options):
        catalog = blueprints.available()
        unknown = [k for k in keys if k not in catalog]
        if unknown:
            raise CommandError(f'No template called {", ".join(unknown)}. There are: {", ".join(catalog)}')
        admin = get_user_model().objects.filter(is_superuser=True).first()
        apps = blueprints.install_many(list(keys) or list(catalog), user=admin, sample=sample)
        self.stdout.write('Installed ' + (', '.join(a.name for a in apps) or 'nothing (they were installed already)') + '.')
