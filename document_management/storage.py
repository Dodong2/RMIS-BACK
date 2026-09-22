import requests
from django.conf import settings


def _headers(content_type=None):
    headers = {"Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def upload_document(file_obj, path):
    """Upload a file to the private Supabase Storage bucket. Returns the storage path."""
    resp = requests.post(
        f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_STORAGE_BUCKET}/{path}",
        headers=_headers(file_obj.content_type or "application/octet-stream"),
        data=file_obj.read(),
    )
    resp.raise_for_status()
    return path


def get_signed_url(path, expires_in=3600):
    """Return a short-lived signed URL for downloading a private document."""
    resp = requests.post(
        f"{settings.SUPABASE_URL}/storage/v1/object/sign/{settings.SUPABASE_STORAGE_BUCKET}/{path}",
        headers=_headers(),
        json={"expiresIn": expires_in},
    )
    resp.raise_for_status()
    return f"{settings.SUPABASE_URL}/storage/v1{resp.json()['signedURL']}"
