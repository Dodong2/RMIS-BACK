import requests
from django.conf import settings


def _headers(content_type=None):
    # Supabase's gateway requires both apikey (identifies the project/key) and
    # Authorization (the actual credential) - Authorization alone 403s.
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def upload_document(file_obj, path, content_type):
    """Upload a file to the private Supabase Storage bucket. Returns the storage path. The bucket has its own
    allowed-MIME list, so content_type must be one it accepts (see serializers.ALLOWED_FILE_TYPES)."""
    resp = requests.post(
        f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_STORAGE_BUCKET}/{path}",
        headers=_headers(content_type),
        data=file_obj.read(),
    )
    resp.raise_for_status()
    return path


def move_document(source, destination):
    """Move an object inside the bucket (used to promote a staged upload to its final project path)."""
    resp = requests.post(
        f"{settings.SUPABASE_URL}/storage/v1/object/move",
        headers=_headers(),
        json={"bucketId": settings.SUPABASE_STORAGE_BUCKET, "sourceKey": source, "destinationKey": destination},
    )
    resp.raise_for_status()
    return destination


def get_signed_url(path, expires_in=3600):
    """Return a short-lived signed URL for downloading a private document."""
    resp = requests.post(
        f"{settings.SUPABASE_URL}/storage/v1/object/sign/{settings.SUPABASE_STORAGE_BUCKET}/{path}",
        headers=_headers(),
        json={"expiresIn": expires_in},
    )
    resp.raise_for_status()
    return f"{settings.SUPABASE_URL}/storage/v1{resp.json()['signedURL']}"


def list_objects(prefix=""):
    """Every object path in the bucket under prefix, walking folders (used by cleanup_fresh_start)."""
    paths, offset = [], 0
    while True:
        resp = requests.post(
            f"{settings.SUPABASE_URL}/storage/v1/object/list/{settings.SUPABASE_STORAGE_BUCKET}",
            headers=_headers("application/json"),
            json={"prefix": prefix, "limit": 1000, "offset": offset},
        )
        resp.raise_for_status()
        items = resp.json()
        for item in items:
            path = f"{prefix}{item['name']}"
            if item.get("id") is None:  # a folder has no id
                paths += list_objects(f"{path}/")
            else:
                paths.append(path)
        if len(items) < 1000:
            return paths
        offset += 1000


def delete_objects(paths):
    """Permanently delete these objects from the bucket."""
    for start in range(0, len(paths), 1000):
        resp = requests.delete(
            f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_STORAGE_BUCKET}",
            headers=_headers("application/json"),
            json={"prefixes": paths[start:start + 1000]},
        )
        resp.raise_for_status()


def delete_documents(paths):
    """Remove objects from the bucket (Task 15, 2026-10-30: the files of a deleted Draft project)."""
    resp = requests.delete(
        f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_STORAGE_BUCKET}",
        headers=_headers(),
        json={"prefixes": paths},
    )
    resp.raise_for_status()
