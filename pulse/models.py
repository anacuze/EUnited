from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Club, University


class Source(models.Model):
    """A website the importer reads news from (sum.ba, unical.it, eupeace.eu)."""

    class Kind(models.TextChoices):
        RSS = "rss", "RSS feed"
        SCRAPE = "scrape", "Scraping"

    name = models.CharField(max_length=200)
    url = models.URLField(unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SCRAPE)
    university = models.ForeignKey(University, on_delete=models.PROTECT, related_name="sources")
    active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PostQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Post.Status.PUBLISHED)

    def _expired_q(self, now):
        """A post is expired when its relevant date is in the past."""
        return (
            Q(type__in=[Post.Type.MOBILITY], deadline__lt=now)
            | Q(type__in=[Post.Type.EVENT, Post.Type.SCIENTIFIC], event_end__lt=now)
            | Q(
                type__in=[Post.Type.EVENT, Post.Type.SCIENTIFIC],
                event_end__isnull=True,
                event_start__lt=now,
            )
        )

    def live(self, now=None):
        """Published posts that are not expired: what the main feed shows."""
        now = now or timezone.now()
        return self.published().exclude(self._expired_q(now))

    def archived(self, now=None):
        """Published posts whose deadline or event has passed, plus manually archived ones."""
        now = now or timezone.now()
        return self.filter(
            (Q(status=Post.Status.PUBLISHED) & self._expired_q(now))
            | Q(status=Post.Status.ARCHIVED)
        )

    def closing_soon(self, days=None, now=None):
        """Live posts with a deadline (or event start) within the next `days` days."""
        now = now or timezone.now()
        days = days or settings.PULSE_CLOSING_SOON_DAYS
        limit = now + timedelta(days=days)
        return (
            self.live(now)
            .filter(Q(deadline__gte=now, deadline__lte=limit) | Q(event_start__gte=now, event_start__lte=limit))
            .distinct()
        )


class Post(models.Model):
    class Type(models.TextChoices):
        MOBILITY = "mobility", "Mobility opportunity"
        EVENT = "event", "Event"
        SCIENTIFIC = "scientific", "Scientific event"
        NEWS = "news", "News"
        BLOG = "blog", "Blog post"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Waiting for approval"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    # Which date fields each type may use
    DEADLINE_TYPES = {Type.MOBILITY, Type.SCIENTIFIC}
    EVENT_TYPES = {Type.EVENT, Type.SCIENTIFIC}

    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=250)
    summary = models.CharField(max_length=500, help_text="One or two sentences shown on the card.")
    body = models.TextField(blank=True)
    image_url = models.URLField(blank=True)
    source_url = models.URLField(
        blank=True, help_text="Original page. Must be unique, which stops duplicate imports."
    )
    language = models.CharField(
        max_length=10, default="en", help_text="Language code of the post, e.g. en, hr, it."
    )

    university = models.ForeignKey(University, on_delete=models.PROTECT, related_name="posts")
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts",
        help_text="Set when the post was imported automatically.",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="posts",
    )
    club = models.ForeignKey(
        Club, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts")

    # Dates
    deadline = models.DateTimeField(
        null=True, blank=True, help_text="Application or submission deadline (mobility, scientific events)."
    )
    event_start = models.DateTimeField(null=True, blank=True)
    event_end = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=250, blank=True, help_text="Place or online link.")

    # Workflow
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approved_posts",
    )
    rejection_reason = models.CharField(max_length=300, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-created_at"]
        permissions = [
            ("publish_post", "Can approve and publish posts"),
            ("hide_post", "Can hide published posts"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_url"],
                condition=~Q(source_url=""),
                name="unique_source_url",
            ),
            models.CheckConstraint(
                condition=Q(deadline__isnull=True) | Q(type__in=["mobility", "scientific"]),
                name="deadline_only_for_mobility_and_scientific",
            ),
            models.CheckConstraint(
                condition=Q(event_start__isnull=True, event_end__isnull=True)
                | Q(type__in=["event", "scientific"]),
                name="event_dates_only_for_events",
            ),
            models.CheckConstraint(
                condition=Q(event_end__isnull=True)
                | Q(event_start__isnull=True)
                | Q(event_end__gte=models.F("event_start")),
                name="event_end_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["deadline"]),
            models.Index(fields=["event_start"]),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("pulse:post_detail", args=[self.pk])

    def clean(self):
        errors = {}
        if self.deadline and self.type not in self.DEADLINE_TYPES:
            errors["deadline"] = "Only mobility opportunities and scientific events have a deadline."
        if (self.event_start or self.event_end) and self.type not in self.EVENT_TYPES:
            errors["event_start"] = "Only events and scientific events have event dates."
        if self.type == self.Type.MOBILITY and not self.deadline:
            errors["deadline"] = "A mobility opportunity needs an application deadline."
        if self.type in self.EVENT_TYPES and not self.event_start:
            errors["event_start"] = "An event needs a start date and time."
        if self.event_start and self.event_end and self.event_end < self.event_start:
            errors["event_end"] = "The event cannot end before it starts."
        if errors:
            raise ValidationError(errors)

    # --- helpers used by templates and reminders --------------------------

    @property
    def key_date(self):
        """The date students care about: the deadline, otherwise the event start."""
        return self.deadline or self.event_start

    @property
    def end_date(self):
        """When the post expires from the feed (None = never)."""
        if self.type == self.Type.MOBILITY:
            return self.deadline
        if self.type in self.EVENT_TYPES:
            return self.event_end or self.event_start
        return None

    @property
    def is_expired(self):
        end = self.end_date
        return bool(end and end < timezone.now()) or self.status == self.Status.ARCHIVED

    @property
    def can_follow(self):
        """Only posts with an upcoming date can be followed with the bell."""
        return bool(self.key_date and self.key_date > timezone.now())

    @property
    def days_left(self):
        if not self.key_date:
            return None
        return (self.key_date - timezone.now()).days

    def publish(self, by_user):
        self.status = self.Status.PUBLISHED
        self.approved_by = by_user
        self.rejection_reason = ""
        if not self.published_at:
            self.published_at = timezone.now()
        self.save()

    def reject(self, by_user, reason=""):
        self.status = self.Status.REJECTED
        self.approved_by = by_user
        self.rejection_reason = reason
        self.save()


class ReviewQueue(Post):
    """Admin-only view of posts that wait for approval (same table as Post)."""

    class Meta:
        proxy = True
        verbose_name = "post waiting for approval"
        verbose_name_plural = "Review queue"


class Like(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="likes")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "post"], name="one_like_per_user")]


class Follow(models.Model):
    """The bell: a student follows a post to get reminders before its deadline or event."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follows")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="follows")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "post"], name="one_follow_per_user")]


class Notification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        IN_APP = "in_app", "In-app"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="notifications")
    days_before = models.PositiveSmallIntegerField()
    channel = models.CharField(max_length=10, choices=Channel.choices)
    send_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-send_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "post", "days_before", "channel"], name="one_reminder_per_slot"
            )
        ]
        indexes = [models.Index(fields=["sent_at", "send_at"])]

    def __str__(self):
        return f"{self.user} – {self.post} ({self.days_before}d, {self.channel})"

    @property
    def message(self):
        what = "Deadline" if self.post.deadline else "Event"
        if self.days_before == 1:
            when = "tomorrow"
        else:
            when = f"in {self.days_before} days"
        return f"{what} {when}: {self.post.title}"
