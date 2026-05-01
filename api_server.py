"""API server — chat con agentes, suscripciones y alertas. Puerto 5001."""
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
from config import XAI_API_KEY, XAI_BASE_URL, MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from profiles import PROFILES
import memory as mem
import portfolio as pf
import data as market_data
import requests as _req
from agent import _FETCH_NEWS_TOOL, _GET_COIN_DETAILS_TOOL, _to_responses_tool, _to_xai_tool
import subscribers
import notifier

PORT = int(os.getenv("CHAT_PORT", "5001"))
RATE_LIMIT = 5        # max requests
RATE_WINDOW = 60      # per N seconds
DB_PATH = os.getenv("CHAT_DB", "chat_history.db")
MAX_HISTORY = 20      # messages kept in context

# {ip: [timestamp, ...]}
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_sub_buckets:  dict[str, list[float]] = defaultdict(list)  # subscribe rate limit
SUB_RATE_MAX = 3  # max subscribe attempts per minute per IP


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
    con.execute("""
        CREATE TABLE IF NOT EXISTS chat_state (
            profile     TEXT PRIMARY KEY,
            response_id TEXT,
            updated_ts  TEXT NOT NULL DEFAULT (datetime('now'))
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


def _save_messages(profile: str, user_msg: str, assistant_msg: str, response_id: str = None):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO messages (profile, role, content) VALUES (?, 'user', ?)", (profile, user_msg))
    con.execute("INSERT INTO messages (profile, role, content) VALUES (?, 'assistant', ?)", (profile, assistant_msg))
    if response_id:
        con.execute(
            "INSERT INTO chat_state (profile, response_id, updated_ts) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(profile) DO UPDATE SET response_id=excluded.response_id, updated_ts=excluded.updated_ts",
            (profile, response_id),
        )
    con.commit()
    con.close()


def _get_last_response_id(profile: str) -> str | None:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        # Only reuse if updated within last 30 minutes (OpenAI TTL safe window)
        "SELECT response_id FROM chat_state WHERE profile=? "
        "AND updated_ts > datetime('now', '-30 minutes')",
        (profile,),
    ).fetchone()
    con.close()
    return row[0] if row else None


def _clear_response_id(profile: str):
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE chat_state SET response_id=NULL WHERE profile=?", (profile,))
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


def _build_prices_summary() -> str:
    """Compact live price table from disk cache (no extra API calls)."""
    try:
        md = market_data.get_all_market_data_cached()
        coins = md.get("coins", [])
        lines = ["LIVE PRICES (EUR) — top 50 by market cap:"]
        for c in coins:
            chg24 = c.get("price_change_percentage_24h_in_currency")
            chg24_str = f"{chg24:+.1f}%" if chg24 is not None else "n/a"
            lines.append(f"  {c['id']:<22} €{c['current_price']:<14.4f} 24h: {chg24_str}")
        fg = md.get("fear_greed", {})
        if fg.get("value") is not None:
            lines.append(f"Fear & Greed: {fg['value']}/100 ({fg['label']})")
        return "\n".join(lines)
    except Exception:
        return ""


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

    prices_summary = _build_prices_summary()

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

{prices_summary}

You are now in CHAT MODE. A human is asking you questions about your portfolio, \
decisions, strategy, or the market. You cannot execute trades here — this is Q&A only.

COMMUNICATION RULES:
- Answer in the same language the user writes in.
- Write as if explaining to someone who is curious about crypto but not an expert. \
Assume the person reading has no trading background — they should be able to understand \
your answer without knowing what "BTC dominance", "funding rates", or "momentum" mean.
- When you mention any trading concept or metric, explain it briefly in simple words.
- Be conversational and human. Short and clear is better than complete and technical.
- Show personality consistent with your profile: \
Moderate = calm and measured. Aggressive = confident and decisive. Degen = bold and direct.

TOOLS AVAILABLE IN CHAT:
- fetch_news([keyword]): Get latest crypto headlines. Use when asked about news or sentiment.
- get_coin_details(coin_id): Deep dev/community data on a specific coin."""


_CHAT_TOOLS = [_FETCH_NEWS_TOOL, _GET_COIN_DETAILS_TOOL]
_CHAT_TOOLS_RESPONSES = [_to_responses_tool(t) for t in _CHAT_TOOLS]


def _make_chat_client(profile_key: str):
    """Returns (client, model, provider) for the given profile."""
    provider = PROFILES.get(profile_key, {}).get("provider", "xai")
    if provider == "openai":
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL), OPENAI_MODEL, "openai"
    from xai_sdk import Client as _XAIClient
    return _XAIClient(api_key=XAI_API_KEY), MODEL, "xai"


