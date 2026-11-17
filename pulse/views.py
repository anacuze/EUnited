from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import University

from . import services
from .forms import ClubPostForm, CommentForm
from .models import Comment, CommentReport, Follow, Like, Post, Tag


def _apply_filters(request, queryset):
    """Filter by ?university=SUM&type=event&tag=erasmus&q=text. Returns (queryset, active filters)."""
    active = {
        "university": request.GET.get("university", ""),
        "type": request.GET.get("type", ""),
        "tag": request.GET.get("tag", ""),
        "q": request.GET.get("q", "").strip(),
    }
    if active["university"]:
        queryset = queryset.filter(university__short_name__iexact=active["university"])
    if active["type"] in Post.Type.values:
        queryset = queryset.filter(type=active["type"])
    if active["tag"]:
        queryset = queryset.filter(tags__slug=active["tag"])
    if active["q"]:
        q = active["q"]
        queryset = queryset.filter(Q(title__icontains=q) | Q(summary__icontains=q) | Q(body__icontains=q))
    return queryset.distinct(), active


def _with_counts(queryset):
    # Django ignores Meta.ordering once a query is grouped for Count(), so order explicitly:
    # newest posts first.
    return (
        queryset.select_related("university", "club").prefetch_related("tags")
        .annotate(
            like_count=Count("likes", distinct=True),
            comment_count=Count(
                "comments", filter=Q(comments__status=Comment.Status.VISIBLE), distinct=True
            ),
        )
        .order_by(*Post._meta.ordering)
    )


def _user_marks(user, posts):
    """Which of these posts the user has liked / followed (for filled hearts and bells)."""
    if not user.is_authenticated:
        return set(), set()
    ids = [p.pk for p in posts]
    liked = set(Like.objects.filter(user=user, post_id__in=ids).values_list("post_id", flat=True))
    followed = set(Follow.objects.filter(user=user, post_id__in=ids).values_list("post_id", flat=True))
    return liked, followed


def _render_list(request, base_queryset, template_title, is_archive=False):
    queryset, active = _apply_filters(request, base_queryset)
    page = Paginator(_with_counts(queryset), settings.PULSE_PAGE_SIZE).get_page(request.GET.get("page"))

    closing_soon = []
    if not is_archive and page.number == 1:
        closing_soon = list(_with_counts(_apply_filters(request, Post.objects.closing_soon())[0]))
        # soonest first, by whichever date is relevant (deadline or event start)
        closing_soon.sort(key=lambda p: p.key_date)
        closing_soon = closing_soon[:10]

    liked, followed = _user_marks(request.user, list(page) + closing_soon)
    query_without_page = request.GET.copy()
    query_without_page.pop("page", None)

    return render(request, "pulse/feed.html", {
        "page": page,
        "closing_soon": closing_soon,
        "liked": liked,
        "followed": followed,
        "active": active,
        "universities": University.objects.filter(posts__isnull=False).distinct(),
        "types": Post.Type.choices,
        "tags": Tag.objects.filter(posts__status=Post.Status.PUBLISHED).distinct(),
        "is_archive": is_archive,
        "title": template_title,
        "querystring": query_without_page.urlencode(),
        "has_filters": any(active.values()),
    })


def feed(request):
    return _render_list(request, Post.objects.live(), "Pulse")


def archive(request):
    return _render_list(request, Post.objects.archived(), "Archive", is_archive=True)


def _comments_for(user, post):
    """The comments this user may see: visible ones, their own held ones, and for
    moderators every comment that waits for a decision."""
    shown = Q(status=Comment.Status.VISIBLE)
    if user.is_authenticated:
        if user.has_perm("pulse.hide_comment"):
            shown |= Q(status=Comment.Status.HELD)
        else:
            shown |= Q(status=Comment.Status.HELD, author=user)
    return post.comments.filter(shown).select_related("author__university")


def _render_post(request, post, comment_form=None):
    liked, followed = _user_marks(request.user, [post])
    comments = list(_comments_for(request.user, post))
    reported = set()
    if request.user.is_authenticated:
        reported = set(
            CommentReport.objects.filter(reporter=request.user, comment__in=comments)
            .values_list("comment_id", flat=True)
        )
    return render(request, "pulse/post_detail.html", {
        "post": post, "liked": liked, "followed": followed,
        "comments": comments,
        "reported": reported,
        "comment_form": comment_form or CommentForm(),
        "can_moderate": request.user.has_perm("pulse.hide_comment"),
        "approvable": {
            c.pk for c in comments
            if c.status != Comment.Status.VISIBLE and services.can_approve_comment(request.user, c)
        },
    })


def post_detail(request, pk):
    post = get_object_or_404(_with_counts(Post.objects.all()), pk=pk)
    visible = post.status in (Post.Status.PUBLISHED, Post.Status.ARCHIVED)
    is_owner = request.user.is_authenticated and post.author_id == request.user.pk
    if not visible and not is_owner and not request.user.is_staff:
        return render(request, "pulse/not_found.html", status=404)
    return _render_post(request, post)


