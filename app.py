import os
from flask import Flask, render_template, session, redirect, url_for, request
from functools import wraps
from extensions import bcrypt
from database import init_db, seed_default_users, get_db
from auth import login_required, admin_required, staff_or_admin_required
from routes.customers import customers_bp
from routes.companies import companies_bp
from routes.bills import bills_bp
from routes.cloth_types import cloth_types_bp
from routes.salespersons import salespersons_bp
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


# Page routes
@app.route("/")
@admin_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/new-bill")
@staff_or_admin_required
def new_bill():
    return render_template("new_bill.html")


@app.route("/bill-history")
@admin_required
def bill_history():
    return render_template("bill_history.html")


@app.route("/bills/<int:bill_id>")
@admin_required
def bill_detail(bill_id):
    return render_template("bill_detail.html", bill_id=bill_id)


@app.route("/edit-bill/<int:bill_id>")
@admin_required
def edit_bill(bill_id):
    return render_template("edit_bill.html", bill_id=bill_id)


@app.route("/customers")
@admin_required
def customers():
    return render_template("customers.html")


@app.route("/customers/<int:customer_id>")
@admin_required
def customer_detail(customer_id):
    return render_template("customer_detail.html", customer_id=customer_id)


@app.route("/admin/users")
@admin_required
def admin_users():
    return render_template("admin_users.html")


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")


def get_bill_by_number(bill_number):
    db   = get_db()
    bill = db.execute(
        "SELECT * FROM bills WHERE bill_number = ?", (bill_number,)
    ).fetchone()
    if not bill:
        return None
    items = db.execute(
        "SELECT * FROM bill_items WHERE bill_id = ? ORDER BY id", (bill["id"],)
    ).fetchall()
    payments = db.execute(
        "SELECT * FROM bill_payments WHERE bill_id = ? ORDER BY id", (bill["id"],)
    ).fetchall()
    return {
        "bill":     dict(bill),
        "items":    [dict(i) for i in items],
        "payments": [dict(p) for p in payments],
    }


@app.route("/bill/share/<bill_number>")
def shared_bill(bill_number):
    data = get_bill_by_number(bill_number)
    if not data:
        return render_template("shared_bill_not_found.html", bill_number=bill_number), 404
    return render_template(
        "shared_bill.html",
        bill=data["bill"],
        items=data["items"],
        payments=data["payments"],
    )


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8081, debug=False)
