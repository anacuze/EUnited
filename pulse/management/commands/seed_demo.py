"""
Fills the database with sample data so the Pulse isn't empty during development.

    python manage.py seed_demo          # add sample data
    python manage.py seed_demo --reset  # delete all posts first, then add sample data

All sample posts are made up and marked "(sample)" – never run this on the live site.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Club, University, User
from pulse.models import Post, Source, Tag

PASSWORD = "eunited-dev-123"

UNIVERSITIES = [
    ("SUM", "University of Mostar", "sum.ba", "https://www.sum.ba"),
    ("UNICAL", "University of Calabria", "unical.it", "https://www.unical.it"),
    ("EUPeace", "EUPeace alliance", "", "https://eupeace.eu"),
]

SOURCES = [
    ("SUM news", "https://www.sum.ba", "SUM"),
    ("UNICAL news", "https://www.unical.it", "UNICAL"),
    ("EUPeace news", "https://eupeace.eu", "EUPeace"),
]

TAGS = ["Erasmus", "Scholarship", "IT", "Law", "Sport", "Culture", "Research", "Career", "Peace"]


class Command(BaseCommand):
    help = "Adds sample universities, users, clubs, tags and posts for development."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete all posts before seeding.")

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        if reset:
            Post.objects.all().delete()

        unis = {}
        for short, name, domain, web in UNIVERSITIES:
            unis[short], _ = University.objects.update_or_create(
                short_name=short, defaults={"name": name, "email_domain": domain, "website": web}
            )

        sources = {}
        for name, url, uni in SOURCES:
            sources[uni], _ = Source.objects.get_or_create(
                url=url, defaults={"name": name, "university": unis[uni]}
            )

        tags = {}
        for name in TAGS:
            tags[name], _ = Tag.objects.get_or_create(slug=slugify(name), defaults={"name": name})

        admin = self._user("admin@sum.ba", "Ana", "Admin", User.Role.SUPERADMIN, unis["SUM"])
        editor = self._user("editor@unical.it", "Elena", "Editor", User.Role.EDITOR, unis["UNICAL"])
        self._user("moderator@sum.ba", "Marko", "Moderator", User.Role.MODERATOR, unis["SUM"])
        club_user = self._user("switch@sum.ba", "SWITCH", "Club", User.Role.CLUB, unis["SUM"])
        self._user("student@unical.it", "Luca", "Student", User.Role.STUDENT, unis["UNICAL"])

        switch, _ = Club.objects.get_or_create(
            name="SWITCH",
            defaults={
                "university": unis["SUM"],
                "contact_email": "switch@sum.ba",
                "description": "Student programming club, around 40 members.",
                "verified": True,
            },
        )
        switch.members.add(club_user)

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        d = lambda days, hour=12: (now + timedelta(days=days)).replace(hour=hour)  # noqa: E731

        samples = [
            # (type, title, summary, uni, tags, extra fields, status)
            ("mobility", "Erasmus+ study exchange 2026/27 – second call (sample)",
             "Spend a semester at a partner university. Open to 2nd year students and above.",
             "SUM", ["Erasmus"], {"deadline": d(2), "source": sources["SUM"]}, "published"),
            ("mobility", "EUPeace short-term mobility grants (sample)",
             "Grants for one-week visits to any EUPeace partner university.",
             "EUPeace", ["Erasmus", "Peace"], {"deadline": d(5)}, "published"),
            ("scientific", "Call for papers: Digital Peacebuilding conference (sample)",
             "Submit an abstract on technology for peace and inclusion. Students welcome.",
             "UNICAL", ["Research", "Peace"],
             {"deadline": d(6), "event_start": d(40, 9), "event_end": d(41, 17), "location": "UNICAL, Rende"},
             "published"),
            ("event", "SWITCH coding night: build your first web app (sample)",
             "Bring a laptop – we'll build a small Django app together. Pizza included.",
             "SUM", ["IT"], {"event_start": d(1, 18), "event_end": d(1, 22), "location": "FPMOZ, room 12",
                             "club": switch, "author": club_user}, "published"),
            ("event", "International students welcome evening (sample)",
             "Meet exchange students and local buddies. Music, food and games.",
             "UNICAL", ["Culture"], {"event_start": d(9, 19), "location": "UNICAL campus, Piazza Vermicelli"},
             "published"),
            ("mobility", "Summer school on European law (sample)",
             "Two weeks in July, fully funded for EUPeace students.",
             "UNICAL", ["Law", "Scholarship"], {"deadline": d(21)}, "published"),
            ("news", "New study rooms open in the central library (sample)",
             "Three new rooms can be booked online, open until 22:00 on weekdays.",
             "SUM", [], {"source": sources["SUM"]}, "published"),
            ("news", "EUPeace launches the Student Challenges results page (sample)",
             "See all funded student projects across the alliance.",
             "EUPeace", ["Peace"], {}, "published"),
            ("blog", "What I learned from my Erasmus in Calabria (sample)",
             "A SUM student on food, friends and finding your way around Rende.",
             "SUM", ["Erasmus", "Culture"], {"body": "Sample blog text.\n\nSecond paragraph.", "author": admin},
             "published"),
            ("event", "Campus basketball tournament (sample)",
             "Sign up your team of three. Finals on Saturday.",
             "SUM", ["Sport"], {"event_start": d(-3, 16), "location": "SUM sports hall"}, "published"),
            ("mobility", "Research internship in Mostar (sample)",
             "Paid internship at a research lab, already closed – shows in the archive.",
             "SUM", ["Research", "Career"], {"deadline": d(-10)}, "published"),
            # Waiting in the review queue
            ("event", "SWITCH hackathon: apps for inclusion (sample)",
             "48-hour hackathon for students from Mostar and Calabria.",
             "SUM", ["IT", "Peace"], {"event_start": d(30, 9), "event_end": d(32, 17), "location": "Online + FPMOZ",
                                       "club": switch, "author": club_user}, "pending"),
            ("news", "UNICAL opens new language centre (sample)",
             "Imported automatically – waiting for an admin to approve.",
             "UNICAL", [], {"source": sources["UNICAL"]}, "draft"),
        ]

        created = 0
        for i, (ptype, title, summary, uni, tag_names, extra, status) in enumerate(samples):
            if Post.objects.filter(title=title).exists():
                continue
            post = Post(
                type=ptype, title=title, summary=summary, university=unis[uni], status=status, **extra
            )
            if status == "published":
                post.published_at = now - timedelta(hours=3 * i + 1)
                post.approved_by = admin
            post.full_clean()
            post.save()
            post.tags.set([tags[t] for t in tag_names])
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Sample data ready – {created} new post(s)."))
        self.stdout.write(f"Log in with any of these (password: {PASSWORD}):")
        for email in ["admin@sum.ba", "editor@unical.it", "moderator@sum.ba", "switch@sum.ba", "student@unical.it"]:
            self.stdout.write(f"  {email}")

    def _user(self, email, first, last, role, uni):
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User(email=email)
            user.set_password(PASSWORD)
        user.first_name, user.last_name, user.role, user.university = first, last, role, uni
        user.save()
        return user
