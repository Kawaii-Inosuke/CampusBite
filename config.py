"""Configuration loaded from environment variables (and .env locally).

Shared by app.py and the seed scripts. Fails fast if a required setting is
missing, and never prints secret values.
"""
import os
import sys

from dotenv import load_dotenv

# Locally this reads .env; on Render there is no .env and the dashboard
# environment variables are used instead.
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
FLASK_ENV = os.environ.get("FLASK_ENV", "production").strip().lower()
IS_PRODUCTION = FLASK_ENV == "production"

# Optional Supabase Storage settings (only needed for image upload).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "").strip() or "menu-images"

# Image upload is enabled only when both URL and service key are present.
UPLOAD_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def public_bucket_prefix():
    """Public URL prefix of the menu-images bucket, or None if not configured."""
    if not SUPABASE_URL:
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/"


def require_settings():
    """Stop the process with a clear message if required settings are missing."""
    missing = [name for name, value in
               (("DATABASE_URL", DATABASE_URL), ("SECRET_KEY", SECRET_KEY)) if not value]
    if missing:
        sys.exit(
            "CampusBite startup error: missing environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env (locally) or set them in the Render dashboard."
        )
