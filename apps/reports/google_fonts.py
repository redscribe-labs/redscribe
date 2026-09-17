import re
import urllib.error
import urllib.parse
import urllib.request

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


class GoogleFontFetchError(Exception):
    pass


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
