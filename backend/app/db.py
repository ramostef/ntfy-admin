import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "admin.db"

ROLES = (
    "superadmin",
    "account_admin",
    "permission_manager",
    "operator",
    "auditor",
    "encryption_admin",
)


def initialize_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS admin_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK (
                    role IN (
                        'superadmin',
                        'account_admin',
                        'permission_manager',
                        'operator',
                        'auditor',
                        'encryption_admin'
                    )
                ),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_username TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
            ON audit_events(created_at)
        """)

        connection.commit()
