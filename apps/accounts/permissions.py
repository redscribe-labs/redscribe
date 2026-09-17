from django.core.exceptions import PermissionDenied


def require_superadmin(user, action: str) -> None:
    if not user.is_authenticated or not user.is_superadmin_role:
        raise PermissionDenied(f"Only a Superadmin can {action}.")


def require_permission(user, codename: str, action: str) -> None:
    if not user.is_authenticated or not user.has_permission(codename):
        raise PermissionDenied(f"You don't have permission to {action}.")
