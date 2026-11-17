"""Business logic for likes, follows (the bell) and reminders, kept out of the views."""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import moderation
from .models import Comment, CommentReport, Follow, Like, Notification, Post


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


def send_due_reminders(now=None, base_url=None):
    """Send email reminders that are due and mark in-app ones as delivered.

    Meant to run every few minutes (cron or a scheduler). Returns the number of emails sent.
    Links in the emails start with base_url, or with the SITE_URL setting if it isn't given.
    """
    now = now or timezone.now()
    base_url = base_url or settings.SITE_URL
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


# --- comments -------------------------------------------------------------------


class CommentRefused(Exception):
    """The comment was not saved. The message says why and is shown to the author."""


def add_comment(user, post, body):
    """Check and save a comment. Returns the Comment (visible or held); raises CommentRefused."""
    if not post.comments_open:
        raise CommentRefused("Comments are closed on this post.")
    verdict = moderation.check_comment(user, post, body)
    if verdict.action == moderation.REJECT:
        raise CommentRefused(verdict.reason)
    held = verdict.action == moderation.HOLD
    return Comment.objects.create(
        post=post,
        author=user,
        body=body,
        status=Comment.Status.HELD if held else Comment.Status.VISIBLE,
        moderation_note=verdict.reason if held else "",
    )


def report_comment(user, comment):
    """Flag a comment for the moderators. Returns False if the user had already reported it."""
    _, created = CommentReport.objects.get_or_create(comment=comment, reporter=user)
    if (
        created
        and comment.status == Comment.Status.VISIBLE
        and comment.moderated_by_id is None  # a moderator's decision is not overruled by reports
        and comment.reports.count() >= settings.PULSE_COMMENT_REPORTS_TO_HOLD
    ):
        comment.status = Comment.Status.HELD
        comment.moderation_note = "Reported by several students."
        comment.save(update_fields=["status", "moderation_note"])
    return created


def can_approve_comment(user, comment):
    """Who may make a held or hidden comment visible.

    Moderators approve students' comments. A comment written by a moderator (or by a
    superadmin) needs a superadmin: nobody approves their own comments, so a stolen
    moderator password is not enough to publish something the checks held back.
    """
    if not user.has_perm("pulse.hide_comment"):
        return False
    if user.is_superuser:
        return True
    return comment.author_id != user.pk and not comment.author.has_perm("pulse.hide_comment")


def set_comment_status(comment, status, by_user):
    """A moderator hides a comment or makes it visible again."""
    comment.status = status
    comment.moderated_by = by_user
    comment.save(update_fields=["status", "moderated_by"])
