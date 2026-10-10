
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from app.db import initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="ntfy-admin API",
    description="API d'administration de notre serveur ntfy personnel.",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/")
def home():
    return {
        "application": "ntfy-admin",
        "status": "running",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
