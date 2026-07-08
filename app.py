import os
import subprocess
from urllib.parse import urlparse
from flask import Flask, jsonify, request, session
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from extensions import bcrypt
from db import init_db, seed_default_users, close_db
from routes.customers import customers_bp
from routes.companies import companies_bp
from routes.bills import bills_bp
from routes.cloth_types import cloth_types_bp
from routes.salespersons import salespersons_bp
from routes.analytics import analytics_bp
from routes.export import export_bp
from routes.pages import pages_bp
from routes.auth import auth_routes
from routes.inventory import inventory_bp
from routes.suppliers import suppliers_bp
from routes.invoices import invoices_bp
from routes.institution_bills import inst_bills_bp
from routes.loyalty import loyalty_bp
from db.tailoring import init_tailoring_db, close_tailoring_db
from routes.tailoring import tailoring_api_bp, tailoring_pages_bp

app = Flask(__name__)

# Cache-busting version derived from the current git commit hash.
# Every deploy (git pull + reload) gets a new hash, forcing browsers
# to fetch the latest JS/CSS instead of serving a stale cached copy.
try:
    _ver = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=os.path.dirname(__file__),
        stderr=subprocess.DEVNULL,
    ).decode().strip()
except Exception:
    _ver = "1"
STATIC_VERSION = _ver

# Secret key for signing session cookies. Never fall back to a hardcoded
# value: with a known key anyone can forge an admin session cookie. If the
# env var is missing we use a random per-boot key — the app still works,
# but everyone is logged out on restart, which makes the misconfiguration
# visible instead of silently insecure.
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    import secrets
    _secret = secrets.token_hex(32)
    app.logger.warning(
        "SECRET_KEY is not set — using a random key for this run. "
        "Sessions will not survive a restart. Set SECRET_KEY in .env (see .env.example)."
    )
app.secret_key = _secret

# Public base URL used for shareable bill links sent via WhatsApp.
# Set this to your Cloudflare tunnel URL or PythonAnywhere URL so that
# bill links are clickable for customers on any network.
# Example: 'https://xyz.trycloudflare.com' or 'https://shubhamnx.pythonanywhere.com'
# Leave empty to fall back to the browser's current origin (local network only).
SHARE_BASE_URL = os.environ.get('SHARE_BASE_URL', '').rstrip('/')

# Session cookie settings
app.config['SESSION_PERMANENT'] = False         # session cookie expires when browser closes
app.config['SESSION_COOKIE_HTTPONLY'] = True    # JS cannot read the cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Protects against CSRF
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Static files are cache-busted with ?v=<git hash> (see STATIC_VERSION above),
# so browsers may cache them freely — Flask's default max age applies.

# Initialize bcrypt
bcrypt.init_app(app)

# Close the per-request DB connections after each request/appcontext teardown
app.teardown_appcontext(close_db)
app.teardown_appcontext(close_tailoring_db)

# Ensure tables exist and seed defaults on every startup
init_db()
seed_default_users(bcrypt)
init_tailoring_db()  # separate tailoring.db for the tailoring delivery system

@app.template_filter("format_date")
def format_date_filter(date_str):
    if not date_str:
        return ""
    try:
        from datetime import datetime
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return d.strftime("%d %b %Y")
    except Exception:
        return str(date_str)


@app.context_processor
def inject_globals():
    return {
        'share_base_url': SHARE_BASE_URL,
        'sv': STATIC_VERSION,
        'current_user': {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'role': session.get('role'),
            'is_admin': session.get('role') == 'admin',
            'is_staff': session.get('role') == 'staff',
        }
    }


@app.before_request
def reject_cross_origin_writes():
    """Lightweight CSRF guard on top of SameSite=Lax: browsers always send
    an Origin header on cross-site state-changing requests, so reject any
    write whose Origin doesn't match the host we're being served on.
    Requests without an Origin header (curl, same-origin navigations in
    older browsers) are allowed through."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return jsonify({"error": "Cross-origin request rejected"}), 403


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# Register blueprints
app.register_blueprint(auth_routes)
app.register_blueprint(customers_bp, url_prefix="/api")
app.register_blueprint(companies_bp, url_prefix="/api")
app.register_blueprint(bills_bp, url_prefix="/api")
app.register_blueprint(cloth_types_bp, url_prefix="/api")
app.register_blueprint(salespersons_bp, url_prefix="/api")
app.register_blueprint(analytics_bp,   url_prefix="/api")
app.register_blueprint(export_bp,      url_prefix="/api")
app.register_blueprint(inventory_bp,   url_prefix="/api")
app.register_blueprint(suppliers_bp,   url_prefix="/api")
app.register_blueprint(invoices_bp,    url_prefix="/api")
app.register_blueprint(inst_bills_bp,  url_prefix="/api")
app.register_blueprint(loyalty_bp,     url_prefix="/api")
app.register_blueprint(tailoring_api_bp, url_prefix="/api")
app.register_blueprint(tailoring_pages_bp)
app.register_blueprint(pages_bp)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8081, debug=False)
