import re
import time
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from db import get_db
from extensions import bcrypt
from auth import api_admin_required, api_login_required

auth_routes = Blueprint('auth_routes', __name__)


@auth_routes.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('pages.dashboard'))
        return redirect(url_for('pages.new_bill'))
    return render_template('login.html')


_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 15 * 60  # 15 minutes


@auth_routes.route('/login', methods=['POST'])
def login_post():
    # --- Lockout check ---
    lockout_until = session.get('lockout_until')
    if lockout_until and time.time() < lockout_until:
        remaining = int((lockout_until - time.time()) / 60) + 1
        return render_template(
            'login.html',
            error=f'Too many failed attempts. Please wait {remaining} minute(s).'
        )

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1",
        (username,)
    ).fetchone()

    if user is None or not bcrypt.check_password_hash(user['password_hash'], password):
        attempts = session.get('login_attempts', 0) + 1
        session['login_attempts'] = attempts
        if attempts >= _MAX_ATTEMPTS:
            session['lockout_until'] = time.time() + _LOCKOUT_SECONDS
            session['login_attempts'] = 0
            return render_template(
                'login.html',
                error='Too many failed attempts. Please wait 15 minutes.'
            )
        return render_template('login.html', error='Invalid username or password')

    # Success — clear attempt counters and set session
    session.pop('login_attempts', None)
    session.pop('lockout_until', None)
    session['user_id']  = user['id']
    session['username'] = user['username']
    session['role']     = user['role']

    if user['role'] == 'admin':
        return redirect(url_for('pages.dashboard'))
    return redirect(url_for('pages.new_bill'))


@auth_routes.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth_routes.login'))


@auth_routes.route('/unauthorized')
def unauthorized():
    return render_template('unauthorized.html')


# ---------------------------------------------------------------------------
# PUT /api/users/me/password
# ---------------------------------------------------------------------------
@auth_routes.route('/api/users/me/password', methods=['PUT'])
@api_login_required
def change_own_password():
    try:
        body = request.get_json(force=True, silent=True) or {}
        current_password = body.get('current_password') or ''
        new_password     = body.get('new_password') or ''
        confirm_password = body.get('confirm_password') or ''

        if not current_password:
            return jsonify({"error": "Current password is required"}), 400
        if len(new_password) < 6:
            return jsonify({"error": "New password must be at least 6 characters"}), 400
        if new_password != confirm_password:
            return jsonify({"error": "Passwords do not match"}), 400

        db = get_db()
        user = db.execute(
            "SELECT id, password_hash FROM users WHERE id = ?",
            (session['user_id'],)
        ).fetchone()

        if not bcrypt.check_password_hash(user['password_hash'], current_password):
            return jsonify({"error": "Current password is incorrect"}), 400

        new_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        db.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (new_hash, session['user_id']),
        )
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------
@auth_routes.route('/api/users', methods=['GET'])
@api_admin_required
def get_users():
    try:
        db = get_db()
        rows = db.execute(
            "SELECT id, username, role, is_active, created_at FROM users ORDER BY id"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/users
# ---------------------------------------------------------------------------
@auth_routes.route('/api/users', methods=['POST'])
@api_admin_required
def create_user():
    try:
        body = request.get_json(force=True, silent=True) or {}
        username = (body.get('username') or '').strip()
        password = body.get('password') or ''
        confirm_password = body.get('confirm_password') or ''
        role = (body.get('role') or '').strip()

        if not username:
            return jsonify({"error": "Username is required"}), 400
        if len(username) < 3:
            return jsonify({"error": "Username must be at least 3 characters"}), 400
        if not re.fullmatch(r'[A-Za-z0-9_]+', username):
            return jsonify({"error": "Username may only contain letters, numbers, and underscores"}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        if password != confirm_password:
            return jsonify({"error": "Passwords do not match"}), 400
        if role not in ('admin', 'staff'):
            return jsonify({"error": "Role must be 'admin' or 'staff'"}), 400

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return jsonify({"error": "Username already taken"}), 409

        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        db.commit()
        row = db.execute(
            "SELECT id, username, role, is_active, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/users/<id>/password
# ---------------------------------------------------------------------------
@auth_routes.route('/api/users/<int:user_id>/password', methods=['PUT'])
@api_admin_required
def change_password(user_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        new_password = body.get('new_password') or ''
        confirm_password = body.get('confirm_password') or ''

        if len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        if new_password != confirm_password:
            return jsonify({"error": "Passwords do not match"}), 400

        db = get_db()
        user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        db.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (password_hash, user_id),
        )
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/users/<id>/toggle-status
# ---------------------------------------------------------------------------
@auth_routes.route('/api/users/<int:user_id>/toggle-status', methods=['PUT'])
@api_admin_required
def toggle_user_status(user_id):
    try:
        if session.get('user_id') == user_id:
            return jsonify({"error": "You cannot deactivate your own account"}), 400

        db = get_db()
        user = db.execute(
            "SELECT id, username, role, is_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Guard: cannot deactivate if it would leave zero active admins
        if user['role'] == 'admin' and user['is_active'] == 1:
            active_admins = db.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()['cnt']
            if active_admins <= 1:
                return jsonify({"error": "Cannot deactivate the last active admin account"}), 400

        new_status = 0 if user['is_active'] == 1 else 1
        db.execute(
            "UPDATE users SET is_active = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (new_status, user_id),
        )
        db.commit()
        updated = db.execute(
            "SELECT id, username, role, is_active, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return jsonify(dict(updated))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
