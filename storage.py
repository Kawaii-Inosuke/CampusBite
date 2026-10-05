"""Optional upload of menu images to Supabase Storage via its REST API.

Only used when SUPABASE_URL and SUPABASE_SERVICE_KEY are set. The service key
stays on the server and is never sent to the browser. Uses only the standard
library, so no extra dependency is needed.
"""
import re
import secrets
import urllib.error
import urllib.request

import config

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_BYTES = 2 * 1024 * 1024  # 2 MB


class UploadError(Exception):
    pass


def _detect_type(data):
    """Check the file's magic bytes instead of trusting the browser's content type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def upload_menu_image(file_storage, item_name):
    """Upload a Werkzeug FileStorage to the bucket and return its public URL."""
    data = file_storage.read(MAX_BYTES + 1)
    if not data:
        raise UploadError("The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadError("Image must be 2 MB or smaller.")
    content_type = _detect_type(data)
    if content_type not in ALLOWED_TYPES:
        raise UploadError("Only JPEG, PNG or WebP images are allowed.")

    # Safe file name: slug of the item name + random suffix (never the user's file name).
    slug = re.sub(r"[^a-z0-9]+", "-", item_name.lower()).strip("-")[:40] or "item"
    object_name = f"{slug}-{secrets.token_hex(4)}.{ALLOWED_TYPES[content_type]}"

    url = f"{config.SUPABASE_URL}/storage/v1/object/{config.SUPABASE_BUCKET}/{object_name}"
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Content-Type": content_type,
        "x-upsert": "false",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status not in (200, 201):
                raise UploadError("Image upload failed.")
    except urllib.error.HTTPError as e:
        # Log only the status code, never the key or headers.
        raise UploadError(f"Image upload failed (storage returned HTTP {e.code}).") from None
    except urllib.error.URLError:
        raise UploadError("Could not reach Supabase Storage.") from None

    return config.public_bucket_prefix() + object_name
