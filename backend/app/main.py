import os
import subprocess
import re
import json
import base64
import hashlib
import secrets
import unicodedata
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.db import get_connection, initialize_database

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PASSWORD_HASH = os.getenv("NTFY_ADMIN_PASSWORD_HASH")
SESSION_SECRET = os.getenv("NTFY_ADMIN_SESSION_SECRET")
DEMO_MODE = os.getenv("RMS_DEMO_MODE", "0").strip() == "1"
SESSION_USER = os.getenv("NTFY_ADMIN_SESSION_USER", "admin").strip() or "admin"
COOKIE_SECURE = os.getenv("NTFY_ADMIN_COOKIE_SECURE", "0").strip() == "1"

if not PASSWORD_HASH or not SESSION_SECRET:
    raise RuntimeError("Configuration administrateur absente du fichier .env")

COOKIE_NAME = os.getenv("NTFY_ADMIN_COOKIE_NAME", "ntfy_admin_session").strip()
SESSION_MAX_AGE = 1800  # 30 minutes
password_hasher = PasswordHash.recommended()
serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="ntfy-admin-session")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="ntfy-admin API", version="0.4.0", lifespan=lifespan)


class LoginRequest(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class ContractSignatureDraftCreate(BaseModel):
    mission_id: int = Field(gt=0)
    worker_id: int = Field(gt=0)
    accepted_invitation_id: int | None = Field(default=None, gt=0)
    worker_email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    agency_signer_name: str = Field(min_length=1, max_length=150)
    agency_signer_email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    original_filename: str = Field(min_length=1, max_length=255)
    pdf_base64: str = Field(min_length=20, max_length=14_000_000)


class AccountCreate(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    role: str = Field(min_length=1, max_length=40)


def require_admin(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Authentification requise")

    try:
        session = serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")

    if session != {"user": SESSION_USER}:
        raise HTTPException(status_code=401, detail="Session invalide")

    return True


@app.get("/")
def home():
    return {"message": "ntfy-admin API", "version": app.version}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ntfy/health")
def ntfy_health(_admin: bool = Depends(require_admin)):
    base_url = os.getenv(
        "NTFY_BASE_URL",
        "https://ntfy-pc-home.duckdns.org",
    ).rstrip("/")

    try:
        with urlopen(f"{base_url}/v1/health", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))

        if response.status == 200 and data.get("healthy") is True:
            return {"status": "online"}

    except (URLError, TimeoutError, OSError, ValueError):
        pass

    return {"status": "offline"}


@app.post("/login")
def login(data: LoginRequest, response: Response):
    try:
        user_matches = data.username == "demo" if DEMO_MODE else data.username in (None, SESSION_USER)
        valid = user_matches and password_hasher.verify(data.password, PASSWORD_HASH)
    except Exception:
        valid = False

    if not valid:
        raise HTTPException(status_code=401, detail="Mot de passe incorrect")

    token = serializer.dumps({"user": SESSION_USER})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return {"authenticated": True}


@app.get("/me")
def me(_admin: bool = Depends(require_admin)):
    return {"authenticated": True, "user": SESSION_USER}


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
    return {"authenticated": False}


@app.get("/accounts")
def list_accounts(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, username, role, status, created_at
            FROM demo_accounts
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/accounts", status_code=201)
def create_account(
    account: AccountCreate,
    _admin: bool = Depends(require_admin),
):
    username = account.username.strip()
    role = account.role.strip()

    if not username or not role:
        raise HTTPException(status_code=422, detail="Nom et rôle obligatoires")

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO demo_accounts (username, role)
                VALUES (?, ?)
                """,
                (username, role),
            )
            row = connection.execute(
                """
                SELECT id, username, role, status, created_at
                FROM demo_accounts
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row)
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="Ce compte existe déjà")
        raise


@app.get("/ntfy/accounts")
def list_real_ntfy_accounts(_admin: bool = Depends(require_admin)):
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/ntfy-admin-list-users"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=503,
            detail="Délai dépassé lors de la lecture des comptes ntfy",
        )
    except OSError:
        raise HTTPException(
            status_code=503,
            detail="Impossible de lancer la commande de lecture ntfy",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail="Impossible de lire les comptes ntfy",
        )

    accounts = []
    current = None

    for line in result.stdout.splitlines():
        match = re.match(
            r"^user (.+) \(role: ([^,]+), tier: ([^)]+)\)$",
            line.strip(),
        )

        if match:
            if current is not None:
                accounts.append(current)

            current = {
                "username": match.group(1),
                "role": match.group(2),
                "tier": match.group(3),
                "permissions": [],
            }
            continue

        if current is None:
            continue

        permission = line.strip().removeprefix("- ").strip()
        if permission:
            current["permissions"].append(permission)

    if current is not None:
        accounts.append(current)

    return [
    account for account in accounts
    if account["username"] != "*"
]


# --- Gestion des comptes ntfy réels ---

class NtfyAccountCreate(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=12, max_length=1024)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


