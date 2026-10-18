import os
import sqlite3
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "admin.db"
DB_PATH = Path(os.getenv("NTFY_ADMIN_DB_PATH", str(_DEFAULT_DB_PATH)))
def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
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

        connection.execute("""
            CREATE TABLE IF NOT EXISTS demo_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Démo',
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS phones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                ntfy_username TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS interim_workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                ntfy_username TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'closed')),
                decision TEXT NOT NULL DEFAULT 'pending'
                    CHECK (decision IN (
                        'pending', 'extended',
                        'access_reviewed', 'keep_access'
                    )),
                decision_note TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                CHECK (end_date >= start_date)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_interim_workers_end_date
            ON interim_workers(end_date)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS interim_worker_phones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                phone_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE (worker_id, phone_id),
                FOREIGN KEY (worker_id)
                    REFERENCES interim_workers(id) ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_interim_worker_phones_worker
            ON interim_worker_phones(worker_id)
        """)


        # Profil professionnel : séparé du suivi administratif ntfy.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS interim_worker_profiles (
                worker_id INTEGER PRIMARY KEY,
                sectors_json TEXT NOT NULL DEFAULT '[]',
                skills_json TEXT NOT NULL DEFAULT '[]',
                qualifications_json TEXT NOT NULL DEFAULT '[]',
                experience_text TEXT NOT NULL DEFAULT '',
                mobility_area TEXT NOT NULL DEFAULT '',
                mobility_km INTEGER,
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (worker_id)
                    REFERENCES interim_workers(id) ON DELETE CASCADE
            )
        """)

        # Crée un profil vide pour chaque intérimaire déjà enregistré.
        connection.execute("""
            INSERT OR IGNORE INTO interim_worker_profiles (worker_id)
            SELECT id FROM interim_workers
        """)


        # Disponibilités professionnelles, distinctes des dates administratives.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS worker_availabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                period_type TEXT NOT NULL
                    CHECK (period_type IN ('available', 'unavailable')),
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                CHECK (ends_at > starts_at),
                FOREIGN KEY (worker_id)
                    REFERENCES interim_workers(id) ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_worker_availabilities_period
            ON worker_availabilities(worker_id, starts_at, ends_at)
        """)

        # Missions professionnelles proposées par l'administrateur.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS work_missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                client_name TEXT NOT NULL DEFAULT '',
                sector TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                required_workers INTEGER NOT NULL DEFAULT 1
                    CHECK (required_workers >= 1),
                required_qualifications_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN (
                        'draft', 'open', 'filled', 'cancelled', 'completed'
                    )),
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                CHECK (ends_at > starts_at)
            )
        """)

        mission_columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(work_missions)"
            ).fetchall()
        }
        if "client_name" not in mission_columns:
            connection.execute(
                "ALTER TABLE work_missions ADD COLUMN client_name TEXT NOT NULL DEFAULT ''"
            )

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_work_missions_period_status
            ON work_missions(status, starts_at, ends_at)
        """)

        # Affectations d'intérimaires aux missions.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS work_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'assigned'
                    CHECK (status IN ('assigned', 'cancelled', 'completed')),
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE (mission_id, worker_id),
                FOREIGN KEY (mission_id)
                    REFERENCES work_missions(id) ON DELETE CASCADE,
                FOREIGN KEY (worker_id)
                    REFERENCES interim_workers(id) ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_work_assignments_worker_status
            ON work_assignments(worker_id, status)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_work_assignments_mission_status
            ON work_assignments(mission_id, status)
        """)



        # Clients professionnels ; les fiches sont conservées même désactivées.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS professional_clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                sector TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive')),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_professional_clients_status_name
            ON professional_clients(status, company_name)
        """)


        # Comptes applicatifs clients, distincts des comptes de démonstration.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS client_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                professional_client_id INTEGER NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'active', 'disabled')),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (professional_client_id)
                    REFERENCES professional_clients(id) ON DELETE RESTRICT
            )
        """)

        # Formules prédéfinies gérées par l'administrateur.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS client_formulas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive')),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)

        # Catalogue des modules activés pour chaque formule.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS formula_modules (
                formula_id INTEGER NOT NULL,
                module_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (enabled IN (0, 1)),
                PRIMARY KEY (formula_id, module_id),
                FOREIGN KEY (formula_id)
                    REFERENCES client_formulas(id) ON DELETE CASCADE
            )
        """)

        # Historique des formules attribuées aux comptes clients.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS client_formula_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_account_id INTEGER NOT NULL,
                formula_id INTEGER NOT NULL,
                assigned_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                ended_at TEXT,
                FOREIGN KEY (client_account_id)
                    REFERENCES client_accounts(id) ON DELETE RESTRICT,
                FOREIGN KEY (formula_id)
                    REFERENCES client_formulas(id) ON DELETE RESTRICT,
                CHECK (ended_at IS NULL OR ended_at >= assigned_at)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_formula_assignments_current
            ON client_formula_assignments(client_account_id, ended_at)
        """)

        # Brouillons de contrats RMS : stockage privé et participants explicites.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS contract_signature_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                worker_email TEXT NOT NULL,
                agency_signer_name TEXT NOT NULL,
                agency_signer_email TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                storage_filename TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'sent', 'partially_signed', 'signed', 'declined', 'expired', 'failed')),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (mission_id) REFERENCES work_missions(id) ON DELETE RESTRICT,
                FOREIGN KEY (worker_id) REFERENCES interim_workers(id) ON DELETE RESTRICT
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_contract_signature_drafts_created
            ON contract_signature_drafts(created_at DESC)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS contract_signature_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id INTEGER NOT NULL,
                signer_role TEXT NOT NULL CHECK (signer_role IN ('worker', 'agency')),
                signer_name TEXT NOT NULL,
                signer_email TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'signed', 'declined')),
                signed_at TEXT,
                FOREIGN KEY (draft_id) REFERENCES contract_signature_drafts(id) ON DELETE CASCADE,
                UNIQUE (draft_id, signer_role)
            )
        """)

        participant_columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(contract_signature_participants)"
            ).fetchall()
        }
        for column, definition in {
            "token_hash": "TEXT",
            "token_expires_at": "TEXT",
            "signed_name": "TEXT",
            "signed_user_agent": "TEXT",
        }.items():
            if column not in participant_columns:
                connection.execute(
                    f"ALTER TABLE contract_signature_participants ADD COLUMN {column} {definition}"
                )

        # Liens de réponse aux notifications de mission. Seul le hash du jeton
        # est conservé; le jeton brut n'est envoyé qu'au profil concerné.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS mission_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'declined', 'expired', 'revoked')),
                expires_at TEXT NOT NULL,
                responded_at TEXT,
                contract_draft_id INTEGER,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (mission_id) REFERENCES work_missions(id) ON DELETE CASCADE,
                FOREIGN KEY (worker_id) REFERENCES interim_workers(id) ON DELETE CASCADE,
                FOREIGN KEY (contract_draft_id) REFERENCES contract_signature_drafts(id) ON DELETE SET NULL
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_mission_invitations_mission_worker
            ON mission_invitations(mission_id, worker_id, status)
        """)

        connection.commit()
