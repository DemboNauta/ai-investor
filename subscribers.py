"""Gestión de suscriptores con doble opt-in."""
import sqlite3
import hashlib
import secrets
import os
import re
import urllib.parse
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DB_PATH  = os.path.join(os.path.dirname(__file__), "subscribers.db")
_SECRET  = os.getenv("UNSUB_SECRET", "cai-unsub-2026")
BASE_URL = os.getenv("BASE_URL", "https://cryptoaiarena.com")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS subscribers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    UNIQUE NOT NULL,
            ip            TEXT    DEFAULT '',
            created_at    TEXT    NOT NULL,
            confirmed     INTEGER NOT NULL DEFAULT 0,
            confirm_token TEXT,
            active        INTEGER NOT NULL DEFAULT 1
        )""")


_init()


def _valid(email: str) -> bool:
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))


def unsub_token(email: str) -> str:
    """Token de baja derivado del email — no requiere DB."""
    return hashlib.sha256(f"{email}:{_SECRET}".encode()).hexdigest()[:40]


def unsub_url(email: str) -> str:
    return f"{BASE_URL}/api/unsubscribe?email={urllib.parse.quote(email)}&token={unsub_token(email)}"


def confirm_url(email: str, token: str) -> str:
    return f"{BASE_URL}/api/confirm?email={urllib.parse.quote(email)}&token={token}"


def add_pending(email: str, ip: str = "") -> tuple[bool, str, str]:
    """
    Añade suscriptor como pendiente de confirmación.
    Returns (ok, message, confirm_token).
    """
    email = email.strip().lower()
    if not _valid(email):
        return False, "Email inválido", ""

    tok = secrets.token_urlsafe(32)
    try:
        with _conn() as c:
            row = c.execute("SELECT confirmed, active FROM subscribers WHERE email=?", (email,)).fetchone()
            if row:
                if row["confirmed"] and row["active"]:
                    return False, "Ya estás suscrito", ""
                # Reactivar o reenviar confirmación
                c.execute(
                    "UPDATE subscribers SET confirmed=0, confirm_token=?, ip=?, created_at=?, active=1 WHERE email=?",
                    (tok, ip, datetime.now(timezone.utc).isoformat(), email),
                )
            else:
                c.execute(
                    "INSERT INTO subscribers (email, ip, created_at, confirm_token) VALUES (?,?,?,?)",
                    (email, ip, datetime.now(timezone.utc).isoformat(), tok),
                )
        return True, "ok", tok
    except Exception as e:
        return False, f"Error: {e}", ""


def confirm(email: str, token: str) -> bool:
    """Confirma suscripción. Devuelve True si OK."""
    email = email.strip().lower()
    with _conn() as c:
        row = c.execute(
            "SELECT confirm_token, confirmed FROM subscribers WHERE email=? AND active=1",
            (email,),
        ).fetchone()
        if not row or row["confirm_token"] != token:
            return False
        if row["confirmed"]:
            return True  # ya confirmado, OK idempotente
        c.execute(
            "UPDATE subscribers SET confirmed=1, confirm_token=NULL WHERE email=?",
            (email,),
        )
    return True


def remove(email: str, tok: str) -> bool:
    email = email.strip().lower()
    if tok != unsub_token(email):
        return False
    with _conn() as c:
        c.execute("UPDATE subscribers SET active=0 WHERE email=?", (email,))
    return True


def get_all() -> list[str]:
    """Solo confirmados y activos."""
    with _conn() as c:
        return [r["email"] for r in
                c.execute(
                    "SELECT email FROM subscribers WHERE confirmed=1 AND active=1"
                ).fetchall()]


def count() -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM subscribers WHERE confirmed=1 AND active=1"
        ).fetchone()[0]
