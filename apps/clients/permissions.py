from apps.accounts.permissions import require_permission


def require_client_manager(user, action: str) -> None:
    require_permission(user, "clients.manage", action)
