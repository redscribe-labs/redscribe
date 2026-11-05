import re

_RGBA_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([\d.]+)\s*)?\)")


def parse_rgba(value: str) -> tuple[int, int, int, float] | None:
    match = _RGBA_RE.match((value or "").strip())
    if not match:
        return None
    r, g, b = (min(int(match.group(i)), 255) for i in (1, 2, 3))
    a = float(match.group(4)) if match.group(4) is not None else 1.0
    return (r, g, b, a)


def composite_on_white(r: int, g: int, b: int, alpha: float) -> tuple[int, int, int]:
    return (
        round(alpha * r + (1 - alpha) * 255),
        round(alpha * g + (1 - alpha) * 255),
        round(alpha * b + (1 - alpha) * 255),
    )


def contrasting_text_rgb(background_rgba: str, default: tuple[int, int, int] = (15, 23, 42)) -> tuple[int, int, int]:
    parsed = parse_rgba(background_rgba)
    if not parsed:
        return default
    r, g, b, alpha = parsed
    cr, cg, cb = composite_on_white(r, g, b, alpha)
    luminance = 0.2126 * cr + 0.7152 * cg + 0.0722 * cb
    return (255, 255, 255) if luminance < 140 else (15, 23, 42)


def _relative_luminance(r: int, g: int, b: int) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _best_text_for(effective_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    bg = _relative_luminance(*effective_rgb)
    dark = (15, 23, 42)
    on_white = 1.05 / (bg + 0.05)
    on_dark = (bg + 0.05) / (_relative_luminance(*dark) + 0.05)
    return (255, 255, 255) if on_white >= on_dark else dark


def accessible_text_rgb(background_rgba: str, default: tuple[int, int, int] = (15, 23, 42)) -> tuple[int, int, int]:
    """White or near-black, whichever has the higher WCAG contrast ratio on
    the background. Used for the app's severity chips; report rendering keeps
    contrasting_text_rgb() so existing deliverables don't change."""
    parsed = parse_rgba(background_rgba)
    if not parsed:
        return default
    r, g, b, alpha = parsed
    return _best_text_for(composite_on_white(r, g, b, alpha))


# Surface the chips sit on in the app's dark theme (--color-slate-100 under
# .dark). A faded/closed chip is translucent, so its effective colour is the
# palette colour composited over *this* surface rather than over white — and
# the accessible text colour differs accordingly. Solid (open) chips are
# unaffected: at alpha 1 the surface drops out and the result equals the
# light-mode choice.
_DARK_SURFACE = (24, 26, 27)


def accessible_text_on_surface(background_rgba: str, surface: tuple[int, int, int],
                               default: tuple[int, int, int] = (15, 23, 42)) -> tuple[int, int, int]:
    parsed = parse_rgba(background_rgba)
    if not parsed:
        return default
    r, g, b, alpha = parsed
    effective = tuple(round(c * alpha + s * (1 - alpha)) for c, s in zip((r, g, b), surface))
    return _best_text_for(effective)


def mix_with_white(rgba: str, amount: float, default: str = "rgba(241,245,249,1)") -> str:
    parsed = parse_rgba(rgba)
    if not parsed:
        return default
    r, g, b, alpha = parsed
    cr, cg, cb = composite_on_white(r, g, b, alpha)
    mixed = tuple(round(c + (255 - c) * amount) for c in (cr, cg, cb))
    return f"rgba({mixed[0]},{mixed[1]},{mixed[2]},1)"


def darken(rgba: str, amount: float, default: str = "rgba(148,163,184,1)") -> str:
    parsed = parse_rgba(rgba)
    if not parsed:
        return default
    r, g, b, alpha = parsed
    cr, cg, cb = composite_on_white(r, g, b, alpha)
    mixed = tuple(round(c * (1 - amount)) for c in (cr, cg, cb))
    return f"rgba({mixed[0]},{mixed[1]},{mixed[2]},1)"


def severity_rgba(severity: str, variant: str, profile=None) -> str:
    from .assembly import _DEFAULT_SEVERITY_COLORS
    from .models import ReportProfile

    if profile is None:
        profile = ReportProfile.objects.filter(is_default=True).first() or ReportProfile.objects.first()
    defaults = _DEFAULT_SEVERITY_COLORS[severity]
    configured = ((profile.severity_colors if profile else {}) or {}).get(severity) or {}
    return configured.get(variant) or defaults[variant]


def finding_severity_style(finding, profile=None) -> dict:
    variant = "open" if finding.status == finding.Status.OPEN else "closed"
    background = severity_rgba(finding.severity, variant, profile)
    r, g, b = accessible_text_rgb(background)
    dr, dg, db = accessible_text_on_surface(background, _DARK_SURFACE)
    return {
        "background": background,
        "color": f"rgb({r},{g},{b})",
        "dark_color": f"rgb({dr},{dg},{db})",
    }
