from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from . import moderation, services
from .models import BlockedWord, Comment, CommentReport, Post
from .tests import PulseTestCase


@override_settings(PULSE_COMMENT_MIN_SECONDS=0)
class CommentTestCase(PulseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = User.objects.create_user("ana@sum.ba", "pass12345!", university=cls.sum, first_name="Ana")
        cls.moderator = User.objects.create_user("mod@sum.ba", "pass12345!", role=User.Role.MODERATOR)

    def setUp(self):
        self.post = self.make_post(title="Open post")
        self.url = reverse("pulse:post_detail", args=[self.post.pk])

    def add(self, body, user=None, post=None):
        self.client.force_login(user or self.student)
        return self.client.post(reverse("pulse:comment_add", args=[(post or self.post).pk]), {"body": body})

    def comment(self, body="Nice one", author=None, **kwargs):
        return Comment.objects.create(post=self.post, author=author or self.student, body=body, **kwargs)


class CommentingTests(CommentTestCase):
    def test_comment_appears_at_once(self):
        response = self.add("Is this open to first-year students?")
        self.assertRedirects(response, self.url + "#comments", fetch_redirect_response=False)
        comment = Comment.objects.get()
        self.assertEqual((comment.author, comment.status), (self.student, "visible"))
        self.client.logout()
        page = self.client.get(self.url)
        self.assertContains(page, "Is this open to first-year students?")
        self.assertContains(page, "UNICAL")
        self.assertContains(page, "Log in</a> with your university account to comment")

    def test_login_required(self):
        response = self.client.post(reverse("pulse:comment_add", args=[self.post.pk]), {"body": "Hi"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertEqual(Comment.objects.count(), 0)

    def test_html_is_shown_as_text(self):
        self.add("<script>alert(1)</script>\nsecond line")
        page = self.client.get(self.url)
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;<br>second line")

    def test_empty_and_too_long_comments_are_refused(self):
        self.assertContains(self.add("   "), "This field is required")
        response = self.add("x" * 1001)
        self.assertContains(response, "at most 1000 characters")
        self.assertEqual(Comment.objects.count(), 0)

    def test_only_published_live_posts_take_comments(self):
        pending = self.make_post(title="Pending", status=Post.Status.PENDING)
        self.assertEqual(self.add("Hi", post=pending).status_code, 404)
        old = self.make_post(title="Old", type=Post.Type.MOBILITY, deadline=timezone.now() - timedelta(days=1))
        Comment.objects.create(post=old, author=self.other, body="Posted while it was open")
        self.client.force_login(self.student)
        response = self.client.post(reverse("pulse:comment_add", args=[old.pk]), {"body": "Too late"}, follow=True)
        self.assertContains(response, "Comments are closed on this post")
        self.assertEqual(old.comments.count(), 1)
        page = self.client.get(reverse("pulse:post_detail", args=[old.pk]))
        self.assertContains(page, "Posted while it was open")
        self.assertContains(page, "comments are closed")
        self.assertNotContains(page, "Post comment")

    def test_feed_shows_the_number_of_visible_comments(self):
        self.comment("One")
        self.comment("Two", author=self.other)
        self.comment("Hidden", status=Comment.Status.HIDDEN)
        response = self.client.get(reverse("pulse:feed"))
        self.assertEqual(response.context["page"][0].comment_count, 2)
        self.assertContains(response, f'href="{self.url}#comments"')
        self.assertContains(response, "Discuss, 2 comments")

    def test_author_deletes_own_comment_only(self):
        mine, theirs = self.comment("Mine"), self.comment("Theirs", author=self.other)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse("pulse:comment_delete", args=[theirs.pk])).status_code, 404)
        self.client.post(reverse("pulse:comment_delete", args=[mine.pk]))
        self.assertEqual(list(Comment.objects.all()), [theirs])

    def test_comments_go_when_the_account_is_deleted(self):
        self.comment("Mine", author=self.other)
        self.other.delete()
        self.assertEqual(Comment.objects.count(), 0)


class AutomaticCheckTests(CommentTestCase):
    @override_settings(PULSE_COMMENT_MIN_SECONDS=30)
    def test_too_fast(self):
        self.add("First")
        response = self.add("Second, right away")
        self.assertContains(response, "commenting very fast")
        self.assertContains(response, "Second, right away")  # the text is not lost
        self.assertEqual(Comment.objects.count(), 1)
        Comment.objects.update(created_at=timezone.now() - timedelta(seconds=31))
        self.add("Second, later")
        self.assertEqual(Comment.objects.count(), 2)

    def test_same_comment_twice(self):
        self.add("Great   news!")
        self.assertContains(self.add("great news!"), "already posted this comment")
        self.assertEqual(Comment.objects.count(), 1)

    def test_too_many_links(self):
        self.add("See https://a.example and www.b.example")
        self.assertEqual(Comment.objects.count(), 1)
        response = self.add("https://a.example https://b.example https://c.example")
        self.assertContains(response, "at most 2 links")
        self.assertEqual(Comment.objects.count(), 1)

    def test_blocked_word_holds_the_comment_for_a_moderator(self):
        BlockedWord.objects.create(word="  Idiot ")
        self.add("You IDIOT, read the post")
        held = Comment.objects.get()
        self.assertEqual(held.status, "held")
        self.assertIn("idiot", held.moderation_note)
        # the author sees it marked as waiting; other students don't see it at all
        self.assertContains(self.client.get(self.url), "Only you can see this comment for now")
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.url), "read the post")
        self.assertEqual(self.client.get(reverse("pulse:feed")).context["page"][0].comment_count, 0)

    def test_blocked_words_match_whole_words_only(self):
        BlockedWord.objects.create(word="ass")
        self.add("The class assignment passes")
        self.assertEqual(Comment.objects.get().status, "visible")

    def test_classifier_is_off_by_default(self):
        with mock.patch.object(moderation.requests, "post") as post:
            self.add("Anything")
        post.assert_not_called()

    @override_settings(PULSE_COMMENT_CLASSIFIER="pulse.moderation.openai_classifier", OPENAI_API_KEY="test-key")
    def test_openai_classifier_holds_flagged_comments(self):
        def answer(flagged):
            response = mock.Mock()
            response.json.return_value = {"results": [{
                "flagged": flagged, "categories": {"harassment": flagged, "violence": False}}]}
            return response

        with mock.patch.object(moderation.requests, "post", return_value=answer(True)) as post:
            self.add("Something nasty")
        self.assertEqual(post.call_args.kwargs["json"]["input"], "Something nasty")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")
        held = Comment.objects.get()
        self.assertEqual(held.status, "held")
        self.assertIn("harassment", held.moderation_note)
        with mock.patch.object(moderation.requests, "post", return_value=answer(False)):
            self.add("Something friendly")
        self.assertEqual(Comment.objects.get(body="Something friendly").status, "visible")

    @override_settings(PULSE_COMMENT_CLASSIFIER="pulse.moderation.openai_classifier")
    def test_comment_goes_through_when_the_classifier_is_down(self):
        with mock.patch.object(moderation.requests, "post", side_effect=OSError("no network")):
            with self.assertLogs("pulse.moderation", level="ERROR"):
                self.add("Still works")
        self.assertEqual(Comment.objects.get().status, "visible")


