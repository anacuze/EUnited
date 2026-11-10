"""
Imports new posts from the active sources (sum.ba, unical.it, eupeace.eu) as drafts.
An admin then approves them in the Review queue.

    python manage.py import_posts                  # all active sources
    python manage.py import_posts --source UNICAL  # only sources whose name contains "UNICAL"
    python manage.py import_posts --dry-run        # show what would be imported, save nothing

Run it about once an hour on the server, e.g. with cron:
    0 * * * *  cd /path/to/EUnited && .venv/bin/python manage.py import_posts
"""
from django.core.management.base import BaseCommand, CommandError

from pulse.importer import import_all
from pulse.models import Source


class Command(BaseCommand):
    help = "Imports new posts from the active sources into the review queue."

    def add_arguments(self, parser):
        parser.add_argument("--source", help="Only sources whose name contains this text.")
        parser.add_argument("--limit", type=int, help="Most posts to import from each source in one run.")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be imported, save nothing.")

    def handle(self, *args, source, limit, dry_run, **options):
        sources = Source.objects.filter(active=True).select_related("university")
        if source:
            sources = sources.filter(name__icontains=source)
            if not sources:
                raise CommandError(f'No active source has "{source}" in its name.')
        elif not sources:
            self.stdout.write("There are no active sources. Add one in the admin panel (Sources).")
            return

        total = 0
        for result in import_all(sources, limit=limit, dry_run=dry_run):
            total += len(result.created)
            line = f"{result.source.name}: {len(result.created)} new post(s)"
            self.stdout.write(self.style.ERROR(line) if result.failed else line)
            if dry_run or options["verbosity"] > 1:
                for post in result.created:
                    self.stdout.write(f"  + {post.title}  <{post.source_url}>")
            for error in result.errors:
                self.stdout.write(self.style.WARNING(f"  ! {error}"))

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {total} post(s) would be imported."))
        else:
            self.stdout.write(self.style.SUCCESS(f"{total} post(s) imported into the review queue."))
