
import os
import subprocess
import re
import json
from urllib.error import URLError
from urllib.request import urlopen

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
