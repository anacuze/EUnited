from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import Follow, Like, Notification, Post, ReviewQueue, Source, Tag
from .services import reschedule_for_post


class PublishPermissionMixin:
    """Admin actions for the publishing workflow, shared by Posts and the Review queue."""

    def has_publish_permission(self, request):
        return request.user.has_perm("pulse.publish_post")

    def has_hide_permission(self, request):
        return request.user.has_perm("pulse.hide_post") or request.user.has_perm("pulse.publish_post")

    @admin.action(description="Approve and publish selected posts", permissions=["publish"])
    def approve(self, request, queryset):
        count = 0
        for post in queryset.exclude(status=Post.Status.PUBLISHED):
            post.publish(request.user)
            count += 1
        self.message_user(request, f"{count} post(s) published.", messages.SUCCESS)

    @admin.action(description="Reject selected posts", permissions=["publish"])
    def reject(self, request, queryset):
        count = 0
        for post in queryset:
            post.reject(request.user, post.rejection_reason or "Rejected by an admin.")
            count += 1
        self.message_user(
            request,
            f"{count} post(s) rejected. Open a post to write the reason the club will see.",
            messages.WARNING,
        )

    @admin.action(description="Hide selected posts (move to archive)", permissions=["hide"])
    def hide(self, request, queryset):
        count = queryset.update(status=Post.Status.ARCHIVED)
        self.message_user(request, f"{count} post(s) hidden.", messages.SUCCESS)


@admin.register(Post)
class PostAdmin(PublishPermissionMixin, admin.ModelAdmin):
    list_display = ("title", "type", "university", "status_badge", "submitted_by", "key_date_col", "published_at")
    list_filter = ("status", "type", "university", "tags")
    search_fields = ("title", "summary", "body")
    autocomplete_fields = ("tags",)
    readonly_fields = ("approved_by", "published_at", "created_at", "updated_at", "source")
    actions = ["approve", "reject", "hide"]
    date_hierarchy = "created_at"
    fieldsets = (
        (None, {"fields": ("type", "title", "summary", "body", "image_url", "language", "tags")}),
        ("Where it comes from", {"fields": ("university", "club", "author", "source", "source_url")}),
        ("Dates", {
            "fields": ("deadline", "event_start", "event_end", "location"),
            "description": "Mobility: deadline required. Events: start required. "
            "Scientific events: start required, deadline optional.",
        }),
        ("Publishing", {"fields": ("status", "rejection_reason", "approved_by", "published_at", "created_at", "updated_at")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colors = {
            "draft": "#888", "pending": "#d98200", "published": "#1a8a4a",
            "rejected": "#c0392b", "archived": "#555",
        }
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.status, "#000"), obj.get_status_display()
        )

    @admin.display(description="Submitted by")
    def submitted_by(self, obj):
        if obj.club:
            return obj.club.name
        if obj.source:
            return f"Importer: {obj.source.name}"
        return obj.author or "–"

    @admin.display(description="Deadline / start", ordering="deadline")
    def key_date_col(self, obj):
        return timezone.localtime(obj.key_date).strftime("%d.%m.%Y %H:%M") if obj.key_date else "–"

    def save_model(self, request, obj, form, change):
        wants_publish = obj.status == Post.Status.PUBLISHED
        was_published = False
        if change:
            previous = Post.objects.get(pk=obj.pk)
            was_published = previous.status == Post.Status.PUBLISHED
        else:
            previous = None
            if not obj.author_id:
                obj.author = request.user

        can_publish = self.has_publish_permission(request)
        # Users who can't publish (editors) may only leave a post as a draft or waiting for
        # approval. Any change they make to a published, rejected or hidden post sends it
        # back to the review queue, so nothing reaches the feed without a superadmin.
        if (
            not can_publish
            and (not change or form.has_changed())
            and obj.status not in (Post.Status.DRAFT, Post.Status.PENDING)
        ):
            obj.status = Post.Status.PENDING
            if was_published:
                text = ("Changes saved. The post is waiting for approval again and is hidden "
                        "from the Pulse until a superadmin publishes it.")
            else:
                text = "Saved as 'Waiting for approval' – a superadmin has to publish it."
            self.message_user(request, text, messages.WARNING)
        elif can_publish and wants_publish and not was_published:
            obj.approved_by = request.user
            obj.published_at = obj.published_at or timezone.now()

        super().save_model(request, obj, form, change)

        if previous and (
            previous.deadline != obj.deadline or previous.event_start != obj.event_start
        ):
            reschedule_for_post(obj)


@admin.register(ReviewQueue)
class ReviewQueueAdmin(PostAdmin):
    """Same as Posts, but only shows drafts and posts waiting for approval, oldest first."""

    list_filter = ("type", "university", "status")
    actions = ["approve", "reject"]
    date_hierarchy = None

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(status__in=[Post.Status.PENDING, Post.Status.DRAFT])
            .order_by("created_at")
        )

    def has_add_permission(self, request):
        return False


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "kind", "university", "active", "last_checked_at")
    list_filter = ("kind", "active", "university")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "post", "days_before", "channel", "send_at", "sent_at", "read_at")
    list_filter = ("channel", "days_before")
    raw_id_fields = ("user", "post")


admin.site.register(Like)
admin.site.register(Follow)
