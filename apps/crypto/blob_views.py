import io
import uuid

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError

from .access import engagement_access_required
from .models import EncryptedBlob
from .services import decrypt_bytes, encrypt_bytes, record_aad

ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 64_000_000

_PIL_FORMAT_TO_CONTENT_TYPE = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


@require_POST
@engagement_access_required
def blob_upload(request, engagement_id):
    upload = request.FILES.get("file")
    if upload is None:
        return HttpResponseBadRequest("No file provided.")
    if upload.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return HttpResponseBadRequest("Unsupported content type.")
    if upload.size > MAX_UPLOAD_BYTES:
        return HttpResponseBadRequest("File too large (10MB limit).")

    plaintext = upload.read()
    try:
        with Image.open(io.BytesIO(plaintext)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(plaintext)) as probe:
            detected_content_type = _PIL_FORMAT_TO_CONTENT_TYPE.get(probe.format)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        detected_content_type = None
    if detected_content_type is None:
        return HttpResponseBadRequest("File content doesn't match a supported image format.")

    blob_id = uuid.uuid4()
    blob = EncryptedBlob.objects.create(
        id=blob_id,
        engagement=request.engagement,
        content_type=detected_content_type,
        original_filename=upload.name[:255],
        ciphertext=encrypt_bytes(
            plaintext, request.project_key, associated_data=record_aad("encryptedblob", blob_id, "ciphertext"),
        ),
        uploaded_by=request.user,
    )
    url = reverse("crypto:blob_serve", args=[engagement_id, blob.id])
    return JsonResponse({"url": url})


@require_GET
@engagement_access_required
def blob_serve(request, engagement_id, blob_id):
    blob = get_object_or_404(EncryptedBlob, pk=blob_id, engagement=request.engagement)
    plaintext = decrypt_bytes(
        bytes(blob.ciphertext), request.project_key,
        associated_data=record_aad("encryptedblob", blob.id, "ciphertext"),
    )
    response = HttpResponse(plaintext, content_type=blob.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    return response