def _back(request, post):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        return redirect(next_url)
    return redirect(post.get_absolute_url())


@login_required
@require_POST
def like(request, pk):
    post = get_object_or_404(Post.objects.published(), pk=pk)
    services.toggle_like(request.user, post)
    return _back(request, post)


@login_required
@require_POST
def follow(request, pk):
    post = get_object_or_404(Post.objects.published(), pk=pk)
    if not post.can_follow:
        messages.info(request, "This post has no upcoming date to remind you about.")
        return _back(request, post)
    now_following = services.toggle_follow(request.user, post)
    if now_following:
        days = " and ".join(str(d) for d in settings.PULSE_REMINDER_DAYS)
        messages.success(request, f"Bell on – we'll remind you {days} day(s) before: {post.title}")
    else:
        messages.info(request, f"Bell off – no more reminders for: {post.title}")
    return _back(request, post)


@login_required
def notifications(request):
    now = timezone.now()
    items = list(
        request.user.notifications.filter(channel="in_app", send_at__lte=now)
        .select_related("post")[:50]
    )
    request.user.notifications.filter(
        channel="in_app", send_at__lte=now, read_at__isnull=True
    ).update(read_at=now)
    following = (
        Follow.objects.filter(user=request.user)
        .select_related("post")
        .order_by("-created_at")
    )
    return render(request, "pulse/notifications.html", {"items": items, "following": following})


@login_required
def club_submissions(request):
    """A club account's own submitted posts with their status, and the submit form."""
    if not request.user.can_submit_posts:
        return HttpResponseForbidden("Only members of a verified student club can submit posts.")
    if request.method == "POST":
        form = ClubPostForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Sent for approval. You'll see the status below.")
            return redirect("pulse:club_submissions")
    else:
        form = ClubPostForm(user=request.user)
    posts = Post.objects.filter(author=request.user).order_by("-created_at")
    return render(request, "pulse/club_submissions.html", {"form": form, "posts": posts})


# --- comments -------------------------------------------------------------------


def _to_comments(post):
    return redirect(post.get_absolute_url() + "#comments")


@login_required
@require_POST
def comment_add(request, pk):
    post = get_object_or_404(_with_counts(Post.objects.published()), pk=pk)
    if not post.comments_open:
        messages.error(request, "Comments are closed on this post.")
        return _to_comments(post)
    form = CommentForm(request.POST)
    if form.is_valid():
        try:
            comment = services.add_comment(request.user, post, form.cleaned_data["body"])
        except services.CommentRefused as refused:
            form.add_error("body", str(refused))
        else:
            if comment.status == Comment.Status.HELD:
                messages.info(
                    request,
                    "Your comment will appear once a moderator has checked it. Only you can see it for now.",
                )
            return _to_comments(post)
    # Show the page again with the text the student wrote and what was wrong with it.
    return _render_post(request, post, comment_form=form)


@login_required
@require_POST
def comment_delete(request, pk):
    """Students delete their own comments. Moderators hide comments instead (comment_moderate)."""
    comment = get_object_or_404(Comment.objects.select_related("post"), pk=pk, author=request.user)
    comment.delete()
    messages.info(request, "Your comment was deleted.")
    return _to_comments(comment.post)


@login_required
@require_POST
def comment_report(request, pk):
    comment = get_object_or_404(
        Comment.objects.select_related("post"), pk=pk, status=Comment.Status.VISIBLE
    )
    if comment.author_id == request.user.pk:
        return HttpResponseForbidden("You can't report your own comment. You can delete it.")
    services.report_comment(request.user, comment)
    messages.success(request, "Thanks. A moderator will look at that comment.")
    return _to_comments(comment.post)


@login_required
@require_POST
def comment_moderate(request, pk):
    """A moderator hides a comment, or approves one that was waiting."""
    if not request.user.has_perm("pulse.hide_comment"):
        return HttpResponseForbidden("Only moderators can do this.")
    comment = get_object_or_404(Comment.objects.select_related("post", "author"), pk=pk)
    if request.POST.get("action") == "approve":
        if not services.can_approve_comment(request.user, comment):
            return HttpResponseForbidden("Only a superadmin can approve a comment written by a moderator.")
        services.set_comment_status(comment, Comment.Status.VISIBLE, request.user)
        messages.success(request, "Comment approved. Everyone can see it now.")
    else:
        services.set_comment_status(comment, Comment.Status.HIDDEN, request.user)
        messages.info(request, "Comment hidden. You can restore it in the admin panel (Comments).")
    return _to_comments(comment.post)


def rules(request):
    return render(request, "pulse/rules.html", {
        "max_links": settings.PULSE_COMMENT_MAX_LINKS,
        "automatic_check": bool(settings.PULSE_COMMENT_CLASSIFIER),
    })
