import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_KWARGS = {"token", "uidb64"}

REDACTED = "[redacted]"

_SENSITIVE_PARAM_RE = re.compile(
    r"(token|password|secret|key|otp|auth|signature|credential)", re.IGNORECASE
)

_LOOKS_LIKE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{16,}$")

MAX_QUERY_STRING_LENGTH = 500
MAX_REFERER_LENGTH = 500
MAX_USER_AGENT_LENGTH = 300


def redacted_path(match) -> str:
    if match is None:
        return ""
    path = match.route or ""

    def fill(m):
        name = m.group(1)
        if name in SENSITIVE_KWARGS:
            return REDACTED
        return str(match.kwargs.get(name, m.group(0)))

    filled = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", fill, path)
    return "/" + filled if not filled.startswith("/") else filled


def sanitize_query_params(pairs):
    return [(k, REDACTED if _SENSITIVE_PARAM_RE.search(k) else v) for k, v in pairs]


def sanitize_query_string(query_string: str) -> str:
    if not query_string:
        return ""
    pairs = sanitize_query_params(parse_qsl(query_string, keep_blank_values=True))
    return urlencode(pairs)[:MAX_QUERY_STRING_LENGTH]


def sanitize_referer(referer: str) -> str:
    if not referer:
        return ""
    try:
        parts = urlsplit(referer)
    except ValueError:
        return ""

    segments = [
        REDACTED if _LOOKS_LIKE_TOKEN_RE.match(segment) else segment
        for segment in parts.path.split("/")
    ]
    query = sanitize_query_string(parts.query)
    cleaned = urlunsplit(("", "", "/".join(segments), query, ""))
    return cleaned[:MAX_REFERER_LENGTH]


def sanitize_user_agent(user_agent: str) -> str:
    return (user_agent or "")[:MAX_USER_AGENT_LENGTH]


def sanitize_object_ref(kwargs: dict) -> str:
    return " ".join(
        f"{key}={REDACTED if key in SENSITIVE_KWARGS else value}"
        for key, value in sorted(kwargs.items())
        if key != "engagement_id"
    )
