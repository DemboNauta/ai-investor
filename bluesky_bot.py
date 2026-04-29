"""Bluesky bot — daily scoreboard thread + notable trade posts.

Env vars:
  BSKY_HANDLE       e.g. cryptoaiarena.bsky.social
  BSKY_APP_PASSWORD app password from bsky.app → Settings → App Passwords

State persisted in bluesky_state.json.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from atproto import Client, models
from dotenv import load_dotenv

import portfolio as pf
from config import INITIAL_CAPITAL_EUR
from profiles import PROFILES

load_dotenv()

HANDLE       = os.getenv("BSKY_HANDLE", "")
APP_PASSWORD = os.getenv("BSKY_APP_PASSWORD", "")

_STATE_FILE = os.path.join(os.path.dirname(__file__), "bluesky_state.json")

STRATEGY_PAIRS = [
    ("moderate",   "moderate_openai"),
    ("aggressive", "aggressive_openai"),
    ("degen",      "degen_openai"),
]
STRATEGY_LABELS = {"moderate": "Conservative", "aggressive": "Aggressive", "degen": "Degen"}
PROFILE_NAMES = {
    "moderate": "Moderate (Grok)", "aggressive": "Aggressive (Grok)", "degen": "Degen (Grok)",
    "moderate_openai": "Moderate (GPT)", "aggressive_openai": "Aggressive (GPT)", "degen_openai": "Degen (GPT)",
}

_LAUNCH_POST = """\
🚀 Launching CryptoAiArena

6 AI agents compete in live paper crypto trading:
🤖 Team Grok (xAI) vs ⚡ Team GPT-4o mini (OpenAI)

3 strategies: Conservative · Aggressive · Degen
€1,000 each. Updated every hour. May the best AI win.

