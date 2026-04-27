"""Chat server — responde preguntas sobre cada agente. Puerto 5001."""
import os
import json
import time
import sqlite3
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI
from config import XAI_API_KEY, XAI_BASE_URL, MODEL
from profiles import PROFILES
import memory as mem
import portfolio as pf

client = OpenAI(api_key=XAI_API_KEY, base_url=XAI_BASE_URL)

PORT = int(os.getenv("CHAT_PORT", "5001"))
RATE_LIMIT = 5        # max requests
RATE_WINDOW = 60      # per N seconds
DB_PATH = os.getenv("CHAT_DB", "chat_history.db")
MAX_HISTORY = 20      # messages kept in context

# {ip: [timestamp, ...]}
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT    NOT NULL,
            role    TEXT    NOT NULL,
            content TEXT    NOT NULL,
            ts      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()


def _load_history(profile: str) -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT role, content FROM messages WHERE profile=? ORDER BY id DESC LIMIT ?",
        (profile, MAX_HISTORY),
    ).fetchall()
    con.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def _save_messages(profile: str, user_msg: str, assistant_msg: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO messages (profile, role, content) VALUES (?, 'user', ?)",
        (profile, user_msg),
    )
    con.execute(
        "INSERT INTO messages (profile, role, content) VALUES (?, 'assistant', ?)",
        (profile, assistant_msg),
    )
    con.commit()
    con.close()

def _check_rate_limit(ip: str) -> bool:
    """Returns True if allowed, False if rate limited."""
    now = time.time()
    bucket = _rate_buckets[ip]
    # Drop timestamps outside window
    _rate_buckets[ip] = [t for t in bucket if now - t < RATE_WINDOW]
    if len(_rate_buckets[ip]) >= RATE_LIMIT:
        return False
    _rate_buckets[ip].append(now)
    return True


def _build_context(profile_key: str) -> str:
    profile = PROFILES[profile_key]
    port_data = pf.load(profile["portfolio_file"])
    profile_memory = mem.load(profile_key)
    memory_prompt = mem.format_for_prompt(profile_memory)

    cash = port_data.get("cash_eur", 0)
    cycle = port_data.get("cycle_count", 0)
    holdings = port_data.get("holdings", {})
    trades = port_data.get("trades", [])[-15:]
    thesis = profile_memory.get("thesis", "")

    holdings_lines = []
    for coin, pos in holdings.items():
        holdings_lines.append(
            f"  {coin}: {pos['amount']:.5f} units, avg cost €{pos['avg_buy_price_eur']:.4f}"
        )

    holdings_str = "\n".join(holdings_lines) if holdings_lines else "  (fully in cash)"

    trade_lines = []
    for t in trades:
        ts = t.get("ts", "")[:16].replace("T", " ")
        trade_lines.append(
            f"  [{ts}] {t['action'].upper()} {t['coin_id']} "
            f"€{t['amount_eur']:.2f} @ €{t['price_eur']:.4f}"
        )
    trades_str = "\n".join(trade_lines) if trade_lines else "  (none yet)"

    return f"""{profile['system_prompt']}
{memory_prompt}

--- CURRENT STATE ---
Cycle: #{cycle}
Cash: €{cash:.2f}
Holdings:
{holdings_str}
{"Current thesis: " + thesis if thesis else ""}

Recent trades (last 15):
{trades_str}
---------------------

You are now in CHAT MODE. A human is asking you a question about your portfolio, \
decisions, strategy, or the market. Answer clearly and concisely in the same language \
the user writes in. You cannot execute trades here — this is Q&A only."""


def _handle_chat(profile_key: str, user_msg: str) -> str:
    if profile_key not in PROFILES:
        return "Unknown profile."
    system = _build_context(profile_key)
    history = _load_history(profile_key)
    messages = history + [{"role": "user", "content": user_msg}]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}] + messages,
        max_tokens=600,
    )
    answer = resp.choices[0].message.content
    _save_messages(profile_key, user_msg, answer)
    return answer


class ChatHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[chat] {args[0]} {args[1]}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code: int, data):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _profile_from_path(self, path: str):
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "chat"]:
            return parts[2]
        return None

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        profile_key = self._profile_from_path(path)
        if not profile_key or profile_key not in PROFILES:
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        self._json(200, {"history": _load_history(profile_key)})

    def do_POST(self):
        path = urlparse(self.path).path
        profile_key = self._profile_from_path(path)

        if not profile_key or profile_key not in PROFILES:
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            message = json.loads(body).get("message", "").strip()
        except Exception:
            message = ""

        if not message:
            self._json(400, {"error": "empty message"})
            return

        ip = self.client_address[0]
        if not _check_rate_limit(ip):
            self.send_response(429)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b'{"error":"rate limit: max 5 requests per minute"}')
            return

        try:
            answer = _handle_chat(profile_key, message)
            self._json(200, {"response": answer})
        except Exception as e:
            self._json(500, {"error": str(e)})


if __name__ == "__main__":
    _init_db()
    server = HTTPServer(("0.0.0.0", PORT), ChatHandler)
    print(f"[chat] Servidor en puerto {PORT} · DB: {DB_PATH}")
    server.serve_forever()
