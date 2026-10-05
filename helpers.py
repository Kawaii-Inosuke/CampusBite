"""Small helpers shared by all route files: role checks and input validation."""
import re
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import abort, jsonify, redirect, request, session, url_for

import config

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_QTY = 10
ROLES = ("student", "manager", "owner")

# Where each role lands after login, and which login page it uses.
HOME_ENDPOINT = {"student": "student.shops", "manager": "manager.orders", "owner": "owner.dashboard"}


def role_required(role):
    """Server-side check of login and role on every protected route (rule 4).

    Not logged in -> redirect to the landing page (401 JSON for /api/ routes).
    Wrong role    -> 403.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            is_api = request.path.startswith("/api/")
            if "user_id" not in session:
                if is_api:
                    return jsonify(error="login required"), 401
                return redirect(url_for("index"))
            if session.get("role") != role:
                if is_api:
                    return jsonify(error="forbidden"), 403
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def clean_text(value, max_len):
    """Trim and length-limit free text. Returns '' when missing."""
    return (value or "").strip()[:max_len]


def parse_int(value, low=None, high=None):
    """Parse a form value as an integer in [low, high]; None if invalid."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def parse_price(value):
    """Price as Decimal with at most 2 decimals, 0 to 99999.99; None if invalid."""
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price < 0 or price > Decimal("99999.99") \
            or price != price.quantize(Decimal("0.01")):
        return None
    return price


def password_error(password):
    """Return an error message if the password is not acceptable, else None."""
    if not 8 <= len(password) <= 128:
        return "Password must be 8 to 128 characters."
    return None


def valid_image_url(url):
    """Data rule: image URLs must point to our bucket (photos are optional)."""
    if url == "":
        return True
    prefix = config.public_bucket_prefix()
    if prefix:
        return url.startswith(prefix)
    # No Supabase configured yet: accept any https URL so the app is still usable.
    return url.startswith("https://")
