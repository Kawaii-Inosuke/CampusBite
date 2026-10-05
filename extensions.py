"""Flask extensions created once and shared by app.py and the route files.

They live here (not in app.py) so route files can use them without importing
app.py, which would create a circular import.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()  # CSRF check on every POST (forms and fetch() requests)
limiter = Limiter(get_remote_address, storage_uri="memory://")
