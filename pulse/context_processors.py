from django.utils import timezone


def notifications(request):
    """Adds the number of unread in-app reminders for the bell in the header."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"unread_notifications": 0}
    count = user.notifications.filter(
        channel="in_app", send_at__lte=timezone.now(), read_at__isnull=True
    ).count()
    return {"unread_notifications": count}
