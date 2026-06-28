from functools import wraps
from flask import session, redirect, url_for, jsonify


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth_routes.login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth_routes.login'))
        if session.get('role') != 'admin':
            return redirect(url_for('auth_routes.unauthorized'))
        return f(*args, **kwargs)
    return decorated


def staff_or_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth_routes.login'))
        return f(*args, **kwargs)
    return decorated


def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Login required"}), 401
        return f(*args, **kwargs)
    return decorated


def api_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Login required"}), 401
        if session.get('role') != 'admin':
            return jsonify({"error": "Access denied"}), 403
        return f(*args, **kwargs)
    return decorated