class ReportAndModerationTests(CommentTestCase):
    def test_report_once_and_not_your_own(self):
        comment = self.comment("Rude", author=self.other)
        self.client.force_login(self.student)
        url = reverse("pulse:comment_report", args=[comment.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(CommentReport.objects.count(), 1)
        self.assertContains(self.client.get(self.url), "Reported")
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 403)

    @override_settings(PULSE_COMMENT_REPORTS_TO_HOLD=2)
    def test_several_reports_take_a_comment_down_until_checked(self):
        comment = self.comment("Rude", author=self.other)
        services.report_comment(self.student, comment)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "visible")
        services.report_comment(self.club_user, comment)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "held")
        # once a moderator has approved it, more reports don't take it down again
        services.set_comment_status(comment, Comment.Status.VISIBLE, self.moderator)
        services.report_comment(self.admin, comment)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "visible")

    def test_students_cannot_moderate(self):
        comment = self.comment("Fine", author=self.other)
        self.client.force_login(self.student)
        response = self.client.post(reverse("pulse:comment_moderate", args=[comment.pk]), {"action": "hide"})
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(self.client.get(self.url), ">Hide<")

    def test_moderator_hides_and_approves_on_the_page(self):
        visible = self.comment("Rude", author=self.other)
        held = self.comment("Waiting", status=Comment.Status.HELD, moderation_note='Contains the blocked word "x".')
        self.client.force_login(self.moderator)
        page = self.client.get(self.url)
        self.assertContains(page, "Waiting for a moderator: Contains the blocked word")
        self.client.post(reverse("pulse:comment_moderate", args=[visible.pk]), {"action": "hide"})
        self.client.post(reverse("pulse:comment_moderate", args=[held.pk]), {"action": "approve"})
        visible.refresh_from_db(); held.refresh_from_db()
        self.assertEqual((visible.status, visible.moderated_by), ("hidden", self.moderator))
        self.assertEqual(held.status, "visible")
        self.client.force_login(self.student)
        page = self.client.get(self.url)
        self.assertNotContains(page, "Rude")
        self.assertContains(page, "Waiting")

    def test_moderators_comments_need_a_superadmin(self):
        # e.g. someone stole a moderator's password and writes something the checks hold back
        BlockedWord.objects.create(word="scam")
        self.add("Click here, not a scam", user=self.moderator)
        mine = Comment.objects.get()
        self.assertEqual(mine.status, "held")
        colleague = User.objects.create_user("mod2@sum.ba", "pass12345!", role=User.Role.MODERATOR)
        for moderator in (self.moderator, colleague):
            self.client.force_login(moderator)
            page = self.client.get(self.url)
            self.assertContains(page, "only a superadmin can approve it")
            self.assertNotContains(page, 'value="approve"')
            response = self.client.post(reverse("pulse:comment_moderate", args=[mine.pk]), {"action": "approve"})
            self.assertEqual(response.status_code, 403)
            response = self.client.post(
                reverse("admin:pulse_comment_changelist"),
                {"action": "restore", "_selected_action": [mine.pk]}, follow=True)
            self.assertContains(response, "can only be approved by a superadmin")
        mine.refresh_from_db()
        self.assertEqual(mine.status, "held")
        # a moderator can still hide it, and the superadmin decides
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), 'value="approve"')
        self.client.post(reverse("pulse:comment_moderate", args=[mine.pk]), {"action": "approve"})
        mine.refresh_from_db()
        self.assertEqual((mine.status, mine.moderated_by), ("visible", self.admin))

    def test_moderator_uses_the_admin_panel(self):
        waiting = self.comment("Waiting", status=Comment.Status.HELD)
        reported = self.comment("Reported one", author=self.other)
        CommentReport.objects.create(comment=reported, reporter=self.student)
        self.comment("Quiet one", author=self.other)
        self.client.force_login(self.moderator)
        url = reverse("admin:pulse_comment_changelist")
        rows = [str(c) for c in self.client.get(url).context["cl"].result_list]
        self.assertEqual(rows, ["Waiting", "Reported one", "Quiet one"])
        response = self.client.post(url, {"action": "restore", "_selected_action": [waiting.pk]}, follow=True)
        self.assertContains(response, "1 comment(s) visible again")
        self.client.post(url, {"action": "hide", "_selected_action": [reported.pk]})
        reported.refresh_from_db()
        self.assertEqual(reported.status, "hidden")
        # and the list of blocked words is theirs to keep up to date
        self.client.post(reverse("admin:pulse_blockedword_add"), {"word": "Spamword"})
        self.assertTrue(BlockedWord.objects.filter(word="spamword").exists())

    def test_rules_page(self):
        response = self.client.get(reverse("pulse:rules"))
        self.assertContains(response, "Community rules")
        self.assertNotContains(response, "OpenAI")
        with self.settings(PULSE_COMMENT_CLASSIFIER="pulse.moderation.openai_classifier"):
            self.assertContains(self.client.get(reverse("pulse:rules")), "OpenAI")

