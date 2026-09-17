from .models import FeatureFlags


def flags(request):
    return {"feature_flags": getattr(request, "feature_flags", None) or FeatureFlags.get_solo()}
