from apps.accounts import security


def _deactivate_portal_users(client):
    users = list(client.portal_users.filter(is_active=True))
    for user in users:
        user.deactivate()
        security.invalidate_other_sessions(user)
    return len(users)


def deactivate_dormant_client_users(client):
    if client is None or client.engagements.filter(archived=False).exists():
        return

    _deactivate_portal_users(client)


def deactivate_client_users(client):
    # One-way on purpose: reactivating a client never reactivates its users, so people who
    # have left the client can't regain access. Each account is reactivated by hand.
    return _deactivate_portal_users(client)
