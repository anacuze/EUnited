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
from .forms import ClubPostForm
from .models import Follow, Like, Post, Tag


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
    return queryset.select_related("university", "club").prefetch_related("tags").annotate(
        like_count=Count("likes", distinct=True)
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


def post_detail(request, pk):
    post = get_object_or_404(_with_counts(Post.objects.all()), pk=pk)
    visible = post.status in (Post.Status.PUBLISHED, Post.Status.ARCHIVED)
    is_owner = request.user.is_authenticated and post.author_id == request.user.pk
    if not visible and not is_owner and not request.user.is_staff:
        return render(request, "pulse/not_found.html", status=404)
    liked, followed = _user_marks(request.user, [post])
    return render(request, "pulse/post_detail.html", {
        "post": post, "liked": liked, "followed": followed,
    })


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
    if not request.user.clubs.filter(verified=True).exists():
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
