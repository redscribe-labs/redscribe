import base64
import difflib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache
from django.urls import reverse

from .models import CachedGoogleFont

_CSS_ENDPOINT = "https://fonts.googleapis.com/css2"
_REQUEST_TIMEOUT_SECONDS = 10

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_FONT_FACE_RE = re.compile(r"(?:/\*\s*(?P<subset>[\w-]+)\s*\*/\s*)?@font-face\s*{(?P<body>[^}]*)}", re.DOTALL)
_PROP_RE = re.compile(r"font-(weight|style):\s*([^;]+);")
_URL_RE = re.compile(r"url\((https://[^)]+\.(?P<ext>woff2|woff|ttf))\)")
_PREFERRED_SUBSETS = ("latin", "latin-ext")

_VALID_FAMILY_RE = re.compile(r"^[A-Za-z0-9 \-]{1,100}$")

# Google's public font metadata (the list fonts.google.com itself browses).
# Fetched on demand for the profile form's suggestions/validation and kept
# in the cache for a day, so there's no bundled copy to keep up to date.
_METADATA_URL = "https://fonts.google.com/metadata/fonts"
_CATALOG_CACHE_KEY = "reports:google_font_catalog"
_CATALOG_TTL_SECONDS = 24 * 60 * 60
# After a failed fetch, wait this long before trying again — so an instance
# without internet access doesn't stall every profile page on a timeout.
_CATALOG_RETRY_SECONDS = 5 * 60


class GoogleFontFetchError(Exception):
    pass


def google_font_catalog() -> list[tuple[str, str]] | None:
    """[(family, category), ...] in popularity order, or None when Google
    Fonts can't be reached (callers then skip suggestions/catalog checks)."""
    cached = cache.get(_CATALOG_CACHE_KEY)
    if cached is not None:
        return cached or None
    try:
        catalog = _fetch_catalog()
    except GoogleFontFetchError:
        cache.set(_CATALOG_CACHE_KEY, [], _CATALOG_RETRY_SECONDS)
        return None
    cache.set(_CATALOG_CACHE_KEY, catalog, _CATALOG_TTL_SECONDS)
    return catalog


def _fetch_catalog() -> list[tuple[str, str]]:
    request = urllib.request.Request(_METADATA_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8")
        # Historically prefixed with an XSSI guard (")]}'"), so parse from
        # the first brace rather than the first byte.
        families = json.loads(text[text.index("{"):])["familyMetadataList"]
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GoogleFontFetchError(f"Could not reach Google Fonts: {exc}.") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise GoogleFontFetchError(f"Unexpected Google Fonts metadata: {exc}.") from exc
    families.sort(key=lambda f: (f.get("popularity", 0), f.get("family", "")))
    catalog = [
        (f["family"], f.get("category", ""))
        for f in families
        # Same rule validate_font_name enforces — no point suggesting a
        # family the form would refuse anyway.
        if isinstance(f.get("family"), str) and _VALID_FAMILY_RE.match(f["family"])
    ]
    if not catalog:
        raise GoogleFontFetchError("Google Fonts returned no font families.")
    return catalog


def _normalize(name: str) -> str:
    return " ".join((name or "").split()).lower()


def canonical_google_font(name: str, catalog: list[tuple[str, str]]) -> str | None:
    """The catalog's exact spelling of `name` (case-insensitive, whitespace
    collapsed), or None if Google Fonts has no such family."""
    needle = _normalize(name)
    return next((family for family, _category in catalog if family.lower() == needle), None)


def similar_google_fonts(name: str, catalog: list[tuple[str, str]], limit: int = 3) -> list[str]:
    """Catalog families spelled close to `name` — "did you mean" hints for a typo."""
    by_lower = {family.lower(): family for family, _category in catalog}
    matches = difflib.get_close_matches(_normalize(name), by_lower, n=limit, cutoff=0.75)
    return [by_lower[match] for match in matches]


def _css_string_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace('"', '\\"')
        .replace("<", "\\3C ").replace(">", "\\3E ")
    )


