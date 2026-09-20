import datetime

from django.utils import timezone

EXPIRING_SOON_THRESHOLD_DAYS = 30


def license_status(payload: dict | None) -> dict:
    if not payload:
        return {"state": "none"}

    expires = datetime.date.fromisoformat(payload["expires"])
    days_left = (expires - timezone.localdate()).days

    if days_left < 0:
        state = "expired"
    elif days_left <= EXPIRING_SOON_THRESHOLD_DAYS:
        state = "expiring_soon"
    else:
        state = "active"

    return {
        "state": state,
        "org": payload["org"],
        "expires": payload["expires"],
        "days_left": days_left,
    }