class NtfyPasswordChange(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class NtfyRoleChange(BaseModel):
    role: str = Field(pattern=r"^(user|admin)$")


class NtfyPermissionChange(BaseModel):
    topic: str = Field(min_length=1, max_length=64)
    permission: str = Field(pattern=r"^(read-write|read-only|write-only|deny)$")


def run_ntfy_manage(args: list[str], password: str | None = None):
    if password is not None and ("\n" in password or "\r" in password):
        raise HTTPException(status_code=422, detail="Mot de passe invalide")

    command = [
        "sudo", "-n", "/usr/local/sbin/ntfy-admin-manage", *args
    ]

    try:
        result = subprocess.run(
            command,
            input=(password + "\n") if password is not None else None,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=503, detail="Opération ntfy trop longue")
    except OSError:
        raise HTTPException(status_code=503, detail="Commande ntfy indisponible")

    if result.returncode != 0:
        # Ne pas exposer les détails internes de la commande au navigateur.
        raise HTTPException(
            status_code=400,
            detail="Opération refusée ou impossible. Vérifie le nom et les paramètres.",
        )

    return {"ok": True, "message": "Opération effectuée"}


def validate_managed_username(username: str):
    if (
        not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", username)
        or username == "admin"
        or username == "*"
    ):
        raise HTTPException(
            status_code=400,
            detail="Nom de compte invalide ou compte protégé",
        )


def validate_managed_topic(topic: str):
    if topic != "tous-les-telephones" and not re.fullmatch(r"tel-[0-9]{3}", topic):
        raise HTTPException(
            status_code=400,
            detail="Sujet non autorisé par le tableau de bord",
        )


@app.post("/ntfy/accounts", status_code=201)
def create_ntfy_account(
    data: NtfyAccountCreate,
    _admin: bool = Depends(require_admin),
):
    username = data.username.strip()
    validate_managed_username(username)

    if data.role == "admin":
        # Création d'un administrateur possible uniquement par action explicite.
        pass

    result = run_ntfy_manage(
        ["add", username, data.role],
        password=data.password,
    )

    return {"username": username, "role": data.role, **result}


@app.delete("/ntfy/accounts/{username}")
def delete_ntfy_account(
    username: str,
    _admin: bool = Depends(require_admin),
):
    validate_managed_username(username)
    return run_ntfy_manage(["delete", username])


@app.put("/ntfy/accounts/{username}/password")
def change_ntfy_password(
    username: str,
    data: NtfyPasswordChange,
    _admin: bool = Depends(require_admin),
):
    validate_managed_username(username)
    return run_ntfy_manage(
        ["change-pass", username],
        password=data.password,
    )


@app.put("/ntfy/accounts/{username}/role")
def change_ntfy_role(
    username: str,
    data: NtfyRoleChange,
    _admin: bool = Depends(require_admin),
):
    validate_managed_username(username)
    return run_ntfy_manage(["change-role", username, data.role])


@app.put("/ntfy/accounts/{username}/permissions")
def change_ntfy_permission(
    username: str,
    data: NtfyPermissionChange,
    _admin: bool = Depends(require_admin),
):
    validate_managed_username(username)
    validate_managed_topic(data.topic)
    return run_ntfy_manage(
        ["access", username, data.topic, data.permission]
    )


# --- Inventaire des téléphones ---

class PhoneCreate(BaseModel):
    phone_id: str = Field(
        min_length=7,
        max_length=7,
        pattern=r"^tel-[0-9]{3}$",
    )
    name: str = Field(min_length=1, max_length=100)
    ntfy_username: str | None = Field(default=None, max_length=32)
    status: str = Field(default="active", pattern=r"^(active|disabled)$")
    notes: str | None = Field(default=None, max_length=1000)


class PhoneUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ntfy_username: str | None = Field(default=None, max_length=32)
    status: str = Field(pattern=r"^(active|disabled)$")
    notes: str | None = Field(default=None, max_length=1000)


class NotificationSend(BaseModel):
    recipients: list[str] = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


@app.get("/phones")
def list_phones(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, phone_id, name, ntfy_username,
                   status, notes, created_at, updated_at
            FROM phones
            ORDER BY phone_id
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/phones", status_code=201)
def create_phone(
    data: PhoneCreate,
    _admin: bool = Depends(require_admin),
):
    phone_id = data.phone_id.strip()
    name = data.name.strip()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="Le nom du téléphone est obligatoire",
        )

    ntfy_username = (
        data.ntfy_username.strip()
        if data.ntfy_username and data.ntfy_username.strip()
        else None
    )
    notes = data.notes.strip() if data.notes and data.notes.strip() else None

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO phones (
                    phone_id, name, ntfy_username, status, notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (phone_id, name, ntfy_username, data.status, notes),
            )
            row = connection.execute(
                """
                SELECT id, phone_id, name, ntfy_username,
                       status, notes, created_at, updated_at
                FROM phones
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="Cet identifiant de téléphone existe déjà",
            )
        raise

    return dict(row)


@app.put("/phones/{phone_id}")
def update_phone(
    phone_id: str,
    data: PhoneUpdate,
    _admin: bool = Depends(require_admin),
):
    if not re.fullmatch(r"tel-[0-9]{3}", phone_id):
        raise HTTPException(
            status_code=400,
            detail="Identifiant de téléphone invalide",
        )

    name = data.name.strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail="Le nom du téléphone est obligatoire",
        )

    ntfy_username = (
        data.ntfy_username.strip()
        if data.ntfy_username and data.ntfy_username.strip()
        else None
    )
    notes = data.notes.strip() if data.notes and data.notes.strip() else None

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE phones
            SET name = ?,
                ntfy_username = ?,
                status = ?,
                notes = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE phone_id = ?
            """,
            (name, ntfy_username, data.status, notes, phone_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Téléphone introuvable",
            )

        row = connection.execute(
            """
            SELECT id, phone_id, name, ntfy_username,
                   status, notes, created_at, updated_at
            FROM phones
            WHERE phone_id = ?
            """,
            (phone_id,),
        ).fetchone()

    return dict(row)


@app.delete("/phones/{phone_id}")
def delete_phone(
    phone_id: str,
    _admin: bool = Depends(require_admin),
):
    if not re.fullmatch(r"tel-[0-9]{3}", phone_id):
        raise HTTPException(
            status_code=400,
            detail="Identifiant de téléphone invalide",
        )

    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM phones WHERE phone_id = ?",
            (phone_id,),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Téléphone introuvable",
            )

    return {"ok": True, "message": "Téléphone retiré de l’inventaire"}



@app.post("/notifications/send")
def send_notification(
    data: NotificationSend,
    _admin: bool = Depends(require_admin),
):
    recipients = [item.strip() for item in data.recipients]
    title = data.title.strip()
    body = data.body.strip()

    if not title or not body:
        raise HTTPException(status_code=422, detail="Titre et message obligatoires")
    if any(not re.fullmatch(r"tel-[0-9]{3}", item) for item in recipients):
        raise HTTPException(status_code=422, detail="Identifiant de téléphone invalide")
    if len(recipients) != len(set(recipients)):
        raise HTTPException(status_code=422, detail="Destinataire en double")

    placeholders = ",".join("?" for _ in recipients)
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT phone_id, status FROM phones WHERE phone_id IN ({placeholders})",
            recipients,
        ).fetchall()

    phones = {row["phone_id"]: row["status"] for row in rows}
    missing = sorted(set(recipients) - set(phones))
    inactive = sorted(item for item in recipients if phones.get(item) != "active")

    if missing:
        raise HTTPException(status_code=422, detail="Téléphone(s) introuvable(s)")
    if inactive:
        raise HTTPException(status_code=422, detail="Un ou plusieurs téléphones sont inactifs")

    username = os.getenv("NTFY_PUBLISHER_USERNAME")
    password = os.getenv("NTFY_PUBLISHER_PASSWORD")
    base_url = os.getenv(
        "NTFY_BASE_URL", "https://ntfy-pc-home.duckdns.org"
    ).rstrip("/")

    if not username or not password:
        raise HTTPException(status_code=503, detail="Compte d'envoi non configuré")

    credentials = base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")

    accepted = []
    failed = []

    for phone_id in recipients:
        request = URLRequest(
            f"{base_url}/{phone_id}",
            data=body.encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Title": title,
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                if 200 <= response.status < 300:
                    accepted.append(phone_id)
                else:
                    failed.append({"phone_id": phone_id, "status": response.status})
        except HTTPError as exc:
            failed.append({"phone_id": phone_id, "status": exc.code})
        except (URLError, TimeoutError, OSError, ValueError):
            failed.append({"phone_id": phone_id, "status": "network_error"})

    if accepted:
        with get_connection() as connection:
            for phone_id in accepted:
                connection.execute(
                    """
                    INSERT INTO audit_events
                        (actor_username, action, target_type, target_id, details_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "admin", "notification_sent", "phone", phone_id,
                        json.dumps(
                            {"title": title, "delivery": "accepted_by_ntfy"},
                            ensure_ascii=False,
                        ),
                    ),
                )

    if not accepted:
        raise HTTPException(
            status_code=502,
            detail={"message": "Aucun envoi accepté par ntfy", "failed": failed},
        )

    return {
        "ok": not failed,
        "accepted_count": len(accepted),
        "failed_count": len(failed),
        "accepted": accepted,
        "failed": failed,
        "message": "Accepté par ntfy" if not failed else "Envoi partiel : vérifiez les résultats",
    }


@app.get("/audit-events")
def list_audit_events(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, actor_username, action, target_type,
                   target_id, details_json, created_at
            FROM audit_events
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
    return [dict(row) for row in rows]


# --- Gestion des intérimaires : aucune désactivation ntfy automatique ---

from datetime import date


class InterimWorkerCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    ntfy_username: str = Field(
        min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    start_date: date
    end_date: date
    phone_ids: list[str] = Field(default_factory=list, max_length=50)


class InterimWorkerUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    start_date: date
    end_date: date
    phone_ids: list[str] = Field(default_factory=list, max_length=50)


class InterimWorkerDecision(BaseModel):
    decision: str = Field(
        pattern=r"^(pending|extended|access_reviewed|keep_access)$"
    )
    note: str | None = Field(default=None, max_length=1000)


class InterimWorkerClose(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class InterimWorkerProfileUpdate(BaseModel):
    sectors: list[str] = Field(default_factory=list, max_length=10)
    skills: list[str] = Field(default_factory=list, max_length=50)
    qualifications: list[str] = Field(default_factory=list, max_length=30)
    experience_text: str = Field(default="", max_length=3000)
    mobility_area: str = Field(default="", max_length=200)
    mobility_km: int | None = Field(default=None, ge=0, le=1000)


def _interim_real_ntfy_usernames() -> set[str]:
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/ntfy-admin-list-users"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        raise HTTPException(
            status_code=503,
            detail="Impossible de vérifier les comptes ntfy",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail="Impossible de vérifier les comptes ntfy",
        )

    return {
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := re.match(
            r"^user (.+) \(role: ([^,]+), tier: ([^)]+)\)$",
            line.strip(),
        ))
        and match.group(1) != "*"
    }


def _interim_validate_dates(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="La date de fin doit être égale ou postérieure à la date de début",
        )


def _interim_validate_phones(phone_ids: list[str], worker_id: int | None = None) -> list[str]:
    if len(phone_ids) != len(set(phone_ids)):
        raise HTTPException(
            status_code=422,
            detail="Un téléphone ne peut être associé qu'une seule fois",
        )

    if any(not re.fullmatch(r"tel-[0-9]{3}", item) for item in phone_ids):
        raise HTTPException(
            status_code=422,
            detail="Identifiant de téléphone invalide",
        )

    if phone_ids:
        placeholders = ",".join("?" for _ in phone_ids)
        with get_connection() as connection:
            rows = connection.execute(
                f"SELECT phone_id FROM phones WHERE phone_id IN ({placeholders})",
                phone_ids,
            ).fetchall()
        found = {row["phone_id"] for row in rows}
        missing = sorted(set(phone_ids) - found)
        if missing:
            raise HTTPException(
                status_code=422,
                detail="Téléphone(s) introuvable(s) : " + ", ".join(missing),
            )
        with get_connection() as connection:
            assigned = connection.execute(
                f"SELECT DISTINCT phone_id FROM interim_worker_phones "
                f"WHERE phone_id IN ({placeholders}) AND worker_id != ?",
                [*phone_ids, worker_id or 0],
            ).fetchall()
        if assigned:
            raise HTTPException(
                status_code=409,
                detail="Ce canal ntfy est déjà associé à un autre profil : "
                + ", ".join(row["phone_id"] for row in assigned),
            )

    return phone_ids


def _interim_audit(connection, action: str, worker_id: int, details: dict) -> None:
    connection.execute(
        """
        INSERT INTO audit_events
            (actor_username, action, target_type, target_id, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("admin", action, "interim_worker", str(worker_id),
         json.dumps(details, ensure_ascii=False)),
    )


def _interim_get_worker(connection, worker_id: int):
    row = connection.execute(
        """
        SELECT id, full_name, ntfy_username, start_date, end_date,
               status, decision, decision_note, created_at, updated_at
        FROM interim_workers WHERE id = ?
        """,
        (worker_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Fiche intérimaire introuvable")

    worker = dict(row)
    phone_rows = connection.execute(
        """
        SELECT p.phone_id, p.name, p.status
        FROM interim_worker_phones wp
        JOIN phones p ON p.phone_id = wp.phone_id
        WHERE wp.worker_id = ?
        ORDER BY p.phone_id
        """,
        (worker_id,),
    ).fetchall()
    worker["phones"] = [dict(phone) for phone in phone_rows]

    today = date.today().isoformat()
    worker["alert"] = (
        "overdue" if worker["status"] == "active" and worker["end_date"] < today
        else "due_today" if worker["status"] == "active" and worker["end_date"] == today
        else "upcoming" if worker["status"] == "active" and worker["end_date"] > today
        else "closed"
    )
    return worker


@app.get("/interim-workers/{worker_id}/profile")
def get_interim_worker_profile(
    worker_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        worker = connection.execute(
            "SELECT id FROM interim_workers WHERE id = ?", (worker_id,)
        ).fetchone()
        if worker is None:
            raise HTTPException(status_code=404, detail="Fiche intérimaire introuvable")

        connection.execute(
            "INSERT OR IGNORE INTO interim_worker_profiles (worker_id) VALUES (?)",
            (worker_id,),
        )
        row = connection.execute(
            "SELECT * FROM interim_worker_profiles WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()

    profile = dict(row)
    profile["sectors"] = json.loads(profile.pop("sectors_json"))
    profile["skills"] = json.loads(profile.pop("skills_json"))
    profile["qualifications"] = json.loads(profile.pop("qualifications_json"))
    return profile


@app.put("/interim-workers/{worker_id}/profile")
def update_interim_worker_profile(
    worker_id: int,
    data: InterimWorkerProfileUpdate,
    _admin: bool = Depends(require_admin),
):
    def clean_items(items: list[str], field_name: str) -> list[str]:
        cleaned = []
        for item in items:
            value = item.strip()
            if len(value) > 100:
                raise HTTPException(
                    status_code=422,
                    detail=f"Chaque élément de {field_name} doit faire 100 caractères maximum",
                )
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    sectors = clean_items(data.sectors, "secteurs")
    skills = clean_items(data.skills, "compétences")
    qualifications = clean_items(data.qualifications, "qualifications")
    experience_text = data.experience_text.strip()
    mobility_area = data.mobility_area.strip()

    with get_connection() as connection:
        worker = connection.execute(
            "SELECT id FROM interim_workers WHERE id = ?", (worker_id,)
        ).fetchone()
        if worker is None:
            raise HTTPException(status_code=404, detail="Fiche intérimaire introuvable")

        connection.execute(
            "INSERT OR IGNORE INTO interim_worker_profiles (worker_id) VALUES (?)",
            (worker_id,),
        )
        connection.execute(
            """
            UPDATE interim_worker_profiles
            SET sectors_json = ?,
                skills_json = ?,
                qualifications_json = ?,
                experience_text = ?,
                mobility_area = ?,
                mobility_km = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE worker_id = ?
            """,
            (
                json.dumps(sectors, ensure_ascii=False),
                json.dumps(skills, ensure_ascii=False),
                json.dumps(qualifications, ensure_ascii=False),
                experience_text,
                mobility_area,
                data.mobility_km,
                worker_id,
            ),
        )
        _interim_audit(connection, "interim_worker_profile_updated", worker_id, {
            "sector_count": len(sectors),
            "skill_count": len(skills),
            "qualification_count": len(qualifications),
        })
        row = connection.execute(
            "SELECT * FROM interim_worker_profiles WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()

    profile = dict(row)
    profile["sectors"] = json.loads(profile.pop("sectors_json"))
    profile["skills"] = json.loads(profile.pop("skills_json"))
    profile["qualifications"] = json.loads(profile.pop("qualifications_json"))
    return profile


@app.get("/interim-workers")
def list_interim_workers(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        ids = connection.execute(
            "SELECT id FROM interim_workers ORDER BY end_date, full_name"
        ).fetchall()
        workers = [_interim_get_worker(connection, row["id"]) for row in ids]
        profiles = connection.execute(
            "SELECT worker_id, sectors_json, skills_json, qualifications_json, "
            "experience_text, mobility_area, mobility_km "
            "FROM interim_worker_profiles"
        ).fetchall()
        profiles_by_worker = {row["worker_id"]: row for row in profiles}
        availability_counts = {
            row["worker_id"]: row["period_count"]
            for row in connection.execute(
                "SELECT worker_id, COUNT(*) AS period_count "
                "FROM worker_availabilities GROUP BY worker_id"
            ).fetchall()
        }
        for worker in workers:
            worker["availability_count"] = availability_counts.get(worker["id"], 0)
            row = profiles_by_worker.get(worker["id"])
            worker["profile"] = {
                "sectors": json.loads(row["sectors_json"]) if row else [],
                "skills": json.loads(row["skills_json"]) if row else [],
                "qualifications": json.loads(row["qualifications_json"]) if row else [],
                "experience_text": row["experience_text"] if row else "",
                "mobility_area": row["mobility_area"] if row else "",
                "mobility_km": row["mobility_km"] if row else None,
            }
        return workers


@app.post("/interim-workers", status_code=201)
def create_interim_worker(
    data: InterimWorkerCreate,
    _admin: bool = Depends(require_admin),
):
    full_name = data.full_name.strip()
    username = data.ntfy_username.strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="Le nom est obligatoire")

    _interim_validate_dates(data.start_date, data.end_date)
    phone_ids = _interim_validate_phones(data.phone_ids)

    if username not in _interim_real_ntfy_usernames():
        raise HTTPException(
            status_code=422,
            detail="Ce nom d'utilisateur n'existe pas dans les comptes ntfy réels",
        )

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO interim_workers
                (full_name, ntfy_username, start_date, end_date)
            VALUES (?, ?, ?, ?)
            """,
            (full_name, username, data.start_date.isoformat(), data.end_date.isoformat()),
        )
        worker_id = cursor.lastrowid

        for phone_id in phone_ids:
            connection.execute(
                "INSERT INTO interim_worker_phones (worker_id, phone_id) VALUES (?, ?)",
                (worker_id, phone_id),
            )

        _interim_audit(connection, "interim_worker_created", worker_id, {
            "ntfy_username": username,
            "start_date": data.start_date.isoformat(),
            "end_date": data.end_date.isoformat(),
            "phone_ids": phone_ids,
        })
        return _interim_get_worker(connection, worker_id)


@app.put("/interim-workers/{worker_id}")
def update_interim_worker(
    worker_id: int,
    data: InterimWorkerUpdate,
    _admin: bool = Depends(require_admin),
):
    full_name = data.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="Le nom est obligatoire")

    _interim_validate_dates(data.start_date, data.end_date)
    phone_ids = _interim_validate_phones(data.phone_ids, worker_id=worker_id)

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM interim_workers WHERE id = ?", (worker_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Fiche intérimaire introuvable")

        connection.execute(
            """
            UPDATE interim_workers
            SET full_name = ?, start_date = ?, end_date = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (full_name, data.start_date.isoformat(), data.end_date.isoformat(), worker_id),
        )
        connection.execute(
            "DELETE FROM interim_worker_phones WHERE worker_id = ?", (worker_id,)
        )
        for phone_id in phone_ids:
            connection.execute(
                "INSERT INTO interim_worker_phones (worker_id, phone_id) VALUES (?, ?)",
                (worker_id, phone_id),
            )

        _interim_audit(connection, "interim_worker_updated", worker_id, {
            "start_date": data.start_date.isoformat(),
            "end_date": data.end_date.isoformat(),
            "phone_ids": phone_ids,
        })
        return _interim_get_worker(connection, worker_id)


@app.post("/interim-workers/{worker_id}/close")
def close_interim_worker(
    worker_id: int,
    data: InterimWorkerClose,
    _admin: bool = Depends(require_admin),
):
    note = data.note.strip() if data.note and data.note.strip() else None

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id, status FROM interim_workers WHERE id = ?",
            (worker_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Fiche intérimaire introuvable")
        if existing["status"] == "closed":
            raise HTTPException(status_code=409, detail="Cette fiche est déjà clôturée")

        connection.execute(
            """
            UPDATE interim_workers
            SET status = 'closed',
                decision_note = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (note, worker_id),
        )
        _interim_audit(connection, "interim_worker_closed", worker_id, {
            "note": note,
        })
        return _interim_get_worker(connection, worker_id)




# --- Missions professionnelles ---

@app.get("/contract-signatures")
def list_contract_signature_drafts(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT d.id, d.mission_id, m.title AS mission_title,
                   m.client_name, m.location, m.starts_at, m.ends_at,
                   d.worker_id, w.full_name AS worker_name,
                   d.worker_email, d.agency_signer_name, d.agency_signer_email,
                   d.original_filename, d.sha256, d.status, d.created_at,
                   worker_signer.status AS worker_signature_status,
                   worker_signer.signed_at AS worker_signed_at,
                   agency_signer.status AS agency_signature_status,
                   agency_signer.signed_at AS agency_signed_at
            FROM contract_signature_drafts d
            JOIN work_missions m ON m.id = d.mission_id
            JOIN interim_workers w ON w.id = d.worker_id
            LEFT JOIN contract_signature_participants worker_signer
              ON worker_signer.draft_id = d.id AND worker_signer.signer_role = 'worker'
            LEFT JOIN contract_signature_participants agency_signer
              ON agency_signer.draft_id = d.id AND agency_signer.signer_role = 'agency'
            ORDER BY d.created_at DESC, d.id DESC
            """
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        signer_statuses = (item["worker_signature_status"], item["agency_signature_status"])
        signed_count = sum(status == "signed" for status in signer_statuses)
        if item["status"] == "declined" or "declined" in signer_statuses:
            item["history_status"] = "declined"
        elif signed_count == 2:
            item["history_status"] = "completed"
        elif item["status"] == "failed":
            item["history_status"] = "failed"
        elif item["status"] == "draft":
            item["history_status"] = "draft"
        elif item["status"] in ("sent", "partially_signed"):
            item["history_status"] = "in_progress"
        else:
            item["history_status"] = item["status"]
        item["signature_progress"] = f"{signed_count}/2"
        results.append(item)
    return results


@app.get("/contract-signatures/configuration")
def contract_signature_configuration(_admin: bool = Depends(require_admin)):
    smtp_ready = all(os.getenv(name, "").strip() for name in (
        "RMS_SMTP_HOST", "RMS_SMTP_USER", "RMS_SMTP_PASSWORD", "RMS_SMTP_FROM"
    ))
    public_url = os.getenv("RMS_PUBLIC_URL", "").strip()
    secure_url = public_url.startswith("https://") or public_url.startswith("http://localhost")
    return {"smtp_ready": smtp_ready, "public_url_ready": secure_url}


def _signature_participant_for_token(connection, token: str):
    if not token or len(token) > 200:
        raise HTTPException(status_code=404, detail="Lien de signature invalide")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = connection.execute(
        """
        SELECT p.*, d.original_filename, d.storage_filename, d.sha256,
               d.status AS draft_status, m.title AS mission_title
        FROM contract_signature_participants p
        JOIN contract_signature_drafts d ON d.id = p.draft_id
        JOIN work_missions m ON m.id = d.mission_id
        WHERE p.token_hash = ?
        """,
        (token_hash,),
    ).fetchone()
    if row is None or row["status"] not in ("sent", "signed"):
        raise HTTPException(status_code=404, detail="Lien de signature invalide ou déjà clôturé")
    try:
        expiry = datetime.fromisoformat(row["token_expires_at"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=410, detail="Lien de signature expiré")
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Lien de signature expiré")
    return row


def _send_contract_for_signature(draft_id: int):
    smtp_host = os.getenv("RMS_SMTP_HOST", "").strip()
    smtp_user = os.getenv("RMS_SMTP_USER", "").strip()
    smtp_password = os.getenv("RMS_SMTP_PASSWORD", "")
    sender = os.getenv("RMS_SMTP_FROM", "").strip()
    public_url = os.getenv("RMS_PUBLIC_URL", "").strip().rstrip("/")
    smtp_port = int(os.getenv("RMS_SMTP_PORT", "587"))
    if not all((smtp_host, smtp_user, smtp_password, sender, public_url)):
        raise HTTPException(
            status_code=503,
            detail="Envoi indisponible : configurez RMS_SMTP_HOST, RMS_SMTP_USER, RMS_SMTP_PASSWORD, RMS_SMTP_FROM et RMS_PUBLIC_URL dans le .env.",
        )
    if not public_url.startswith("https://") and not public_url.startswith("http://localhost"):
        raise HTTPException(status_code=503, detail="RMS_PUBLIC_URL doit utiliser HTTPS pour les liens signataires")

    with get_connection() as connection:
        draft = connection.execute(
            "SELECT id, status, original_filename FROM contract_signature_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise HTTPException(status_code=404, detail="Brouillon de contrat introuvable")
        if draft["status"] not in ("draft", "failed"):
            raise HTTPException(status_code=409, detail="Ce contrat a déjà été envoyé")
        participants = connection.execute(
            "SELECT * FROM contract_signature_participants WHERE draft_id = ? ORDER BY signer_role",
            (draft_id,),
        ).fetchall()
        if len(participants) != 2:
            raise HTTPException(status_code=409, detail="Les deux signataires doivent être renseignés")

        expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        outgoing = []
        for participant in participants:
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            connection.execute(
                """UPDATE contract_signature_participants
                   SET token_hash = ?, token_expires_at = ?, status = 'pending',
                       signed_at = NULL, signed_name = NULL, signed_user_agent = NULL
                   WHERE id = ?""",
                (token_hash, expiry, participant["id"]),
            )
            link = f"{public_url}/signature.html?token={token}"
            message = EmailMessage()
            message["Subject"] = "RMS · Document à consulter et signer"
            message["From"] = sender
            message["To"] = participant["signer_email"]
            message.set_content(
                f"Bonjour {participant['signer_name']},\n\n"
                f"Le contrat « {draft['original_filename']} » concernant la mission vous attend.\n"
                f"Consultez le PDF et suivez le parcours RMS ici : {link}\n\n"
                "Ce lien individuel expire dans 7 jours. Si vous ne vous attendiez pas à ce message, contactez l’agence.\n"
            )
            outgoing.append((message, participant["signer_role"]))

        connection.commit()

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as client:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
            client.login(smtp_user, smtp_password)
            for message, _role in outgoing:
                client.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        with get_connection() as connection:
            connection.execute(
                "UPDATE contract_signature_drafts SET status = 'failed' WHERE id = ?",
                (draft_id,),
            )
            connection.execute(
                """UPDATE contract_signature_participants
                   SET token_hash = NULL, token_expires_at = NULL, status = 'pending'
                   WHERE draft_id = ?""",
                (draft_id,),
            )
        raise HTTPException(status_code=502, detail=f"Échec de l’envoi SMTP : {error.__class__.__name__}")

    with get_connection() as connection:
        connection.execute(
            "UPDATE contract_signature_participants SET status = 'sent' WHERE draft_id = ?",
            (draft_id,),
        )
        connection.execute(
            "UPDATE contract_signature_drafts SET status = 'sent' WHERE id = ?",
            (draft_id,),
        )
    return {"id": draft_id, "status": "sent", "expires_at": expiry}


@app.post("/contract-signatures/{draft_id}/send")
def send_contract_for_signature(
    draft_id: int,
    _admin: bool = Depends(require_admin),
):
    raise HTTPException(
        status_code=409,
        detail="L’envoi d’un contrat se valide depuis la rubrique ‘Contrats à valider’ de la page d’accueil.",
    )


@app.get("/contract-signatures/pending-approvals")
def list_contract_pending_approvals(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
        """SELECT i.id AS invitation_id, i.responded_at, d.id AS draft_id,
                      d.status AS draft_status, d.original_filename, d.sha256,
                      m.id AS mission_id, m.title AS mission_title, m.client_name,
                      m.location, m.starts_at, m.ends_at,
                      w.id AS worker_id, w.full_name AS worker_name,
                      p.signer_email AS worker_email,
                      agency.signer_name AS agency_signer_name,
                      agency.signer_email AS agency_signer_email
               FROM mission_invitations i
               LEFT JOIN contract_signature_drafts d ON d.id = COALESCE(
                   i.contract_draft_id,
                   (SELECT d2.id FROM contract_signature_drafts d2
                    WHERE d2.mission_id = i.mission_id AND d2.worker_id = i.worker_id
                    ORDER BY d2.created_at DESC, d2.id DESC LIMIT 1)
               )
               JOIN work_missions m ON m.id = i.mission_id
               JOIN interim_workers w ON w.id = i.worker_id
               LEFT JOIN contract_signature_participants p
                 ON p.draft_id = d.id AND p.signer_role = 'worker'
               LEFT JOIN contract_signature_participants agency
                 ON agency.draft_id = d.id AND agency.signer_role = 'agency'
               WHERE i.status = 'accepted' AND (d.id IS NULL OR d.status IN ('draft', 'failed'))
               ORDER BY i.responded_at DESC, i.id DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/contract-signatures/{draft_id}/approve-and-send")
def approve_and_send_contract(
    draft_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        invitation = connection.execute(
            """SELECT i.id, i.mission_id, i.worker_id
               FROM mission_invitations i
               JOIN contract_signature_drafts d
                 ON (d.id = i.contract_draft_id OR
                     (i.contract_draft_id IS NULL AND d.mission_id = i.mission_id AND d.worker_id = i.worker_id))
               WHERE d.id = ? AND i.status = 'accepted'
               ORDER BY i.responded_at DESC, i.id DESC LIMIT 1""",
            (draft_id,),
        ).fetchone()
        if invitation is None:
            raise HTTPException(status_code=409, detail="Aucune acceptation associée à ce contrat. Il ne peut pas être envoyé.")
        connection.execute(
            "UPDATE mission_invitations SET contract_draft_id = ? WHERE id = ? AND contract_draft_id IS NULL",
            (draft_id, invitation["id"]),
        )
    result = _send_contract_for_signature(draft_id)
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO audit_events
               (actor_username, action, target_type, target_id, details_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "admin", "contract_approved_and_sent", "contract_signature_draft",
                str(draft_id),
                json.dumps({"invitation_id": invitation["id"], "mission_id": invitation["mission_id"], "worker_id": invitation["worker_id"]}),
            ),
        )
    return result


def _request_signature_token(request: Request) -> str:
    return request.headers.get("X-RMS-Signature-Token", "")


@app.get("/contract-signatures/signing-request")
def get_signing_request(request: Request):
    with get_connection() as connection:
        row = _signature_participant_for_token(connection, _request_signature_token(request))
    return {
        "signer_name": row["signer_name"],
        "signer_role": row["signer_role"],
        "mission_title": row["mission_title"],
        "filename": row["original_filename"],
        "sha256": row["sha256"],
        "status": row["status"],
    }


@app.get("/contract-signatures/signing-document")
def get_signing_document(request: Request):
    with get_connection() as connection:
        row = _signature_participant_for_token(connection, _request_signature_token(request))
    file_path = Path(__file__).resolve().parents[1] / "data" / "contracts" / row["storage_filename"]
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Le document privé est introuvable")
    return FileResponse(file_path, media_type="application/pdf", filename=row["original_filename"])


class ContractSignatureRecord(BaseModel):
    signed_name: str = Field(min_length=2, max_length=150)
    consent: bool


@app.post("/contract-signatures/signing-response")
def record_contract_signature(data: ContractSignatureRecord, request: Request):
    if not data.consent:
        raise HTTPException(status_code=422, detail="Le consentement doit être confirmé")
    with get_connection() as connection:
        row = _signature_participant_for_token(connection, _request_signature_token(request))
        if row["status"] == "signed":
            raise HTTPException(status_code=409, detail="Votre réponse est déjà enregistrée")
        if data.signed_name.strip().casefold() != row["signer_name"].strip().casefold():
            raise HTTPException(status_code=422, detail="Saisissez votre nom complet tel qu’indiqué dans l’invitation")
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """UPDATE contract_signature_participants
               SET status = 'signed', signed_at = ?, signed_name = ?, signed_user_agent = ?
               WHERE id = ? AND status = 'sent'""",
            (now, data.signed_name.strip(), request.headers.get("user-agent", "")[:500], row["id"]),
        )
        remaining = connection.execute(
            "SELECT COUNT(*) FROM contract_signature_participants WHERE draft_id = ? AND status != 'signed'",
            (row["draft_id"],),
        ).fetchone()[0]
        new_status = "partially_signed" if remaining else "signed"
        connection.execute(
            "UPDATE contract_signature_drafts SET status = ? WHERE id = ?",
            (new_status, row["draft_id"]),
        )
    return {"status": new_status, "recorded_at": now}


@app.post("/contract-signatures", status_code=201)
def create_contract_signature_draft(
    data: ContractSignatureDraftCreate,
    _admin: bool = Depends(require_admin),
):
    try:
        pdf_bytes = base64.b64decode(data.pdf_base64, validate=True)
    except (ValueError, base64.binascii.Error):
        raise HTTPException(status_code=422, detail="Le fichier PDF est invalide")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Le document doit être un PDF valide")
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Le PDF ne doit pas dépasser 10 Mo")

    original_name = Path(data.original_filename).name
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Le document doit porter l’extension .pdf")

    with get_connection() as connection:
        mission = connection.execute(
            "SELECT id FROM work_missions WHERE id = ?", (data.mission_id,)
        ).fetchone()
        worker = connection.execute(
            "SELECT id, full_name FROM interim_workers WHERE id = ? AND status = 'active'",
            (data.worker_id,),
        ).fetchone()
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        if worker is None:
            raise HTTPException(status_code=404, detail="Intérimaire actif introuvable")
        if data.accepted_invitation_id is not None:
            invitation = connection.execute(
                """SELECT id FROM mission_invitations
                   WHERE id = ? AND mission_id = ? AND worker_id = ?
                     AND status = 'accepted' AND contract_draft_id IS NULL""",
                (data.accepted_invitation_id, data.mission_id, data.worker_id),
            ).fetchone()
            if invitation is None:
                raise HTTPException(
                    status_code=409,
                    detail="Cette acceptation n’est plus disponible ou ne correspond pas à la personne et à la mission sélectionnées.",
                )

        storage_name = f"{secrets.token_hex(24)}.pdf"
        contract_dir = Path(__file__).resolve().parents[1] / "data" / "contracts"
        contract_dir.mkdir(parents=True, exist_ok=True)
        file_path = contract_dir / storage_name
        try:
            file_path.write_bytes(pdf_bytes)
            file_path.chmod(0o600)
            cursor = connection.execute(
                """
                INSERT INTO contract_signature_drafts
                    (mission_id, worker_id, worker_email, agency_signer_name,
                     agency_signer_email, original_filename, storage_filename, sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.mission_id,
                    data.worker_id,
                    data.worker_email.strip().lower(),
                    data.agency_signer_name.strip(),
                    data.agency_signer_email.strip().lower(),
                    original_name,
                    storage_name,
                    hashlib.sha256(pdf_bytes).hexdigest(),
                ),
            )
            draft_id = cursor.lastrowid
            connection.executemany(
                """
                INSERT INTO contract_signature_participants
                    (draft_id, signer_role, signer_name, signer_email)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (draft_id, "worker", worker["full_name"], data.worker_email.strip().lower()),
                    (draft_id, "agency", data.agency_signer_name.strip(), data.agency_signer_email.strip().lower()),
                ],
            )
            if data.accepted_invitation_id is not None:
                linked = connection.execute(
                    """UPDATE mission_invitations SET contract_draft_id = ?
                       WHERE id = ? AND status = 'accepted' AND contract_draft_id IS NULL""",
                    (draft_id, data.accepted_invitation_id),
                )
                if linked.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Cette acceptation a déjà été associée à un contrat.")
            row = connection.execute(
                "SELECT * FROM contract_signature_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            return {"id": draft_id, "status": row["status"], "sha256": row["sha256"]}
        except Exception:
            file_path.unlink(missing_ok=True)
            raise


@app.get("/contract-signatures/{draft_id}/document")
def download_contract_signature_draft(
    draft_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT original_filename, storage_filename FROM contract_signature_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Brouillon de contrat introuvable")
    file_path = Path(__file__).resolve().parents[1] / "data" / "contracts" / row["storage_filename"]
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Le document privé est introuvable")
    return FileResponse(file_path, media_type="application/pdf", filename=row["original_filename"])


class WorkMissionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    client_name: str = Field(default="", max_length=150)
    sector: str = Field(min_length=1, max_length=100)
    location: str = Field(default="", max_length=200)
    starts_at: datetime
    ends_at: datetime
    required_workers: int = Field(default=1, ge=1, le=500)
    required_qualifications: list[str] = Field(default_factory=list, max_length=30)
    status: str = Field(default="draft", pattern=r"^(draft|open)$")
    notes: str = Field(default="", max_length=3000)


def _work_mission_dict(row):
    mission = dict(row)
    mission["required_qualifications"] = json.loads(
        mission.pop("required_qualifications_json")
    )
    return mission


@app.get("/work-missions")
def list_work_missions(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM work_missions
            ORDER BY starts_at, id
            """
        ).fetchall()
    return [_work_mission_dict(row) for row in rows]


@app.post("/work-missions", status_code=201)
def create_work_mission(
    data: WorkMissionCreate,
    _admin: bool = Depends(require_admin),
):
    title = data.title.strip()
    client_name = data.client_name.strip()
    sector = data.sector.strip()
    location = data.location.strip()
    notes = data.notes.strip()

    if not title or not sector:
        raise HTTPException(
            status_code=422,
            detail="Le titre et le secteur sont obligatoires",
        )

    if data.ends_at <= data.starts_at:
        raise HTTPException(
            status_code=422,
            detail="La fin de mission doit être postérieure au début",
        )

    if (data.starts_at.tzinfo is None) != (data.ends_at.tzinfo is None):
        raise HTTPException(
            status_code=422,
            detail="Les deux horaires doivent utiliser le même format de fuseau horaire",
        )

    qualifications = []
    for item in data.required_qualifications:
        value = item.strip()
        if len(value) > 100:
            raise HTTPException(
                status_code=422,
                detail="Chaque qualification doit faire 100 caractères maximum",
            )
        if value and value not in qualifications:
            qualifications.append(value)

    starts_at = data.starts_at.isoformat()
    ends_at = data.ends_at.isoformat()

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO work_missions (
                title, client_name, sector, location, starts_at, ends_at,
                required_workers, required_qualifications_json,
                status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                client_name,
                sector,
                location,
                starts_at,
                ends_at,
                data.required_workers,
                json.dumps(qualifications, ensure_ascii=False),
                data.status,
                notes,
            ),
        )
        mission_id = cursor.lastrowid

        connection.execute(
            """
            INSERT INTO audit_events
                (actor_username, action, target_type, target_id, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "admin",
                "work_mission_created",
                "work_mission",
                str(mission_id),
                json.dumps(
                    {
                        "title": title,
                        "client_name": client_name,
                        "sector": sector,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "status": data.status,
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        row = connection.execute(
            "SELECT * FROM work_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()

    return _work_mission_dict(row)




# --- Disponibilites des interimaires ---

class WorkerAvailabilityCreate(BaseModel):
    period_type: str = Field(pattern=r"^(available|unavailable)$")
    starts_at: datetime
    ends_at: datetime
    note: str = Field(default="", max_length=1000)


@app.get("/interim-workers/{worker_id}/availabilities")
def list_worker_availabilities(
    worker_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        worker = connection.execute(
            "SELECT id FROM interim_workers WHERE id = ?",
            (worker_id,),
        ).fetchone()

        if worker is None:
            raise HTTPException(
                status_code=404,
                detail="Fiche interimaires introuvable",
            )

        rows = connection.execute(
            """
            SELECT id, worker_id, period_type, starts_at, ends_at,
                   note, created_at
            FROM worker_availabilities
            WHERE worker_id = ?
            ORDER BY starts_at, id
            """,
            (worker_id,),
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/interim-workers/{worker_id}/availabilities", status_code=201)
def create_worker_availability(
    worker_id: int,
    data: WorkerAvailabilityCreate,
    _admin: bool = Depends(require_admin),
):
    if data.ends_at <= data.starts_at:
        raise HTTPException(
            status_code=422,
            detail="La fin doit etre posterieure au debut",
        )

    if (data.starts_at.tzinfo is None) != (data.ends_at.tzinfo is None):
        raise HTTPException(
            status_code=422,
            detail="Les deux horaires doivent utiliser le meme format de fuseau horaire",
        )

    starts_at = data.starts_at.isoformat()
    ends_at = data.ends_at.isoformat()
    note = data.note.strip()

    with get_connection() as connection:
        worker = connection.execute(
            "SELECT id FROM interim_workers WHERE id = ?",
            (worker_id,),
        ).fetchone()

        if worker is None:
            raise HTTPException(
                status_code=404,
                detail="Fiche interimaires introuvable",
            )

        cursor = connection.execute(
            """
            INSERT INTO worker_availabilities
                (worker_id, period_type, starts_at, ends_at, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (worker_id, data.period_type, starts_at, ends_at, note),
        )
        availability_id = cursor.lastrowid

        _interim_audit(
            connection,
            "interim_availability_created",
            worker_id,
            {
                "availability_id": availability_id,
                "period_type": data.period_type,
                "starts_at": starts_at,
                "ends_at": ends_at,
            },
        )

        row = connection.execute(
            """
            SELECT id, worker_id, period_type, starts_at, ends_at,
                   note, created_at
            FROM worker_availabilities
            WHERE id = ?
            """,
            (availability_id,),
        ).fetchone()

    return dict(row)




# --- Affectations aux missions ---

class WorkAssignmentCreate(BaseModel):
    worker_id: int = Field(gt=0)
    notes: str = Field(default="", max_length=1000)


def _work_datetime(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    return parsed


def _mission_normalize(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _work_mission_matches(connection, mission):
    mission_start = _work_datetime(mission["starts_at"])
    mission_end = _work_datetime(mission["ends_at"])
    required_qualifications = {
        _mission_normalize(item)
        for item in json.loads(mission["required_qualifications_json"] or "[]")
    }
    sector = _mission_normalize(mission["sector"])
    query_words = set(re.findall(
        r"[a-z0-9]{3,}",
        _mission_normalize(" ".join((mission["title"], mission["notes"], mission["sector"]))),
    ))
    rows = connection.execute(
        """
        SELECT w.id, w.full_name, w.status, p.sectors_json, p.skills_json,
               p.qualifications_json, p.experience_text, p.mobility_area,
               (SELECT COUNT(*) FROM interim_worker_phones wp
                JOIN phones ph ON ph.phone_id = wp.phone_id
                WHERE wp.worker_id = w.id AND ph.status = 'active') AS phone_count
        FROM interim_workers w
        LEFT JOIN interim_worker_profiles p ON p.worker_id = w.id
        WHERE w.status = 'active'
        ORDER BY w.full_name COLLATE NOCASE
        """
    ).fetchall()
    matches = []
    for row in rows:
        if row["sectors_json"] is None:
            continue
        sectors = json.loads(row["sectors_json"] or "[]")
        skills = json.loads(row["skills_json"] or "[]")
        qualifications = json.loads(row["qualifications_json"] or "[]")
        if sector not in {_mission_normalize(item) for item in sectors}:
            continue
        normalized_qualifications = {_mission_normalize(item) for item in qualifications}
        if not required_qualifications.issubset(normalized_qualifications):
            continue

        periods = connection.execute(
            "SELECT period_type, starts_at, ends_at FROM worker_availabilities WHERE worker_id = ?",
            (row["id"],),
        ).fetchall()
        try:
            available = any(
                period["period_type"] == "available"
                and _work_datetime(period["starts_at"]) <= mission_start
                and _work_datetime(period["ends_at"]) >= mission_end
                for period in periods
            )
            unavailable = any(
                period["period_type"] == "unavailable"
                and _work_datetime(period["starts_at"]) < mission_end
                and _work_datetime(period["ends_at"]) > mission_start
                for period in periods
            )
            other_assignments = connection.execute(
                """
                SELECT m.starts_at, m.ends_at FROM work_assignments a
                JOIN work_missions m ON m.id = a.mission_id
                WHERE a.worker_id = ? AND a.status = 'assigned' AND a.mission_id != ?
                """,
                (row["id"], mission["id"]),
            ).fetchall()
            assignment_conflict = any(
                _work_datetime(item["starts_at"]) < mission_end
                and _work_datetime(item["ends_at"]) > mission_start
                for item in other_assignments
            )
        except (TypeError, ValueError):
            continue
        if not available or unavailable or assignment_conflict:
            continue

        normalized_skills = {_mission_normalize(item) for item in skills}
        skill_words = set(re.findall(r"[a-z0-9]{3,}", " ".join(normalized_skills)))
        matched_skills = [item for item in skills if _mission_normalize(item) in query_words]
        overlap = len(query_words & skill_words)
        score = min(99, 78 + (12 if required_qualifications else 0) + min(9, overlap * 3))
        matches.append({
            "id": row["id"],
            "full_name": row["full_name"],
            "skills": skills,
            "qualifications": qualifications,
            "experience_text": row["experience_text"] or "",
            "mobility_area": row["mobility_area"] or "",
            "matched_skills": matched_skills,
            "phone_count": row["phone_count"],
            "score": score,
        })
    matches.sort(key=lambda item: (-item["score"], item["full_name"].casefold()))
    return matches


@app.get("/work-missions/{mission_id}/matches")
def list_work_mission_matches(
    mission_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        mission = connection.execute(
            "SELECT * FROM work_missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        return _work_mission_matches(connection, mission)


class WorkMissionNotify(BaseModel):
    worker_ids: list[int] = Field(min_length=1, max_length=50)


@app.post("/work-missions/{mission_id}/notify")
def notify_work_mission_matches(
    mission_id: int,
    data: WorkMissionNotify,
    _admin: bool = Depends(require_admin),
):
    if len(data.worker_ids) != len(set(data.worker_ids)):
        raise HTTPException(status_code=422, detail="Profil sélectionné plusieurs fois")
    username = os.getenv("NTFY_PUBLISHER_USERNAME")
    password = os.getenv("NTFY_PUBLISHER_PASSWORD")
    base_url = os.getenv("NTFY_BASE_URL", "https://ntfy-pc-home.duckdns.org").rstrip("/")
    public_url = os.getenv("RMS_PUBLIC_URL", "").strip().rstrip("/")
    if not username or not password:
        raise HTTPException(status_code=503, detail="Compte d'envoi non configuré")
    if not public_url.startswith("https://"):
        raise HTTPException(status_code=503, detail="RMS_PUBLIC_URL doit être configurée en HTTPS pour permettre les réponses sécurisées")

    with get_connection() as connection:
        mission = connection.execute(
            "SELECT * FROM work_missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        matched = {item["id"]: item for item in _work_mission_matches(connection, mission)}
        missing_matches = [worker_id for worker_id in data.worker_ids if worker_id not in matched]
        if missing_matches:
            raise HTTPException(
                status_code=409,
                detail="Un profil sélectionné ne correspond plus à la mission ou à ses disponibilités.",
            )
        placeholders = ",".join("?" for _ in data.worker_ids)
        destinations = connection.execute(
            f"""
            SELECT w.id AS worker_id, w.full_name, p.phone_id
            FROM interim_workers w
            JOIN interim_worker_phones wp ON wp.worker_id = w.id
            JOIN phones p ON p.phone_id = wp.phone_id AND p.status = 'active'
            WHERE w.id IN ({placeholders})
            ORDER BY w.id, p.phone_id
            """,
            data.worker_ids,
        ).fetchall()
        workers_without_phone = [
            matched[worker_id]["full_name"] for worker_id in data.worker_ids
            if not any(item["worker_id"] == worker_id for item in destinations)
        ]
        if workers_without_phone:
            raise HTTPException(
                status_code=409,
                detail="Aucun téléphone ntfy actif n'est lié à : " + ", ".join(workers_without_phone),
            )

        message_parts = [
            f"Mission : {mission['title']}",
            f"Client : {mission['client_name'] or 'À préciser'}",
            f"Secteur : {mission['sector']}",
            f"Lieu : {mission['location'] or 'À préciser'}",
            f"Début : {mission['starts_at']}",
            f"Fin : {mission['ends_at']}",
        ]
        qualifications = json.loads(mission["required_qualifications_json"] or "[]")
        if qualifications:
            message_parts.append("Qualifications : " + ", ".join(qualifications))
        if mission["notes"]:
            message_parts.append("Détails : " + mission["notes"])
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        response_tokens = {}
        for worker_id in data.worker_ids:
            connection.execute(
                "UPDATE mission_invitations SET status = 'revoked' WHERE mission_id = ? AND worker_id = ? AND status = 'pending'",
                (mission_id, worker_id),
            )
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            connection.execute(
                """INSERT INTO mission_invitations
                   (mission_id, worker_id, token_hash, expires_at)
                   VALUES (?, ?, ?, ?)""",
                (mission_id, worker_id, token_hash, expires_at),
            )
            response_tokens[worker_id] = token

        # Les jetons doivent être lisibles dès que la notification ntfy arrive.
        connection.commit()
        credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        accepted_workers = set()
        failed_workers = set()
        accepted_count = 0
        for destination in destinations:
            response_link = f"{public_url}/mission-response.html?token={quote(response_tokens[destination['worker_id']], safe='')}"
            body = "\n".join(message_parts + [
                "\nRépondez à cette proposition :",
                response_link,
                "Ce lien personnel expire dans 48 heures.",
            ])
            request = URLRequest(
                f"{base_url}/{quote(destination['phone_id'], safe='')}",
                data=body.encode("utf-8"),
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Title": f"Mission RMS · {mission['title']}",
                    "Content-Type": "text/plain; charset=utf-8",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=10) as response:
                    if 200 <= response.status < 300:
                        accepted_workers.add(destination["worker_id"])
                        accepted_count += 1
                    else:
                        failed_workers.add(destination["worker_id"])
            except (HTTPError, URLError, TimeoutError, OSError, ValueError):
                failed_workers.add(destination["worker_id"])

        for worker_id in accepted_workers:
            connection.execute(
                """
                INSERT INTO audit_events
                    (actor_username, action, target_type, target_id, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "admin", "work_mission_notification_sent", "work_mission", str(mission_id),
                    json.dumps({"worker_id": worker_id, "delivery": "accepted_by_ntfy"}),
                ),
            )
        failed_delivery_workers = set(data.worker_ids) - accepted_workers
        for worker_id in failed_delivery_workers:
            connection.execute(
                "UPDATE mission_invitations SET status = 'revoked' WHERE mission_id = ? AND worker_id = ? AND status = 'pending'",
                (mission_id, worker_id),
            )
        if accepted_count == 0:
            connection.commit()
            raise HTTPException(status_code=502, detail="Aucune notification acceptée par ntfy.")
        return {
            "ok": not failed_workers,
            "accepted_workers": [matched[item]["full_name"] for item in sorted(accepted_workers)],
            "failed_workers": [matched[item]["full_name"] for item in sorted(failed_workers)],
            "accepted_count": accepted_count,
            "message": "Notifications transmises. Les profils disposent de 48 heures pour accepter ou refuser.",
        }


class MissionInvitationDecision(BaseModel):
    decision: str = Field(pattern=r"^(accepted|declined)$")


def _mission_invitation_for_token(connection, token: str):
    if not token or len(token) > 200:
        raise HTTPException(status_code=404, detail="Lien de réponse invalide")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = connection.execute(
        """SELECT i.*, m.title AS mission_title, m.client_name, m.location,
                  m.starts_at, m.ends_at, w.full_name AS worker_name
           FROM mission_invitations i
           JOIN work_missions m ON m.id = i.mission_id
           JOIN interim_workers w ON w.id = i.worker_id
           WHERE i.token_hash = ?""",
        (token_hash,),
    ).fetchone()
    if row is None or row["status"] == "revoked":
        raise HTTPException(status_code=404, detail="Lien de réponse invalide ou annulé")
    try:
        expiry = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=410, detail="Lien de réponse expiré")
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Lien de réponse expiré")
    return row


@app.get("/mission-invitations/respond")
def get_mission_invitation(token: str):
    with get_connection() as connection:
        invitation = _mission_invitation_for_token(connection, token)
        contract_rows = connection.execute(
            """SELECT id, status FROM contract_signature_drafts
               WHERE mission_id = ? AND worker_id = ? ORDER BY created_at DESC, id DESC""",
            (invitation["mission_id"], invitation["worker_id"]),
        ).fetchall()
    ready = [row for row in contract_rows if row["status"] in ("draft", "failed")]
    already_sent = [row for row in contract_rows if row["status"] in ("sent", "partially_signed", "signed")]
    contract_status = (
        "review_required" if len(ready) > 1 else
        "ready" if len(ready) == 1 else
        "already_sent" if already_sent else
        "not_prepared"
    )
    return {
        "mission_title": invitation["mission_title"],
        "client_name": invitation["client_name"],
        "location": invitation["location"],
        "starts_at": invitation["starts_at"],
        "ends_at": invitation["ends_at"],
        "worker_name": invitation["worker_name"],
        "status": invitation["status"],
        "expires_at": invitation["expires_at"],
        "contract_status": contract_status,
    }


@app.post("/mission-invitations/respond")
def respond_to_mission_invitation(token: str, decision: MissionInvitationDecision):
    contract_draft_id = None
    contract_already_sent = False
    contract_requires_review = False
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        invitation = _mission_invitation_for_token(connection, token)
        if invitation["status"] != "pending":
            raise HTTPException(status_code=409, detail="Une réponse a déjà été enregistrée pour cette proposition")

        if decision.decision == "accepted":
            contract_rows = connection.execute(
                """SELECT id, status FROM contract_signature_drafts
                   WHERE mission_id = ? AND worker_id = ? ORDER BY created_at DESC, id DESC""",
                (invitation["mission_id"], invitation["worker_id"]),
            ).fetchall()
            ready = [row for row in contract_rows if row["status"] in ("draft", "failed")]
            if len(ready) > 1:
                contract_requires_review = True
            elif ready:
                contract_draft_id = ready[0]["id"]
            elif not ready:
                contract_already_sent = any(
                    row["status"] in ("sent", "partially_signed", "signed")
                    for row in contract_rows
                )

        new_status = decision.decision
        now = datetime.now(timezone.utc).isoformat()
        updated = connection.execute(
            """UPDATE mission_invitations
               SET status = ?, responded_at = ?, contract_draft_id = ?
               WHERE id = ? AND status = 'pending'""",
            (new_status, now, contract_draft_id, invitation["id"]),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="Une réponse a déjà été enregistrée pour cette proposition")
        if decision.decision == "accepted":
            connection.execute(
                """INSERT INTO audit_events
                   (actor_username, action, target_type, target_id, details_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    "worker_response", "mission_invitation_accepted", "work_mission",
                    str(invitation["mission_id"]),
                    json.dumps({"worker_id": invitation["worker_id"], "invitation_id": invitation["id"]}),
                ),
            )
        else:
            connection.execute(
                """INSERT INTO audit_events
                   (actor_username, action, target_type, target_id, details_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    "worker_response", "mission_invitation_declined", "work_mission",
                    str(invitation["mission_id"]),
                    json.dumps({"worker_id": invitation["worker_id"], "invitation_id": invitation["id"]}),
                ),
            )

    if decision.decision == "declined":
        return {"status": "declined", "contract_sent": False, "message": "Votre refus est enregistré. Aucun contrat ne sera envoyé."}
    if contract_requires_review:
        return {"status": "accepted", "contract_sent": False, "message": "Votre acceptation est enregistrée. Plusieurs contrats sont préparés; l’agence doit vérifier lequel vous envoyer."}
    if contract_already_sent:
        return {"status": "accepted", "contract_sent": True, "message": "Votre acceptation est enregistrée. Le contrat avait déjà été envoyé par e-mail."}
    if contract_draft_id is None:
        return {"status": "accepted", "contract_sent": False, "message": "Votre acceptation est enregistrée. Le contrat n’est pas encore préparé; l’agence pourra vous l’envoyer ensuite."}
    return {
        "status": "accepted",
        "contract_sent": False,
        "contract_pending_approval": True,
        "message": "Votre acceptation est enregistrée. Le contrat sera envoyé après validation par le responsable RH.",
    }


@app.get("/work-missions/{mission_id}/responses")
def list_mission_invitation_responses(
    mission_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        mission = connection.execute(
            "SELECT id FROM work_missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        rows = connection.execute(
            """SELECT i.id, i.worker_id, w.full_name, i.status, i.created_at,
                      i.responded_at, i.expires_at, d.status AS contract_status
               FROM mission_invitations i
               JOIN interim_workers w ON w.id = i.worker_id
               LEFT JOIN contract_signature_drafts d ON d.id = i.contract_draft_id
               WHERE i.mission_id = ? AND i.status != 'revoked'
               ORDER BY i.id DESC""",
            (mission_id,),
        ).fetchall()
    latest_by_worker = {}
    for row in rows:
        item = dict(row)
        if item["status"] == "pending":
            try:
                if datetime.fromisoformat(item["expires_at"]) <= datetime.now(timezone.utc):
                    item["status"] = "expired"
            except (TypeError, ValueError):
                item["status"] = "expired"
        latest_by_worker.setdefault(item["worker_id"], item)
    return list(latest_by_worker.values())


@app.get("/dashboard/missions")
def mission_dashboard(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        mission_rows = connection.execute(
            """
            SELECT m.*,
                   (SELECT COUNT(*) FROM work_assignments a
                    WHERE a.mission_id = m.id AND a.status = 'assigned') AS assigned_count
            FROM work_missions m
            ORDER BY CASE WHEN m.status = 'open' THEN 0 ELSE 1 END,
                     CASE WHEN m.starts_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') THEN 0 ELSE 1 END,
                     m.starts_at ASC, m.id DESC
            """
        ).fetchall()
        active_workers = connection.execute(
            "SELECT COUNT(*) FROM interim_workers WHERE status = 'active'"
        ).fetchone()[0]
        notifications_7_days = connection.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE action = 'work_mission_notification_sent'
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-7 days')
            """
        ).fetchone()[0]

        mission_cards = []
        open_missions = 0
        positions_to_fill = 0
        available_matches = 0
        for row in mission_rows:
            mission = _work_mission_dict(row)
            match_count = len(_work_mission_matches(connection, row)) if row["status"] == "open" else 0
            if row["status"] == "open":
                open_missions += 1
                positions_to_fill += max(0, row["required_workers"] - row["assigned_count"])
                available_matches += match_count
            mission_cards.append({
                "id": mission["id"],
                "title": mission["title"],
                "client_name": mission.get("client_name", ""),
                "sector": mission["sector"],
                "location": mission["location"],
                "starts_at": mission["starts_at"],
                "ends_at": mission["ends_at"],
                "status": mission["status"],
                "required_workers": mission["required_workers"],
                "assigned_count": row["assigned_count"],
                "match_count": match_count,
            })

    return {
        "metrics": {
            "open_missions": open_missions,
            "active_workers": active_workers,
            "positions_to_fill": positions_to_fill,
            "available_matches": available_matches,
            "notifications_7_days": notifications_7_days,
        },
        "missions": mission_cards[:6],
    }


def _work_audit(connection, action, assignment_id, mission_id, worker_id, details):
    connection.execute(
        """
        INSERT INTO audit_events
            (actor_username, action, target_type, target_id, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "admin",
            action,
            "work_assignment",
            str(assignment_id),
            json.dumps(
                {
                    "mission_id": mission_id,
                    "worker_id": worker_id,
                    **details,
                },
                ensure_ascii=False,
            ),
        ),
    )


@app.get("/work-missions/{mission_id}/assignments")
def list_work_assignments(
    mission_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        mission = connection.execute(
            "SELECT id FROM work_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()

        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")

        rows = connection.execute(
            """
            SELECT a.id, a.mission_id, a.worker_id, w.full_name,
                   a.status, a.notes, a.created_at, a.updated_at
            FROM work_assignments AS a
            JOIN interim_workers AS w ON w.id = a.worker_id
            WHERE a.mission_id = ?
            ORDER BY a.id
            """,
            (mission_id,),
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/work-missions/{mission_id}/assignments", status_code=201)
def create_work_assignment(
    mission_id: int,
    data: WorkAssignmentCreate,
    _admin: bool = Depends(require_admin),
):
    notes = data.notes.strip()

    with get_connection() as connection:
        # Verrouille l'écriture avant les contrôles d'effectif et de conflit.
        connection.execute("BEGIN IMMEDIATE")

        mission = connection.execute(
            "SELECT * FROM work_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()

        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")

        if mission["status"] != "open":
            raise HTTPException(
                status_code=409,
                detail="La mission doit être ouverte pour recevoir une affectation",
            )

        worker = connection.execute(
            "SELECT id, status FROM interim_workers WHERE id = ?",
            (data.worker_id,),
        ).fetchone()

        if worker is None:
            raise HTTPException(status_code=404, detail="Intérimaire introuvable")

        if worker["status"] != "active":
            raise HTTPException(
                status_code=409,
                detail="L'intérimaire n'est pas actif",
            )

        profile = connection.execute(
            "SELECT * FROM interim_worker_profiles WHERE worker_id = ?",
            (data.worker_id,),
        ).fetchone()

        if profile is None:
            raise HTTPException(
                status_code=409,
                detail="Le profil professionnel doit être renseigné",
            )

        sectors = json.loads(profile["sectors_json"] or "[]")
        qualifications = json.loads(profile["qualifications_json"] or "[]")
        required_qualifications = json.loads(
            mission["required_qualifications_json"] or "[]"
        )

        if not any(
            str(sector).strip().casefold() == mission["sector"].strip().casefold()
            for sector in sectors
        ):
            raise HTTPException(
                status_code=409,
                detail="Le secteur de la mission ne figure pas dans le profil",
            )

        missing = [
            required for required in required_qualifications
            if required not in qualifications
        ]
        if missing:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Qualifications obligatoires manquantes",
                    "missing_qualifications": missing,
                },
            )

        mission_start = _work_datetime(mission["starts_at"])
        mission_end = _work_datetime(mission["ends_at"])

        # Vérifie qu'une période disponible couvre toute la mission.
        periods = connection.execute(
            """
            SELECT period_type, starts_at, ends_at
            FROM worker_availabilities
            WHERE worker_id = ?
            """,
            (data.worker_id,),
        ).fetchall()

        try:
            available_covers_mission = any(
                period["period_type"] == "available"
                and _work_datetime(period["starts_at"]) <= mission_start
                and _work_datetime(period["ends_at"]) >= mission_end
                for period in periods
            )

            unavailable_overlaps = any(
                period["period_type"] == "unavailable"
                and _work_datetime(period["starts_at"]) < mission_end
                and _work_datetime(period["ends_at"]) > mission_start
                for period in periods
            )
        except TypeError:
            raise HTTPException(
                status_code=409,
                detail="Les fuseaux horaires des disponibilités sont incompatibles",
            )

        if not available_covers_mission:
            raise HTTPException(
                status_code=409,
                detail="Aucune période disponible ne couvre toute la mission",
            )

        if unavailable_overlaps:
            raise HTTPException(
                status_code=409,
                detail="Une période d'indisponibilité chevauche la mission",
            )

        existing = connection.execute(
            """
            SELECT id FROM work_assignments
            WHERE mission_id = ? AND worker_id = ?
            """,
            (mission_id, data.worker_id),
        ).fetchone()

        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Cet intérimaire possède déjà une affectation pour cette mission",
            )

        active_count = connection.execute(
            """
            SELECT COUNT(*) FROM work_assignments
            WHERE mission_id = ? AND status = 'assigned'
            """,
            (mission_id,),
        ).fetchone()[0]

        if active_count >= mission["required_workers"]:
            raise HTTPException(
                status_code=409,
                detail="L'effectif demandé pour cette mission est déjà atteint",
            )

        other_assignments = connection.execute(
            """
            SELECT a.id, m.starts_at, m.ends_at
            FROM work_assignments AS a
            JOIN work_missions AS m ON m.id = a.mission_id
            WHERE a.worker_id = ?
              AND a.status = 'assigned'
              AND a.mission_id != ?
            """,
            (data.worker_id, mission_id),
        ).fetchall()

        try:
            for other in other_assignments:
                other_start = _work_datetime(other["starts_at"])
                other_end = _work_datetime(other["ends_at"])

                if other_start < mission_end and other_end > mission_start:
                    raise HTTPException(
                        status_code=409,
                        detail="L'intérimaire est déjà affecté à une mission sur ces horaires",
                    )
        except TypeError:
            raise HTTPException(
                status_code=409,
                detail="Les fuseaux horaires des missions sont incompatibles",
            )

        cursor = connection.execute(
            """
            INSERT INTO work_assignments (mission_id, worker_id, status, notes)
            VALUES (?, ?, 'assigned', ?)
            """,
            (mission_id, data.worker_id, notes),
        )
        assignment_id = cursor.lastrowid

        new_count = active_count + 1
        if new_count >= mission["required_workers"]:
            connection.execute(
                """
                UPDATE work_missions
                SET status = 'filled',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (mission_id,),
            )

        _work_audit(
            connection,
            "work_assignment_created",
            assignment_id,
            mission_id,
            data.worker_id,
            {"status": "assigned"},
        )

        row = connection.execute(
            """
            SELECT a.id, a.mission_id, a.worker_id, w.full_name,
                   a.status, a.notes, a.created_at, a.updated_at
            FROM work_assignments AS a
            JOIN interim_workers AS w ON w.id = a.worker_id
            WHERE a.id = ?
            """,
            (assignment_id,),
        ).fetchone()

    return dict(row)


@app.post("/work-assignments/{assignment_id}/cancel")
def cancel_work_assignment(
    assignment_id: int,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        assignment = connection.execute(
            """
            SELECT id, mission_id, worker_id, status
            FROM work_assignments WHERE id = ?
            """,
            (assignment_id,),
        ).fetchone()

        if assignment is None:
            raise HTTPException(status_code=404, detail="Affectation introuvable")

        if assignment["status"] != "assigned":
            raise HTTPException(
                status_code=409,
                detail="Cette affectation n'est pas active",
            )

        connection.execute(
            """
            UPDATE work_assignments
            SET status = 'cancelled',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (assignment_id,),
        )

        connection.execute(
            """
            UPDATE work_missions
            SET status = 'open',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND status = 'filled'
            """,
            (assignment["mission_id"],),
        )

        _work_audit(
            connection,
            "work_assignment_cancelled",
            assignment_id,
            assignment["mission_id"],
            assignment["worker_id"],
            {"status": "cancelled"},
        )

        row = connection.execute(
            """
            SELECT id, mission_id, worker_id, status, notes,
                   created_at, updated_at
            FROM work_assignments WHERE id = ?
            """,
            (assignment_id,),
        ).fetchone()

    return dict(row)


@app.post("/interim-workers/{worker_id}/decision")
def decide_interim_worker(
    worker_id: int,
    data: InterimWorkerDecision,
    _admin: bool = Depends(require_admin),
):
    note = data.note.strip() if data.note and data.note.strip() else None

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id, status, decision FROM interim_workers WHERE id = ?",
            (worker_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Fiche intérimaire introuvable")

        new_status = existing["status"]
        connection.execute(
            """
            UPDATE interim_workers
            SET decision = ?, decision_note = ?, status = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (data.decision, note, new_status, worker_id),
        )
        _interim_audit(connection, "interim_worker_decision", worker_id, {
            "decision": data.decision,
            "note": note,
        })
        return _interim_get_worker(connection, worker_id)


# --- Clients professionnels ---

class ProfessionalClientInput(BaseModel):
    company_name: str = Field(min_length=1, max_length=180)
    sector: str = Field(default="", max_length=100)
    contact_name: str = Field(default="", max_length=150)
    phone: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=254)
    address: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=3000)


class ProfessionalClientStatus(BaseModel):
    status: str = Field(pattern=r"^(active|inactive)$")


def _professional_client_audit(connection, action, client_id, details):
    connection.execute(
        """
        INSERT INTO audit_events
            (actor_username, action, target_type, target_id, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "admin",
            action,
            "professional_client",
            str(client_id),
            json.dumps(details, ensure_ascii=False),
        ),
    )


def _professional_client_values(data):
    values = {
        key: getattr(data, key).strip()
        for key in (
            "company_name", "sector", "contact_name",
            "phone", "email", "address", "notes"
        )
    }
    if not values["company_name"]:
        raise HTTPException(
            status_code=422,
            detail="Le nom de l'entreprise est obligatoire.",
        )
    return values


@app.get("/professional-clients")
def list_professional_clients(_admin: bool = Depends(require_admin)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM professional_clients
            ORDER BY
                CASE status WHEN 'active' THEN 0 ELSE 1 END,
                company_name COLLATE NOCASE, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/professional-clients", status_code=201)
def create_professional_client(
    data: ProfessionalClientInput,
    _admin: bool = Depends(require_admin),
):
    values = _professional_client_values(data)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO professional_clients
                (company_name, sector, contact_name, phone, email, address, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(values.values()),
        )
        client_id = cursor.lastrowid
        _professional_client_audit(
            connection, "professional_client_created", client_id,
            {"company_name": values["company_name"]},
        )
        row = connection.execute(
            "SELECT * FROM professional_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
    return dict(row)


@app.put("/professional-clients/{client_id}")
def update_professional_client(
    client_id: int,
    data: ProfessionalClientInput,
    _admin: bool = Depends(require_admin),
):
    values = _professional_client_values(data)
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM professional_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Client introuvable.")

        connection.execute(
            """
            UPDATE professional_clients
            SET company_name = ?, sector = ?, contact_name = ?, phone = ?,
                email = ?, address = ?, notes = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (*values.values(), client_id),
        )
        _professional_client_audit(
            connection, "professional_client_updated", client_id,
            {"company_name": values["company_name"]},
        )
        row = connection.execute(
            "SELECT * FROM professional_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
    return dict(row)


@app.patch("/professional-clients/{client_id}/status")
def change_professional_client_status(
    client_id: int,
    data: ProfessionalClientStatus,
    _admin: bool = Depends(require_admin),
):
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id, company_name FROM professional_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Client introuvable.")

        connection.execute(
            """
            UPDATE professional_clients
            SET status = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (data.status, client_id),
        )
        _professional_client_audit(
            connection, "professional_client_status_changed", client_id,
            {"company_name": existing["company_name"], "status": data.status},
        )
        row = connection.execute(
            "SELECT * FROM professional_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
    return dict(row)
