import time

from . import redaction
from .integrity import append_with_chain

_SAFE_METHODS = {"HEAD", "OPTIONS"}

_EXCLUDED_VIEW_NAMES = {
    "health",
    "csp_report",
}

_REDACTED_PATH_VIEW_NAMES = {
    "accounts:password_reset_confirm",
    "accounts:account_setup_confirm",
}


def _client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000)

        if request.method not in _SAFE_METHODS:
            match = getattr(request, "resolver_match", None)
            view_name = match.view_name if match else None
            if view_name not in _EXCLUDED_VIEW_NAMES:
                self._log(request, response, duration_ms)

        return response

    def _log(self, request, response, duration_ms):
        user = getattr(request, "user", None)
        actor = user if (user is not None and user.is_authenticated) else None
        match = getattr(request, "resolver_match", None)
        kwargs = (match.kwargs if match else None) or {}
        view_name = match.view_name if match else ""

        path = (
            redaction.redacted_path(match)
            if view_name in _REDACTED_PATH_VIEW_NAMES
            else request.path
        )

        append_with_chain(
            actor=actor,
            actor_username=getattr(actor, "username", ""),
            actor_role=getattr(actor, "role", ""),
            action=view_name,
            method=request.method,
            path=path,
            status_code=response.status_code,
            engagement_id=str(kwargs.get("engagement_id", "")),
            object_ref=redaction.sanitize_object_ref(kwargs),
            ip_address=_client_ip(request),
            query_string=redaction.sanitize_query_string(request.META.get("QUERY_STRING", "")),
            referer=redaction.sanitize_referer(request.META.get("HTTP_REFERER", "")),
            user_agent=redaction.sanitize_user_agent(request.META.get("HTTP_USER_AGENT", "")),
            duration_ms=duration_ms,
        )