def font_face_css(family: str, *, embed: bool = True) -> str:
    """Emit @font-face rules for every cached weight/style of `family`.

    embed=True inlines each font as a base64 data-URI — for self-contained
    exports (PDF, standalone HTML). embed=False points at the same-origin
    report_font_file view instead — for pages served under the app's CSP,
    whose `font-src 'self'` blocks data: fonts.

    DB-read-only — never fetches over the network. Callers needing a family that
    isn't cached yet (report generation's admin-facing save path) go through
    fetch_and_cache_font() explicitly first; this only reads what's already there.
    """
    variants = CachedGoogleFont.objects.filter(family=family)
    if not embed:
        variants = variants.defer("font_data")
    if not variants:
        return ""
    rules = []
    for variant in variants:
        if embed:
            src = f"data:{variant.content_type};base64,{base64.b64encode(bytes(variant.font_data)).decode('ascii')}"
        else:
            path = reverse("report_font_file", args=[family, variant.weight, variant.style])
            src = f'"{path}?v={int(variant.fetched_at.timestamp())}"'
        rules.append(
            "@font-face {{ font-family: \"{family}\"; font-weight: {weight}; font-style: {style}; "
            "src: url({src}) format(\"{fmt}\"); font-display: swap; }}".format(
                family=_css_string_escape(family), weight=variant.weight, style=variant.style,
                src=src, fmt=variant.font_format,
            )
        )
    return "".join(rules)


def fetch_and_cache_font(family: str) -> int:
    family = (family or "").strip()
    if not family or not _VALID_FAMILY_RE.match(family):
        raise GoogleFontFetchError(f"Not a valid font family name: {family!r}")

    seen: set[tuple[str, str]] = set()
    variants: list[tuple[str, str, str]] = []
    for weight in ("400", "700"):
        css = _fetch_css(family, weight)
        for w, style, url in _parse_font_faces(css):
            if (w, style) in seen:
                continue
            seen.add((w, style))
            variants.append((w, style, url))
    if not variants:
        raise GoogleFontFetchError(f'Google Fonts has no family named "{family}".')

    fetched = []
    for weight, style, url in variants:
        font_bytes, content_type = _fetch_bytes(url)
        fetched.append((weight, style, url, font_bytes, content_type))

    CachedGoogleFont.objects.filter(family=family).delete()
    CachedGoogleFont.objects.bulk_create([
        CachedGoogleFont(
            family=family, weight=weight, style=style,
            font_format=url.rsplit(".", 1)[-1], content_type=content_type,
            font_data=font_bytes,
        )
        for weight, style, url, font_bytes, content_type in fetched
    ])
    return len(fetched)


def _fetch_css(family: str, weight: str = "400") -> str:
    query = urllib.parse.urlencode({"family": f"{family}:wght@{weight}", "display": "swap"})
    request = urllib.request.Request(f"{_CSS_ENDPOINT}?{query}", headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise GoogleFontFetchError(f"Google Fonts returned HTTP {response.status} for {family!r}.")
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            raise GoogleFontFetchError(f'Google Fonts has no family named "{family}".') from exc
        raise GoogleFontFetchError(f"Google Fonts request failed: HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GoogleFontFetchError(f"Could not reach Google Fonts: {exc}.") from exc


def _parse_font_faces(css: str) -> list[tuple[str, str, str]]:
    # Google's CSS2 response emits one @font-face block per Unicode subset
    # (cyrillic, greek, vietnamese, latin, ...) for each weight/style — all
    # covering different, mutually exclusive glyph ranges, not alternates
    # of the same glyphs. Since CachedGoogleFont stores one row per
    # (family, weight, style), picking the wrong block (e.g. "cyrillic-ext")
    # embeds a font with no Latin glyphs at all, silently pushing every
    # English-language render onto WeasyPrint's fallback font. Prefer the
    # "latin" subset (falling back to "latin-ext", then whatever's first)
    # so report text — English by default — actually has glyphs to draw.
    best: dict[tuple[str, str], tuple[int, str]] = {}
    for match in _FONT_FACE_RE.finditer(css):
        subset = (match.group("subset") or "").strip().lower()
        block = match.group("body")
        props = dict(_PROP_RE.findall(block))
        url_match = _URL_RE.search(block)
        if not url_match:
            continue
        weight = props.get("weight", "400").strip()
        style = props.get("style", "normal").strip()
        rank = _PREFERRED_SUBSETS.index(subset) if subset in _PREFERRED_SUBSETS else len(_PREFERRED_SUBSETS)
        key = (weight, style)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, url_match.group(1))
    return [(weight, style, url) for (weight, style), (_, url) in best.items()]


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "font/woff2")
            return response.read(), content_type
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GoogleFontFetchError(f"Could not download font file: {exc}.") from exc
