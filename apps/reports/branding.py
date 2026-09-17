from .models import ReportSettings


def get_branding() -> dict:
    settings_obj = ReportSettings.get_solo()
    return {
        "firm_name": settings_obj.firm_name,
        "has_logo": bool(settings_obj.firm_logo),
        "display_name": settings_obj.firm_name or "RedScribe",
    }
