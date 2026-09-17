from .models import Notification


def unread_count(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"unread_notification_count": Notification.objects.filter(recipient=user, read=False).count()}
