from .models import LicenseKey
from .status import license_status
from .verify import verify_license_key


def license_info(request):
    return {"license_status": license_status(verify_license_key(LicenseKey.get_solo().key_text))}
