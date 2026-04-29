"""Twitter/X bot — daily scoreboard thread + notable trade tweets.

Env vars needed:
  TWITTER_API_KEY, TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
  TWITTER_ENABLED=true  (default: false — safe off switch)

State persisted in twitter_state.json.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

import portfolio as pf
from config import INITIAL_CAPITAL_EUR
from profiles import PROFILES

load_dotenv()

API_KEY       = os.getenv("X_CONSUMER_KEY", "")
API_SECRET    = os.getenv("X_CONSUMER_KEY_SECREY", "")  # typo in .env preserved
ACCESS_TOKEN  = os.getenv("X_ACCESS_TOKEN", "")
ACCESS_SECRET = os.getenv("X_SECRET_ACCESS_TOKEN", "")
ENABLED       = os.getenv("TWITTER_ENABLED", "true").lower() != "false"

_TWEET_URL   = "https://api.twitter.com/2/tweets"
_STATE_FILE  = os.path.join(os.path.dirname(__file__), "twitter_state.json")

STRATEGY_PAIRS = [
    ("moderate",   "moderate_openai"),
    ("aggressive", "aggressive_openai"),
    ("degen",      "degen_openai"),
]
STRATEGY_LABELS = {"moderate": "Conservative", "aggressive": "Aggressive", "degen": "Degen"}
PROFILE_NAMES   = {
    "moderate": "Moderate (Grok)", "aggressive": "Aggressive (Grok)", "degen": "Degen (Grok)",
    "moderate_openai": "Moderate (GPT)", "aggressive_openai": "Aggressive (GPT)", "degen_openai": "Degen (GPT)",
}


# ── OAuth 1.0a ────────────────────────────────────────────────────────────────

def _oauth_header(method: str, url: str, body_params: dict | None = None) -> str:
    oauth = {
        "oauth_consumer_key":     API_KEY,
        "oauth_nonce":            secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            ACCESS_TOKEN,
        "oauth_version":          "1.0",
    }
    all_params = {**oauth, **(body_params or {})}
    enc = lambda s: urllib.parse.quote(str(s), safe="")
    param_str = "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(all_params.items()))
    base = "&".join([method.upper(), enc(url), enc(param_str)])
    key  = f"{enc(API_SECRET)}&{enc(ACCESS_SECRET)}"
    sig  = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(oauth.items()))


# ── Twitter API ───────────────────────────────────────────────────────────────

def _post(text: str, reply_to: str | None = None) -> str | None:
    """Post tweet. Returns tweet id or None on failure."""
    if not ENABLED:
        print(f"[twitter] DISABLED — would post: {text[:80]}…")
        return "dry_run"
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
        print("[twitter] Missing credentials — set TWITTER_* env vars")
        return None

    payload: dict = {"text": text}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}

    headers = {
        "Authorization": _oauth_header("POST", _TWEET_URL),
        "Content-Type":  "application/json",
    }
    try:
        r = requests.post(_TWEET_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 201:
            tid = r.json()["data"]["id"]
            print(f"[twitter] Posted tweet {tid}: {text[:60]}…")
            return tid
        print(f"[twitter] Error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"[twitter] Request error: {e}")
        return None


def post_thread(tweets: list[str]) -> list[str]:
    """Post list of strings as a thread. Returns list of tweet ids."""
    ids = []
    prev = None
    for text in tweets:
        tid = _post(text, reply_to=prev)
        if tid:
            ids.append(tid)
            prev = tid
        else:
            break
    return ids


# ── State ─────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_daily_ts": None, "last_cycle_ts": {}}


def _save_state(state: dict) -> None:
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _hours_since(ts_str: str | None) -> float:
    if not ts_str:
        return 9999.0
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except Exception:
        return 9999.0


# ── Price fetch ───────────────────────────────────────────────────────────────

def _fetch_prices(coin_ids: list[str]) -> dict[str, float]:
    if not coin_ids:
        return {}
    ids_str = urllib.parse.quote(",".join(coin_ids))
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=eur"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-investor-twitter/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return {k: v.get("eur", 0) for k, v in data.items()}
    except Exception as e:
        print(f"[twitter] Price fetch failed: {e}")
        return {}


def _portfolio_value(profile_key: str, prices: dict) -> tuple[float, float]:
    """Returns (total_eur, pnl_eur)."""
    port  = pf.load(PROFILES[profile_key]["portfolio_file"])
    cash  = port.get("cash_eur", 0)
    inv   = sum(pos["amount"] * prices.get(cid, 0) for cid, pos in port.get("holdings", {}).items())
    total = cash + inv
    return total, total - INITIAL_CAPITAL_EUR


# ── Tweet builders ────────────────────────────────────────────────────────────

def _pnl_str(eur: float) -> str:
    sign = "+" if eur >= 0 else ""
    pct  = eur / INITIAL_CAPITAL_EUR * 100
    return f"{sign}€{abs(eur):.2f} ({sign}{pct:.1f}%)"


def build_daily_thread(prices: dict) -> list[str]:
    """Build 2-tweet daily scoreboard thread."""
    grok_pnl = 0.0
    gpt_pnl  = 0.0
    rows = []

    for gk, ok in STRATEGY_PAIRS:
        _, gpnl = _portfolio_value(gk, prices)
        _, opnl = _portfolio_value(ok, prices)
        grok_pnl += gpnl
        gpt_pnl  += opnl
        g_str = f"{'+' if gpnl >= 0 else ''}{gpnl / INITIAL_CAPITAL_EUR * 100:.1f}%"
        o_str = f"{'+' if opnl >= 0 else ''}{opnl / INITIAL_CAPITAL_EUR * 100:.1f}%"
        label = STRATEGY_LABELS[gk]
        rows.append(f"{label:<12} Grok {g_str:>7} | GPT {o_str:>7}")

    leader = "🤖 GROK" if grok_pnl > gpt_pnl else ("⚡ GPT" if gpt_pnl > grok_pnl else "TIE")
    diff   = abs(grok_pnl - gpt_pnl)

    tweet1 = (
        f"📊 Daily AI Crypto Arena Update\n\n"
        f"6 AI agents compete in paper trading (€1k each):\n"
        f"🤖 Grok team:    {_pnl_str(grok_pnl)}\n"
        f"⚡ GPT-4o mini: {_pnl_str(gpt_pnl)}\n\n"
        f"🏆 Leading: {leader} (€{diff:.2f} ahead)\n\n"
        f"cryptoaiarena.com\n#crypto #AITrading #papertrading"
    )

    tweet2 = (
        f"📈 By strategy:\n\n"
        + "\n".join(rows)
        + f"\n\n→ Live dashboard: cryptoaiarena.com"
    )

    return [tweet1, tweet2]


def build_cycle_tweet(
    profile_key: str,
    activity_log: list[dict],
    total_eur: float,
    pnl_pct: float,
    summary: str = "",
) -> str | None:
    """Build tweet for a notable cycle. Returns None if not tweet-worthy."""
    trades = [e for e in activity_log if e.get("tool") in ("buy", "sell")]
    if not trades:
        return None

    name  = PROFILE_NAMES.get(profile_key, profile_key)
    sign  = "+" if pnl_pct >= 0 else ""
    lines = [f"⚡ {name} — cycle update\n"]

    for t in trades[:3]:
        action = t["tool"].upper()
        coin   = t.get("coin_id", "?").upper()
        eur    = t.get("amount_eur", 0)
        icon   = "🟢" if action == "BUY" else "🔴"
        if eur < 0:
            lines.append(f"{icon} {action} ALL {coin}")
        else:
            lines.append(f"{icon} {action} {coin} €{eur:.0f}")

    if len(trades) > 3:
        lines.append(f"…+{len(trades) - 3} more trades")

    lines.append(f"\nPortfolio: €{total_eur:.2f} ({sign}{pnl_pct:.1f}%)")

    if summary:
        trunc = summary[:100] + "…" if len(summary) > 100 else summary
        lines.append(f'\n“{trunc}”')

    lines.append("\ncryptoaiarena.com #crypto")
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def post_daily(prices: dict | None = None) -> bool:
    """Post daily scoreboard thread. Skips if already posted in last 20h.
    Returns True if posted (or dry-run)."""
    state = _load_state()
    if _hours_since(state.get("last_daily_ts")) < 20:
        print("[twitter] Daily tweet already sent recently, skipping.")
        return False

    if prices is None:
        all_coins: set[str] = set()
        for p in PROFILES.values():
            port = pf.load(p["portfolio_file"])
            all_coins.update(port.get("holdings", {}).keys())
        prices = _fetch_prices(list(all_coins))

    thread = build_daily_thread(prices)
    ids = post_thread(thread)
    if ids:
        state["last_daily_ts"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    return False


def maybe_post_cycle(
    profile_key: str,
    activity_log: list[dict],
    total_eur: float,
    pnl_pct: float,
    summary: str = "",
    cooldown_hours: float = 4.0,
) -> bool:
    """Post a cycle tweet if notable and cooldown elapsed.
    Returns True if posted (or dry-run)."""
    state = _load_state()
    last = state.get("last_cycle_ts", {}).get(profile_key)
    if _hours_since(last) < cooldown_hours:
        return False

    text = build_cycle_tweet(profile_key, activity_log, total_eur, pnl_pct, summary)
    if not text:
        return False

    tid = _post(text)
    if tid:
        state.setdefault("last_cycle_ts", {})[profile_key] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    return False


_LAUNCH_TWEET = """\
🚀 Launching CryptoAiArena

6 AI agents compete in live paper crypto trading:
🤖 Team Grok (xAI) vs ⚡ Team GPT-4o mini (OpenAI)

3 strategies each: Conservative · Aggressive · Degen
€1,000 each. Updated every hour. May the best AI win.

👉 cryptoaiarena.com
#crypto #AI #AITrading #papertrading\
"""


def post_launch() -> bool:
    """Post one-time launch tweet. Skips if already posted."""
    state = _load_state()
    if state.get("launch_posted"):
        print("[twitter] Launch tweet already posted, skipping.")
        return False
    tid = _post(_LAUNCH_TWEET)
    if tid:
        state["launch_posted"] = True
        _save_state(state)
        return True
    return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd == "daily":
        post_daily()
    elif cmd == "launch":
        post_launch()
    elif cmd == "test":
        prices: dict[str, float] = {}
        thread = build_daily_thread(prices)
        print(f"\n── Launch tweet ({len(_LAUNCH_TWEET)} chars) ──")
        print(_LAUNCH_TWEET)
        for i, t in enumerate(thread, 1):
            print(f"\n── Daily tweet {i} ({len(t)} chars) ──")
            print(t)
    else:
        print("Usage: python twitter_bot.py [launch|daily|test]")
