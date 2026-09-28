from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

from .google_fonts import _VALID_FAMILY_RE
from .models import CachedGoogleFont

# Content-Type comes from this fixed map, never from the stored `content_type`
# (whatever header the upstream fetch returned) — this is an unauthenticated
# same-origin endpoint, so it must only ever answer with a font type.
_FONT_CONTENT_TYPES = {"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf"}


@require_GET
def report_font_file(request, family, weight, style):
    """Serves one cached report-profile font variant from our own origin, so the
    app's `font-src 'self'` CSP allows it (the data: URIs font_face_css() embeds
    for exports would be blocked). No login required: base.html renders on the
    login page too, and these are public Google Fonts. The URL carries a
    `?v=<fetched_at>` cache-buster (see font_face_css), so it's cached forever."""
    if not _VALID_FAMILY_RE.match(family):
        raise Http404
    variant = CachedGoogleFont.objects.filter(family=family, weight=weight, style=style).first()
    if variant is None or variant.font_format not in _FONT_CONTENT_TYPES:
        raise Http404
    response = HttpResponse(bytes(variant.font_data), content_type=_FONT_CONTENT_TYPES[variant.font_format])
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
