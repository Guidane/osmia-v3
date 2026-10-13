from django.core.management.base import BaseCommand

from core import automation


class Command(BaseCommand):
    help = 'Run the automations that are due: schedules and dates reached. serve.py does this every minute by itself.'

    def handle(self, *args, **options):
        ran = automation.tick()
        self.stdout.write(f'Ran {ran} automation{"s" if ran != 1 else ""}.')
