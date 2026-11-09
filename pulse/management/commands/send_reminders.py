"""
Sends reminders that are due (3 days and 1 day before a deadline or event).

Run it every few minutes, e.g. with cron:
    */10 * * * *  cd /path/to/EUnited && .venv/bin/python manage.py send_reminders
"""
from django.core.management.base import BaseCommand

from pulse.services import send_due_reminders


class Command(BaseCommand):
    help = "Sends due email reminders and releases due in-app notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url", default="http://localhost:8000",
            help="Address of the site, used for links in emails.",
        )

    def handle(self, *args, base_url, **options):
        sent = send_due_reminders(base_url=base_url)
        self.stdout.write(self.style.SUCCESS(f"{sent} reminder email(s) sent."))
