#!/usr/bin/env python3
"""
create_users_from_spo2.py

This script creates or updates user_auth entries for all user_ids
present in pulse_sp02_data. It does not require any encryption key.
Passwords will simply be set to the same value as the user_id.
"""

import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

# Configuration
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'app.db'


def main():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ensure user_auth table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_auth';")
    if not cur.fetchone():
        print("user_auth table not found — creating user_auth table.")
        cur.execute('''
            CREATE TABLE user_auth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                plain_pwd TEXT,
                encrypted_pwd TEXT,
                pwd_hash TEXT,
                role TEXT DEFAULT 'user',
                is_private INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.commit()

    # Get all unique user_ids from pulse_sp02_data
    cur.execute("SELECT DISTINCT user_id FROM pulse_sp02_data;")
    user_ids = [row[0] for row in cur.fetchall() if row[0]]

    if not user_ids:
        print("No user IDs found in pulse_sp02_data.")
        return

    created, updated = 0, 0
    for uid in user_ids:
        pwd_hash = generate_password_hash(uid)

        # Check if user exists
        cur.execute("SELECT id FROM user_auth WHERE user_id=?;", (uid,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE user_auth SET plain_pwd=?, encrypted_pwd='', pwd_hash=? WHERE user_id=?;",
                (uid, pwd_hash, uid)
            )
            updated += 1
        else:
            cur.execute(
                "INSERT INTO user_auth (user_id, plain_pwd, encrypted_pwd, pwd_hash, role, is_private) VALUES (?, ?, '', ?, 'user', 0);",
                (uid, uid, pwd_hash)
            )
            created += 1

    conn.commit()
    conn.close()

    print(f"Users created: {created}, updated: {updated}, total processed: {len(user_ids)}")


if __name__ == "__main__":
    main()