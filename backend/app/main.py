import os
import subprocess
import re
import json
import base64
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.db import get_connection, initialize_database

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PASSWORD_HASH = os.getenv("NTFY_ADMIN_PASSWORD_HASH")
SESSION_SECRET = os.getenv("NTFY_ADMIN_SESSION_SECRET")

if not PASSWORD_HASH or not SESSION_SECRET:
    raise RuntimeError("Configuration administrateur absente du fichier .env")

COOKIE_NAME = "ntfy_admin_session"
SESSION_MAX_AGE = 1800  # 30 minutes
password_hasher = PasswordHash.recommended()
serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="ntfy-admin-session")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="ntfy-admin API", version="0.4.0", lifespan=lifespan)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


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

    if session != {"user": "admin"}:
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
        valid = password_hasher.verify(data.password, PASSWORD_HASH)
    except Exception:
        valid = False

    if not valid:
        raise HTTPException(status_code=401, detail="Mot de passe incorrect")

    token = serializer.dumps({"user": "admin"})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=False,  # Usage local via HTTP uniquement ; activer HTTPS avant toute exposition.
        samesite="strict",
        path="/",
    )
    return {"authenticated": True}


@app.get("/me")
def me(_admin: bool = Depends(require_admin)):
    return {"authenticated": True, "user": "admin"}


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


def _interim_validate_phones(phone_ids: list[str]) -> list[str]:
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
        return [_interim_get_worker(connection, row["id"]) for row in ids]


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
    phone_ids = _interim_validate_phones(data.phone_ids)

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
