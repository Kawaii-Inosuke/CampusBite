"""CampusBite: multi-shop canteen pre-order and token system (Flask).

Run locally:   python app.py          (uses FLASK_ENV from .env)
Production:    gunicorn app:app       (Render start command)

The routes are split into four files:
  app.py      setup, security settings, landing page, login/register/logout, errors
  student.py  shops list, shop menu, cart, ordering, order tracking   (role: student)
  manager.py  one shop's order queue, menu and Open/Closed toggle     (role: manager)
  owner.py    add/deactivate/delete shops, create managers            (role: owner)
"""
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
import psycopg2.errors

import config
from db import dict_cursor, get_db
from extensions import csrf, limiter
from helpers import EMAIL_RE, HOME_ENDPOINT, clean_text, password_error

# ---------------------------------------------------------------------------
# 1. App setup and security settings
# ---------------------------------------------------------------------------
config.require_settings()  # fail fast if DATABASE_URL or SECRET_KEY is missing

app = Flask(__name__)
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    # Secure cookies only in production; on http://localhost a Secure cookie
    # would never be sent back and login would silently fail.
    SESSION_COOKIE_SECURE=config.IS_PRODUCTION,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=8 * 60 * 60,  # 8 hours
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,      # rejects oversized uploads early
    WTF_CSRF_TIME_LIMIT=None,                # token valid for the whole session
)

# Render sits behind a proxy: trust one hop for the client IP and http/https.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

csrf.init_app(app)     # CSRF check on every POST (forms and fetch() requests)
limiter.init_app(app)  # rate limits (login, register, cart API)


@app.before_request
def force_https():
    """Security rule 1: redirect plain http to https in production."""
    if config.IS_PRODUCTION and request.headers.get("X-Forwarded-Proto") == "http":
        return redirect(request.url.replace("http://", "https://", 1), code=301)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


@app.context_processor
def template_globals():
    cart = session.get("cart") or {}
    return {
        "cart_count": sum((cart.get("items") or {}).values()),
        "current_role": session.get("role"),
        "current_name": session.get("name"),
    }


# ---------------------------------------------------------------------------
# 2. Landing page and authentication
# ---------------------------------------------------------------------------
# The three login forms. Each one only accepts its own role.
LOGIN_KINDS = {
    "student": {"role": "student", "title": "Student login",
                "subtitle": "Order food from campus shops and track your token."},
    "staff": {"role": "manager", "title": "Staff login",
              "subtitle": "For shop managers: order queue and menu."},
    "owner": {"role": "owner", "title": "Owner login",
              "subtitle": "Manage shops and shop managers."},
}


@app.route("/")
def index():
    """Logged out: landing page with Student / Staff cards. Logged in: own dashboard."""
    role = session.get("role")
    if role in HOME_ENDPOINT:
        return redirect(url_for(HOME_ENDPOINT[role]))
    session.clear()  # unknown/legacy role in an old cookie: start fresh
    return render_template("landing.html")


@app.route("/health")
def health():
    """Uptime ping endpoint. Does not touch the DB so it stays fast."""
    return jsonify(status="ok"), 200


@app.route("/login")
def login_redirect():
    """Old single login URL: send people to the landing page to pick a form."""
    return redirect(url_for("index"))


@app.route("/login/<kind>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])  # one shared limit for all 3 forms
def login(kind):
    form = LOGIN_KINDS.get(kind)
    if not form:
        abort(404)
    if request.method == "GET":
        return render_template("login.html", kind=kind, form=form)

    email = clean_text(request.form.get("email"), 254).lower()
    password = request.form.get("password") or ""
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select id, name, password_hash, role from users where email = %s",
                    (email,))
        user = cur.fetchone()

    # Wrong password, unknown email AND an account of another role all get the
    # same generic message, so the form never reveals which part was wrong.
    if (not user or user["role"] != form["role"]
            or not check_password_hash(user["password_hash"], password)):
        flash("Invalid email or password.", "error")
        return render_template("login.html", kind=kind, form=form, email=email), 401

    session.clear()  # drop any old session data (and cart) before logging in
    session.permanent = True
    session.update(user_id=user["id"], name=user["name"], role=user["role"])
    return redirect(url_for(HOME_ENDPOINT[user["role"]]))


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = clean_text(request.form.get("name"), 100)
    email = clean_text(request.form.get("email"), 254).lower()
    password = request.form.get("password") or ""
    # Any "role" or "shop_id" field in the form is deliberately ignored (rule 3).

    errors = []
    if not name:
        errors.append("Name is required.")
    if not EMAIL_RE.match(email):
        errors.append("Enter a valid email address.")
    if password_error(password):
        errors.append(password_error(password))
    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("register.html", name=name, email=email), 400

    try:
        with get_db() as conn, conn.cursor() as cur:
            # role is hard-coded: registration can only ever create students.
            cur.execute(
                "insert into users (name, email, password_hash, role) "
                "values (%s, %s, %s, 'student')",
                (name, email, generate_password_hash(password)),
            )
    except psycopg2.errors.UniqueViolation:
        flash("An account with this email already exists. Please log in.", "error")
        return render_template("register.html", name=name, email=email), 400

    flash("Account created. Please log in.", "success")
    return redirect(url_for("login", kind="student"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# 3. Role areas (imported here so they can use `app`-level settings above)
# ---------------------------------------------------------------------------
from student import bp as student_bp  # noqa: E402
from manager import bp as manager_bp  # noqa: E402
from owner import bp as owner_bp      # noqa: E402

app.register_blueprint(student_bp)
app.register_blueprint(manager_bp)
app.register_blueprint(owner_bp)


# ---------------------------------------------------------------------------
# 4. Error handlers
# ---------------------------------------------------------------------------
def wants_json():
    return request.path.startswith("/api/")


@app.errorhandler(CSRFError)
def csrf_error(e):
    if wants_json():
        return jsonify(ok=False, error="Your session expired. Refresh the page and try again."), 400
    return render_template("error.html", code=400,
                           message="Your form expired. Go back, refresh and try again."), 400


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(429)
def http_error(e):
    messages = {
        400: "Bad request.",
        403: "You do not have permission to open this page.",
        404: "Page not found.",
        413: "File too large.",
        429: "Too many attempts. Please wait a minute and try again.",
    }
    if wants_json():
        return jsonify(ok=False, error=messages[e.code]), e.code
    return render_template("error.html", code=e.code, message=messages[e.code]), e.code


@app.errorhandler(500)
def server_error(e):
    # Generic message only: no stack trace or connection details to the user.
    return render_template("error.html", code=500,
                           message="Something went wrong. Please try again."), 500


if __name__ == "__main__":
    # Debug mode only for local development, never in production (rule 16).
    app.run(host="127.0.0.1", port=5000, debug=not config.IS_PRODUCTION)
