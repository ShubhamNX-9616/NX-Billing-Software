import hashlib
from functools import wraps
from flask import session, redirect, url_for, jsonify, request

from db import get_db


def password_fingerprint(password_hash):
    """Short, non-reversible stamp of the current password. A session remembers the
    stamp it logged in with; once the password changes the stamp no longer matches
    and the session ends (see check_session_valid)."""
    return hashlib.sha256(str(password_hash).encode("utf-8")).hexdigest()[:16]


def check_session_valid():
    """before_request guard: a login stays valid only while the account does.

    A session is a signed cookie that used to be believed for as long as the
    browser stayed open, so deactivating a user, changing their role or resetting
    their password had no effect on a device that was already signed in - a
    dismissed employee kept working until they closed the browser. Now, on every
    request that carries a login:
      - the user must still exist and be active, else the session is ended;
      - the password must be the one the session signed in with (an admin reset or
        the user's own change signs out their other devices);
      - the role and username are refreshed from the account, so a role change
        applies at once.
    Sessions created before this check existed carry no stamp; they are accepted and
    stamped on first sight so nobody is signed out by the upgrade itself."""
    if request.endpoint in (None, "static", "health"):
        return None
    user_id = session.get("user_id")
    if user_id is None:
        return None

    row = get_db().execute(
        "SELECT username, role, is_active, password_hash FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    valid = row is not None and bool(row["is_active"])
    if valid:
        stamp = password_fingerprint(row["password_hash"])
        if "pwf" not in session:
            session["pwf"] = stamp
        elif session["pwf"] != stamp:
            valid = False
    if not valid:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "Your session has ended. Please sign in again."}), 401
        return redirect(url_for("auth_routes.login"))

    if session.get("role") != row["role"]:
        session["role"] = row["role"]
    if session.get("username") != row["username"]:
        session["username"] = row["username"]
    return None


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
        if session.get('role') not in ('admin', 'staff'):
            return redirect(url_for('auth_routes.unauthorized'))
        return f(*args, **kwargs)
    return decorated


def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Login required"}), 401
        return f(*args, **kwargs)
    return decorated


def api_staff_or_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Login required"}), 401
        if session.get('role') not in ('admin', 'staff'):
            return jsonify({"error": "Access denied"}), 403
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