def _exec_tool(fn: str, args: dict) -> str:
    if fn == "fetch_news":
        keyword = args.get("filter_keyword", "").strip().lower()
        headlines = market_data.get_crypto_news(max_items=15)
        if keyword:
            headlines = [h for h in headlines if keyword in h.lower()]
        if headlines:
            return "RECENT NEWS:\n" + "\n".join(f"• {h}" for h in headlines)
        return f"No news found{' for: ' + keyword if keyword else ''}."

    if fn == "get_coin_details":
        coin_id = args["coin_id"]
        try:
            resp = _req.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization": "false", "tickers": "false",
                        "community_data": "true", "developer_data": "true"},
                timeout=15,
            )
            resp.raise_for_status()
            d = resp.json()
            desc = (d.get("description", {}).get("en") or "")[:400].replace("\r\n", " ")
            cats = ", ".join((d.get("categories") or [])[:5])
            dev = d.get("developer_data", {})
            comm = d.get("community_data", {})
            mkt = d.get("market_data", {})
            price_eur = mkt.get("current_price", {}).get("eur")
            chg24 = mkt.get("price_change_percentage_24h")
            price_str = f"€{price_eur:.4f}" if price_eur else "n/a"
            chg_str = f"{chg24:+.2f}%" if chg24 is not None else "n/a"
            return (
                f"COIN: {d.get('name')} ({d.get('symbol', '').upper()})\n"
                f"Current price: {price_str} (24h: {chg_str})\n"
                f"Description: {desc}...\n"
                f"Categories: {cats}\n"
                f"GitHub stars: {dev.get('stars', 'n/a')} | Forks: {dev.get('forks', 'n/a')} | "
                f"Commits 4w: {dev.get('commit_count_4_weeks', 'n/a')}\n"
                f"Twitter followers: {comm.get('twitter_followers', 'n/a')} | "
                f"Reddit subscribers: {comm.get('reddit_subscribers', 'n/a')}"
            )
        except Exception as e:
            return f"ERROR fetching '{coin_id}': {e}"

    return f"unknown tool: {fn}"


def _handle_chat(profile_key: str, user_msg: str) -> str:
    if profile_key not in PROFILES:
        return "Unknown profile."

    llm_client, model, provider = _make_chat_client(profile_key)
    system_prompt = _build_context(profile_key)
    history = _load_history(profile_key)
    prev_id = _get_last_response_id(profile_key)

    if provider == "openai":
        answer, new_id = _handle_chat_openai(llm_client, model, system_prompt, history, user_msg, prev_id)
    else:
        answer, new_id = _handle_chat_xai(llm_client, model, system_prompt, history, user_msg, prev_id)

    _save_messages(profile_key, user_msg, answer, response_id=new_id)
    return answer


def _handle_chat_openai(oai_client, model: str, system_prompt: str, history: list,
                        user_msg: str, prev_id: str | None) -> tuple[str, str | None]:
    """OpenAI Responses API — stateful across turns via previous_response_id."""
    if prev_id:
        # Continue existing conversation — only send the new user message
        try:
            response = oai_client.responses.create(
                model=model,
                input=[{"role": "user", "content": user_msg}],
                previous_response_id=prev_id,
                tools=_CHAT_TOOLS_RESPONSES,
                max_output_tokens=800,
            )
        except Exception:
            # ID expired or invalid — fall back to full history
            prev_id = None

    if not prev_id:
        input_msgs = [{"role": m["role"], "content": m["content"]} for m in history]
        input_msgs.append({"role": "user", "content": user_msg})
        response = oai_client.responses.create(
            model=model,
            instructions=system_prompt,
            input=input_msgs,
            tools=_CHAT_TOOLS_RESPONSES,
            max_output_tokens=800,
        )

    for _ in range(8):
        tool_calls = [item for item in response.output if item.type == "function_call"]
        if not tool_calls:
            break
        tool_outputs = []
        for item in tool_calls:
            result = _exec_tool(item.name, json.loads(item.arguments))
            tool_outputs.append({"type": "function_call_output", "call_id": item.call_id, "output": result})
        response = oai_client.responses.create(
            model=model,
            input=tool_outputs,
            previous_response_id=response.id,
            tools=_CHAT_TOOLS_RESPONSES,
            max_output_tokens=800,
        )

    for item in response.output:
        if item.type == "message":
            for c in item.content:
                if hasattr(c, "text"):
                    return c.text, response.id
    return "Error: no response.", None


