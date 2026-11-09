from datetime import timedelta

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Club, University, User

from . import services
from .models import Notification, Post


class PulseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sum = University.objects.create(short_name="SUM", name="University of Mostar", email_domain="sum.ba")
        cls.unical = University.objects.create(short_name="UNICAL", name="University of Calabria", email_domain="unical.it")
        cls.admin = User.objects.create_superuser("admin@sum.ba", "pass12345!")
        cls.student = User.objects.create_user("luca@unical.it", "pass12345!", university=cls.unical)
        cls.club_user = User.objects.create_user("switch@sum.ba", "pass12345!", role=User.Role.CLUB)
        cls.club = Club.objects.create(name="SWITCH", university=cls.sum, verified=True)
        cls.club.members.add(cls.club_user)

    def make_post(self, **kwargs):
        defaults = dict(
            type=Post.Type.NEWS, title="A post", summary="Summary", university=self.sum,
            status=Post.Status.PUBLISHED, published_at=timezone.now(),
        )
        defaults.update(kwargs)
        return Post.objects.create(**defaults)


class FeedTests(PulseTestCase):
    def test_feed_shows_only_published_live_posts(self):
        now = timezone.now()
        live = self.make_post(title="Live news")
        self.make_post(title="Pending one", status=Post.Status.PENDING)
        self.make_post(title="Old mobility", type=Post.Type.MOBILITY, deadline=now - timedelta(days=1))
        response = self.client.get(reverse("pulse:feed"))
        self.assertContains(response, live.title)
        self.assertNotContains(response, "Pending one")
        self.assertNotContains(response, "Old mobility")

    def test_feed_newest_first(self):
        now = timezone.now()
        self.make_post(title="Older", published_at=now - timedelta(days=2))
        self.make_post(title="Newer", published_at=now)
        response = self.client.get(reverse("pulse:feed"))
        self.assertEqual([p.title for p in response.context["page"]], ["Newer", "Older"])

    def test_expired_posts_go_to_archive(self):
        self.make_post(title="Old mobility", type=Post.Type.MOBILITY, deadline=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse("pulse:archive"))
        self.assertContains(response, "Old mobility")

    def test_closing_soon_includes_deadlines_within_7_days(self):
        now = timezone.now()
        soon = self.make_post(title="Soon", type=Post.Type.MOBILITY, deadline=now + timedelta(days=2))
        self.make_post(title="Later", type=Post.Type.MOBILITY, deadline=now + timedelta(days=20))
        self.assertEqual(list(Post.objects.closing_soon()), [soon])

    def test_filters_and_search(self):
        self.make_post(title="Mostar news")
        self.make_post(title="Calabria news", university=self.unical)
        response = self.client.get(reverse("pulse:feed"), {"university": "UNICAL"})
        self.assertContains(response, "Calabria news")
        self.assertNotContains(response, "Mostar news")
        response = self.client.get(reverse("pulse:feed"), {"q": "mostar"})
        self.assertContains(response, "Mostar news")
        self.assertNotContains(response, "Calabria news")

    def test_anyone_can_read(self):
        post = self.make_post()
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_pending_post_hidden_from_public(self):
        post = self.make_post(status=Post.Status.PENDING)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)


class ValidationTests(PulseTestCase):
    def test_mobility_needs_deadline(self):
        post = Post(type=Post.Type.MOBILITY, title="x", summary="y", university=self.sum)
        with self.assertRaises(ValidationError):
            post.full_clean()

    def test_news_cannot_have_deadline(self):
        post = Post(type=Post.Type.NEWS, title="x", summary="y", university=self.sum, deadline=timezone.now())
        with self.assertRaises(ValidationError):
            post.full_clean()


