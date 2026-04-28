import os
from flask import Flask, session
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

app = Flask(__name__)

# Secret key for signing session cookies
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')

# Public base URL used for shareable bill links sent via WhatsApp.
# Set this to your Cloudflare tunnel URL or PythonAnywhere URL so that
# bill links are clickable for customers on any network.
# Example: 'https://xyz.trycloudflare.com' or 'https://shubhamnx.pythonanywhere.com'
# Leave empty to fall back to the browser's current origin (local network only).
SHARE_BASE_URL = os.environ.get('SHARE_BASE_URL', 'https://shubhamnxtailoring.pythonanywhere.com').rstrip('/')

# Session cookie settings
app.config['SESSION_PERMANENT'] = False         # session cookie expires when browser closes
app.config['SESSION_COOKIE_HTTPONLY'] = True    # JS cannot read the cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Protects against CSRF
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Initialize bcrypt
bcrypt.init_app(app)

# Close the per-request DB connection after each request/appcontext teardown
app.teardown_appcontext(close_db)

# Ensure tables exist and seed defaults on every startup
init_db()
seed_default_users(bcrypt)

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
        'current_user': {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'role': session.get('role'),
            'is_admin': session.get('role') == 'admin',
            'is_staff': session.get('role') == 'staff',
        }
    }


# Register blueprints
app.register_blueprint(auth_routes)
app.register_blueprint(customers_bp, url_prefix="/api")
app.register_blueprint(companies_bp, url_prefix="/api")
app.register_blueprint(bills_bp, url_prefix="/api")
app.register_blueprint(cloth_types_bp, url_prefix="/api")
app.register_blueprint(salespersons_bp, url_prefix="/api")
app.register_blueprint(analytics_bp,   url_prefix="/api")
app.register_blueprint(export_bp,      url_prefix="/api")
app.register_blueprint(pages_bp)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8081, debug=False)
