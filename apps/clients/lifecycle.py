from apps.accounts import security


def deactivate_dormant_client_users(client):
    if client is None or client.engagements.filter(archived=False).exists():
        return

    for user in client.portal_users.filter(is_active=True):
        user.deactivate()
        security.invalidate_other_sessions(user)