class LikeAndBellTests(PulseTestCase):
    def test_like_requires_login(self):
        post = self.make_post()
        response = self.client.post(reverse("pulse:like", args=[post.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_like_toggles(self):
        post = self.make_post()
        self.client.force_login(self.student)
        self.client.post(reverse("pulse:like", args=[post.pk]))
        self.assertEqual(post.likes.count(), 1)
        self.client.post(reverse("pulse:like", args=[post.pk]))
        self.assertEqual(post.likes.count(), 0)

    def test_bell_schedules_reminders_3_and_1_days_before(self):
        deadline = timezone.now() + timedelta(days=10)
        post = self.make_post(type=Post.Type.MOBILITY, deadline=deadline)
        self.client.force_login(self.student)
        self.client.post(reverse("pulse:follow", args=[post.pk]))
        notifs = Notification.objects.filter(user=self.student, post=post)
        self.assertEqual(notifs.count(), 4)  # 2 days x (email + in-app)
        self.assertEqual(
            sorted(set(notifs.values_list("days_before", flat=True))), [1, 3]
        )
        # ringing the bell again turns it off and removes pending reminders
        self.client.post(reverse("pulse:follow", args=[post.pk]))
        self.assertFalse(Notification.objects.filter(user=self.student, post=post).exists())

    def test_due_reminders_are_emailed(self):
        post = self.make_post(type=Post.Type.MOBILITY, deadline=timezone.now() + timedelta(days=10))
        services.follow(self.student, post)
        later = post.deadline - timedelta(days=3) + timedelta(minutes=1)
        sent = services.send_due_reminders(now=later)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("in 3 days", mail.outbox[0].subject)

    @override_settings(SITE_URL="https://eunited.example.org")
    def test_reminder_email_links_to_the_site(self):
        post = self.make_post(type=Post.Type.MOBILITY, deadline=timezone.now() + timedelta(days=10))
        services.follow(self.student, post)
        services.send_due_reminders(now=post.deadline - timedelta(days=3) + timedelta(minutes=1))
        self.assertIn("https://eunited.example.org" + post.get_absolute_url(), mail.outbox[0].body)

    def test_bell_count_in_header(self):
        post = self.make_post(type=Post.Type.MOBILITY, deadline=timezone.now() + timedelta(days=10))
        services.follow(self.student, post)
        Notification.objects.filter(channel="in_app").update(send_at=timezone.now() - timedelta(minutes=1))
        self.client.force_login(self.student)
        response = self.client.get(reverse("pulse:feed"))
        self.assertEqual(response.context["unread_notifications"], 2)


class ClubWorkflowTests(PulseTestCase):
    def test_club_submission_goes_to_review_queue(self):
        self.client.force_login(self.club_user)
        response = self.client.post(reverse("pulse:club_submissions"), {
            "club": self.club.pk, "type": "news", "title": "Club news", "summary": "Hello",
            "language": "en",
        })
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="Club news")
        self.assertEqual(post.status, Post.Status.PENDING)
        self.assertEqual(post.university, self.sum)
        # not visible in the feed until approved
        self.assertNotContains(self.client.get(reverse("pulse:feed")), "Club news")
        post.publish(self.admin)
        self.assertContains(self.client.get(reverse("pulse:feed")), "Club news")

    def test_students_cannot_submit(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("pulse:club_submissions")).status_code, 403)

    def test_submit_link_only_for_verified_club_members(self):
        self.client.force_login(self.club_user)
        self.assertContains(self.client.get(reverse("pulse:feed")), "Submit a post")
        unverified = Club.objects.create(name="New club", university=self.sum, verified=False)
        member = User.objects.create_user("new@sum.ba", "pass12345!")
        unverified.members.add(member)
        self.client.force_login(member)
        self.assertNotContains(self.client.get(reverse("pulse:feed")), "Submit a post")
        self.assertEqual(self.client.get(reverse("pulse:club_submissions")).status_code, 403)

    def test_editor_cannot_publish_through_admin(self):
        editor = User.objects.create_user("ed@unical.it", "pass12345!", role=User.Role.EDITOR)
        self.assertTrue(editor.is_staff)
        self.assertTrue(editor.has_perm("pulse.change_post"))
        self.assertFalse(editor.has_perm("pulse.publish_post"))
        self.assertTrue(self.admin.has_perm("pulse.publish_post"))

    def test_admin_review_queue_approve_action(self):
        post = self.make_post(status=Post.Status.PENDING, title="Waiting")
        self.client.force_login(self.admin)
        url = reverse("admin:pulse_reviewqueue_changelist")
        self.assertContains(self.client.get(url), "Waiting")
        self.client.post(url, {"action": "approve", "_selected_action": [post.pk]})
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.PUBLISHED)
        self.assertEqual(post.approved_by, self.admin)


class EditorEditTests(PulseTestCase):
    """Editors can't publish, so their changes to a published post send it back for approval."""

    def setUp(self):
        self.editor = User.objects.create_user("ed@unical.it", "pass12345!", role=User.Role.EDITOR)
        self.post = self.make_post(title="Published news")

    def save_as(self, user, **changes):
        data = {
            "type": self.post.type, "title": self.post.title, "summary": self.post.summary,
            "body": "", "image_url": "", "language": "en", "university": self.sum.pk,
            "club": "", "author": "", "source_url": "", "location": "",
            "deadline_0": "", "deadline_1": "", "event_start_0": "", "event_start_1": "",
            "event_end_0": "", "event_end_1": "",
            "status": self.post.status, "rejection_reason": "", "_save": "Save",
        }
        data.update(changes)
        self.client.force_login(user)
        response = self.client.post(reverse("admin:pulse_post_change", args=[self.post.pk]), data)
        if response.status_code != 302:
            self.fail(response.context["adminform"].form.errors)
        self.post.refresh_from_db()

    def test_editor_change_sends_published_post_back_for_approval(self):
        self.save_as(self.editor, title="Edited by editor")
        self.assertEqual(self.post.status, Post.Status.PENDING)
        feed = self.client.get(reverse("pulse:feed")).context["page"]
        self.assertNotIn(self.post, list(feed))

    def test_editor_saving_without_changes_keeps_post_published(self):
        self.save_as(self.editor)
        self.assertEqual(self.post.status, Post.Status.PUBLISHED)

    def test_editor_cannot_hide_through_the_status_field(self):
        self.save_as(self.editor, status=Post.Status.ARCHIVED)
        self.assertEqual(self.post.status, Post.Status.PENDING)

    def test_superadmin_change_keeps_post_published(self):
        self.save_as(self.admin, title="Edited by admin")
        self.assertEqual(self.post.status, Post.Status.PUBLISHED)