👉 cryptoaiarena.com
#crypto #AI #AITrading\
"""


# ── Client ────────────────────────────────────────────────────────────────────

def _client() -> Client | None:
    if not HANDLE or not APP_PASSWORD:
        print("[bluesky] Missing BSKY_HANDLE or BSKY_APP_PASSWORD")
        return None
    try:
        c = Client()
        c.login(HANDLE, APP_PASSWORD)
        return c
    except Exception as e:
        print(f"[bluesky] Login error: {e}")
        return None


# ── State ─────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"launch_posted": False, "last_daily_ts": None, "last_cycle_ts": {}}


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


# ── Posting ───────────────────────────────────────────────────────────────────

def _post(client: Client, text: str, reply_ref=None) -> tuple | None:
    """Post text. Returns (uri, cid) or None."""
    try:
        if reply_ref:
            resp = client.send_post(text=text, reply_to=reply_ref)
        else:
            resp = client.send_post(text=text)
        print(f"[bluesky] Posted: {text[:60]}…")
        return resp.uri, resp.cid
    except Exception as e:
        print(f"[bluesky] Post error: {e}")
        return None


def _post_thread(client: Client, posts: list[str]) -> bool:
    """Post list of texts as a thread. Returns True if all posted."""
    root_ref = None
    parent_ref = None
    for text in posts:
        result = _post(client, text, reply_ref=parent_ref)
        if not result:
            return False
        uri, cid = result
        ref = models.create_strong_ref(uri=uri, cid=cid)
        if root_ref is None:
            root_ref = ref
        parent_ref = models.AppBskyFeedPost.ReplyRef(root=root_ref, parent=ref)
    return True


# ── Price fetch ───────────────────────────────────────────────────────────────

def _fetch_prices(coin_ids: list[str]) -> dict[str, float]:
    if not coin_ids:
        return {}
    ids_str = urllib.parse.quote(",".join(coin_ids))
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=eur"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-investor-bluesky/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return {k: v.get("eur", 0) for k, v in data.items()}
    except Exception as e:
        print(f"[bluesky] Price fetch failed: {e}")
        return {}


def _portfolio_value(profile_key: str, prices: dict) -> tuple[float, float]:
    port  = pf.load(PROFILES[profile_key]["portfolio_file"])
    cash  = port.get("cash_eur", 0)
    inv   = sum(pos["amount"] * prices.get(cid, 0) for cid, pos in port.get("holdings", {}).items())
    total = cash + inv
    return total, total - INITIAL_CAPITAL_EUR


def _pnl_str(eur: float) -> str:
    sign = "+" if eur >= 0 else ""
    pct  = eur / INITIAL_CAPITAL_EUR * 100
    return f"{sign}€{abs(eur):.2f} ({sign}{pct:.1f}%)"


# ── Post builders ─────────────────────────────────────────────────────────────

def build_daily_posts(prices: dict) -> list[str]:
    grok_pnl = gpt_pnl = 0.0
    rows = []
    for gk, ok in STRATEGY_PAIRS:
        _, gpnl = _portfolio_value(gk, prices)
        _, opnl = _portfolio_value(ok, prices)
        grok_pnl += gpnl
        gpt_pnl  += opnl
        g_str = f"{'+' if gpnl >= 0 else ''}{gpnl / INITIAL_CAPITAL_EUR * 100:.1f}%"
        o_str = f"{'+' if opnl >= 0 else ''}{opnl / INITIAL_CAPITAL_EUR * 100:.1f}%"
        rows.append(f"{STRATEGY_LABELS[gk]:<12} Grok {g_str:>7} | GPT {o_str:>7}")

    leader = "🤖 GROK" if grok_pnl > gpt_pnl else ("⚡ GPT" if gpt_pnl > grok_pnl else "TIE")
    diff   = abs(grok_pnl - gpt_pnl)

    post1 = (
        f"📊 Daily AI Crypto Arena Update\n\n"
        f"6 AI agents in paper trading (€1k each):\n"
        f"🤖 Grok:         {_pnl_str(grok_pnl)}\n"
        f"⚡ GPT-4o mini: {_pnl_str(gpt_pnl)}\n\n"
        f"🏆 Leading: {leader} (€{diff:.2f} ahead)\n\n"
        f"cryptoaiarena.com\n#crypto #AITrading #papertrading"
    )
    post2 = (
        "📈 By strategy:\n\n"
        + "\n".join(rows)
        + "\n\n→ cryptoaiarena.com"
    )
    return [post1, post2]


def build_cycle_post(
    profile_key: str,
    activity_log: list[dict],
    total_eur: float,
    pnl_pct: float,
    summary: str = "",
) -> str | None:
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
        lines.append(f"{icon} {action} ALL {coin}" if eur < 0 else f"{icon} {action} {coin} €{eur:.0f}")
    if len(trades) > 3:
        lines.append(f"…+{len(trades) - 3} more")
    lines.append(f"\nPortfolio: €{total_eur:.2f} ({sign}{pnl_pct:.1f}%)")
    if summary:
        trunc = summary[:100] + "…" if len(summary) > 100 else summary
        lines.append(f'\n"{trunc}"')
    lines.append("\ncryptoaiarena.com #crypto")
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def post_launch() -> bool:
    """One-time launch post. Skips if already posted."""
    state = _load_state()
    if state.get("launch_posted"):
        print("[bluesky] Launch post already sent, skipping.")
        return False
    c = _client()
    if not c:
        return False
    result = _post(c, _LAUNCH_POST)
    if result:
        state["launch_posted"] = True
        _save_state(state)
        return True
    return False


def post_daily(prices: dict | None = None) -> bool:
    """Daily scoreboard thread. Skips if posted in last 20h."""
    state = _load_state()
    if _hours_since(state.get("last_daily_ts")) < 20:
        print("[bluesky] Daily post already sent recently, skipping.")
        return False
    if prices is None:
        all_coins: set[str] = set()
        for p in PROFILES.values():
            port = pf.load(p["portfolio_file"])
            all_coins.update(port.get("holdings", {}).keys())
        prices = _fetch_prices(list(all_coins))
    c = _client()
    if not c:
        return False
    ok = _post_thread(c, build_daily_posts(prices))
    if ok:
        state["last_daily_ts"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
    return ok


def maybe_post_cycle(
    profile_key: str,
    activity_log: list[dict],
    total_eur: float,
    pnl_pct: float,
    summary: str = "",
    cooldown_hours: float = 4.0,
) -> bool:
    """Post cycle update if notable and cooldown elapsed."""
    state = _load_state()
    last  = state.get("last_cycle_ts", {}).get(profile_key)
    if _hours_since(last) < cooldown_hours:
        return False
    text = build_cycle_post(profile_key, activity_log, total_eur, pnl_pct, summary)
    if not text:
        return False
    c = _client()
    if not c:
        return False
    result = _post(c, text)
    if result:
        state.setdefault("last_cycle_ts", {})[profile_key] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "launch":
        post_launch()
    elif cmd == "daily":
        post_daily()
    elif cmd == "test":
        prices: dict[str, float] = {}
        print(f"\n── Launch post ({len(_LAUNCH_POST)} chars) ──")
        print(_LAUNCH_POST)
        posts = build_daily_posts(prices)
        for i, p in enumerate(posts, 1):
            print(f"\n── Daily post {i} ({len(p)} chars) ──")
            print(p)
    else:
        print("Usage: python bluesky_bot.py [launch|daily|test]")
