from db.connection import _open_connection


def seed_default_users(bcrypt):
    conn = _open_connection()
    try:
        if conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"] > 0:
            return
        defaults = [
            ("admin", "Admin@1234", "admin"),
            ("staff", "Staff@1234", "staff"),
        ]
        for username, plain_password, role in defaults:
            password_hash = bcrypt.generate_password_hash(plain_password).decode("utf-8")
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
        conn.commit()
        print("Default users created:")
        print("  Admin  — username: admin   password: Admin@1234")
        print("  Staff  — username: staff   password: Staff@1234")
        print("  IMPORTANT: Change these passwords after first login!")
    finally:
        conn.close()
