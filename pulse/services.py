"""Business logic for likes, follows (the bell) and reminders, kept out of the views."""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Follow, Like, Notification, Post


def toggle_like(user, post):
    """Like or unlike. Returns True if the post is now liked."""
    like, created = Like.objects.get_or_create(user=user, post=post)
    if not created:
        like.delete()
    return created


@transaction.atomic
def follow(user, post):
    """Follow a post and schedule its reminders. Returns the Follow."""
    follow_obj, _ = Follow.objects.get_or_create(user=user, post=post)
    schedule_reminders(user, post)
    return follow_obj


@transaction.atomic
def unfollow(user, post):
    Follow.objects.filter(user=user, post=post).delete()
    Notification.objects.filter(user=user, post=post, sent_at__isnull=True).delete()


def toggle_follow(user, post):
    """Ring or silence the bell. Returns True if the post is now followed."""
    if Follow.objects.filter(user=user, post=post).exists():
        unfollow(user, post)
        return False
    follow(user, post)
    return True


def schedule_reminders(user, post, now=None):
    """Create one email and one in-app reminder for each reminder day still in the future."""
    now = now or timezone.now()
    key_date = post.key_date
    if not key_date or key_date <= now:
        return []
    created = []
    for days in settings.PULSE_REMINDER_DAYS:
        send_at = key_date - timedelta(days=days)
        if send_at <= now:
            continue
        for channel in (Notification.Channel.EMAIL, Notification.Channel.IN_APP):
            notif, was_created = Notification.objects.get_or_create(
                user=user,
                post=post,
                days_before=days,
                channel=channel,
                defaults={"send_at": send_at},
            )
            if was_created:
                created.append(notif)
    return created


def reschedule_for_post(post):
    """Call after a post's deadline or event date changes, so reminders follow the new date."""
    Notification.objects.filter(post=post, sent_at__isnull=True).delete()
    for f in Follow.objects.filter(post=post).select_related("user"):
        schedule_reminders(f.user, post)


def send_due_reminders(now=None, base_url="http://localhost:8000"):
    """Send email reminders that are due and mark in-app ones as delivered.

    Meant to run every few minutes (cron or a scheduler). Returns the number of emails sent.
    """
    now = now or timezone.now()
    due = (
        Notification.objects.filter(sent_at__isnull=True, send_at__lte=now)
        .select_related("user", "post")
    )
    emails_sent = 0
    for notif in due:
        post = notif.post
        if post.status != Post.Status.PUBLISHED:
            notif.delete()
            continue
        if notif.channel == Notification.Channel.EMAIL:
            link = base_url.rstrip("/") + reverse("pulse:post_detail", args=[post.pk])
            send_mail(
                subject=f"EUnited reminder – {notif.message}",
                message=(
                    f"Hi {notif.user.display_name},\n\n"
                    f"{notif.message}\n\n"
                    f"{post.summary}\n\n"
                    f"Open it on EUnited: {link}\n\n"
                    "You get this email because you rang the bell on this post. "
                    "Tap the bell again on the post to stop reminders."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notif.user.email],
                fail_silently=False,
            )
            emails_sent += 1
        notif.sent_at = now
        notif.save(update_fields=["sent_at"])
    return emails_sent
