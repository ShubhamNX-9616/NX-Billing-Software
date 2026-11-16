import os
import secrets

from db.connection import _open_connection


def _initial_password(env_name):
    """Password for a first-run account: the one set in .env if there is one,
    otherwise a fresh random one. Returns (password, was_generated).

    These used to be fixed values written in this public repository (and its README),
    so anyone could try them on a live site whose owner had not changed them yet."""
    configured = os.environ.get(env_name, "").strip()
    if configured:
        return configured, False
    return secrets.token_urlsafe(9), True


def seed_default_users(bcrypt):
    conn = _open_connection()
    try:
        if conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"] > 0:
            return
        defaults = [
            ("admin", "INITIAL_ADMIN_PASSWORD", "admin"),
            ("staff", "INITIAL_STAFF_PASSWORD", "staff"),
        ]
        generated = []
        for username, env_name, role in defaults:
            plain_password, was_generated = _initial_password(env_name)
            password_hash = bcrypt.generate_password_hash(plain_password).decode("utf-8")
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
            if was_generated:
                generated.append((username, plain_password))
        conn.commit()
        print("First-run accounts created: admin and staff.")
        if generated:
            print("Sign-in details (shown only this once - note them down and change them after logging in):")
            for username, plain_password in generated:
                print(f"  {username:<6} password: {plain_password}")
        else:
            print("Their passwords are the ones set in .env (INITIAL_ADMIN_PASSWORD / INITIAL_STAFF_PASSWORD).")
        print("  IMPORTANT: change these passwords after first login (My Profile).")
    finally:
        conn.close()