def _handle_chat_xai(xai_client, model: str, system_prompt: str, history: list,
                     user_msg: str, prev_id: str | None) -> tuple[str, str | None]:
    """xAI SDK — stateful across turns via previous_response_id."""
    from xai_sdk.chat import user as _user, system as _system, assistant as _assistant, tool_result as _tr

    tools_x = [_to_xai_tool(t) for t in _CHAT_TOOLS]

    if prev_id:
        try:
            chat = xai_client.chat.create(
                model=model, store_messages=True,
                previous_response_id=prev_id, tools=tools_x,
            )
            chat.append(_user(user_msg))
            response = chat.sample()
        except Exception:
            prev_id = None

    if not prev_id:
        chat = xai_client.chat.create(model=model, store_messages=True, tools=tools_x)
        chat.append(_system(system_prompt))
        for m in history:
            if m["role"] == "user":
                chat.append(_user(m["content"]))
            elif m["role"] == "assistant":
                chat.append(_assistant(m["content"]))
        chat.append(_user(user_msg))
        response = chat.sample()

    for _ in range(8):
        if not response.tool_calls:
            break
        next_chat = xai_client.chat.create(
            model=model, store_messages=True,
            previous_response_id=response.id, tools=tools_x,
        )
        for tc in response.tool_calls:
            result = _exec_tool(tc.function.name, json.loads(tc.function.arguments))
            next_chat.append(_tr(result, tool_call_id=tc.id))
        response = next_chat.sample()

    return response.content or "Error: no response.", response.id


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
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        path   = parsed.path

        # Confirm subscription
        if path == "/api/confirm":
            params = parse_qs(parsed.query)
            email  = params.get("email", [""])[0]
            tok    = params.get("token", [""])[0]
            ok = subscribers.confirm(email, tok)
            if ok:
                try:
                    notifier.notify_welcome(email)
                except Exception as e:
                    print(f"[api] Welcome email error: {e}")
            html = (
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px;background:#06060d;color:#e8e8f0'>"
                b"<h2 style='color:#00ff87'>\xe2\x9c\x85 \xc2\xa1Suscripci\xc3\xb3n confirmada!</h2>"
                b"<p>Ya recibir\xc3\xa1s el resumen diario y alertas de CryptoAiArena.</p>"
                b"<a href='https://cryptoaiarena.com' style='color:#00d4ff'>Ver dashboard</a>"
                b"</body></html>"
            ) if ok else (
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px;background:#06060d;color:#e8e8f0'>"
                b"<h2 style='color:#ff4466'>\xe2\x9d\x8c Enlace inv\xc3\xa1lido o expirado.</h2>"
                b"<p>Vuelve a suscribirte en <a href='https://cryptoaiarena.com' style='color:#00d4ff'>cryptoaiarena.com</a></p>"
                b"</body></html>"
            )
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)
            return

        # Unsubscribe
        if path == "/api/unsubscribe":
            params = parse_qs(parsed.query)
            email  = params.get("email", [""])[0]
            tok    = params.get("token", [""])[0]
            ok = subscribers.remove(email, tok)
            html = (
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                b"<h2>\xe2\x9c\x85 Suscripci\xc3\xb3n cancelada.</h2>"
                b"<p>Ya no recibir\xc3\xa1s alertas de CryptoAiArena.</p></body></html>"
            ) if ok else (
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                b"<h2>\xe2\x9d\x8c Enlace inv\xc3\xa1lido.</h2></body></html>"
            )
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)
            return

        if path == "/api/last-update":
            import glob as _glob
            base = os.path.dirname(os.path.abspath(__file__))
            files = _glob.glob(os.path.join(base, "portfolio_*.json"))
            ts = max((os.path.getmtime(f) for f in files), default=0)
            self._json(200, {"ts": ts})
            return

        profile_key = self._profile_from_path(path)
        if not profile_key or profile_key not in PROFILES:
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        self._json(200, {"history": _load_history(profile_key)})

    def do_POST(self):
        path = urlparse(self.path).path

        # Subscribe endpoint — doble opt-in
        if path == "/api/subscribe":
            ip  = self.client_address[0]
            now = time.time()
            _sub_buckets[ip] = [t for t in _sub_buckets[ip] if now - t < RATE_WINDOW]
            if len(_sub_buckets[ip]) >= SUB_RATE_MAX:
                self._json(429, {"error": "Demasiados intentos, espera un minuto."})
                return
            _sub_buckets[ip].append(now)

            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                email = json.loads(body).get("email", "").strip()
            except Exception:
                email = ""

            ok, msg, tok = subscribers.add_pending(email, ip)
            if ok:
                try:
                    url = subscribers.confirm_url(email, tok)
                    notifier.notify_confirmation(email, url)
                except Exception as e:
                    print(f"[api] Confirmation email error: {e}")
            self._json(200 if ok else 400, {"ok": ok, "message": msg})
            return

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
