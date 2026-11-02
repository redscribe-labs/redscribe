from django.contrib.auth import get_user_model
from django.db.models import Q


def keep_current_user_selectable(field, current):
    """Show people by their in-app label, and keep `current` choosable even if it's no longer
    in the field's queryset (typically because the account was deactivated).

    Without this, a form opened on a record whose person has since been deactivated renders
    the empty choice, and saving it for any unrelated change silently clears that person.
    """
    field.label_from_instance = lambda user: user.display_label
    if current is None or field.queryset is None:
        return
    queryset = field.queryset
    if queryset.filter(pk=current.pk).exists():
        return
    field.queryset = get_user_model().objects.filter(
        Q(pk__in=queryset.values("pk")) | Q(pk=current.pk)
    ).order_by(*(queryset.query.order_by or ("username",)))
