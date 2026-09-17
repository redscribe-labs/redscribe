import json
import logging
import secrets

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("redscribe.csp")


class ContentSecurityPolicyMiddleware:
    """Sets a nonce-based CSP header. Views/templates read the per-request
    nonce off `request.csp_nonce` (exposed to templates via the built-in
    `request` context processor as `request.csp_nonce`) and must put it on
    every inline `<script>` tag."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            f"script-src 'self' 'nonce-{request.csp_nonce}'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "report-uri /csp-report/"
        )
        return response


@csrf_exempt
@require_POST
def csp_report_view(request):
    """Browsers POST here (no auth, no CSRF token) whenever the CSP header
    above blocks something. Just logged — this is telemetry to catch a
    template/route the initial audit missed, not a page users see."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        report = payload.get("csp-report", payload)
    except (ValueError, UnicodeDecodeError):
        report = {"raw": request.body[:2048].decode("utf-8", "replace")}
    logger.warning("CSP violation: %s", json.dumps(report))
    return HttpResponse(status=204)
