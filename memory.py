import json
import os
from datetime import datetime, timezone

INJECT_LAST_N = 15
SUMMARIZE_THRESHOLD = 50
KEEP_RECENT_AFTER_SUMMARY = 10


def _path(profile_key: str) -> str:
    return f"memory_{profile_key}.json"


def load(profile_key: str) -> dict:
    path = _path(profile_key)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"entries": [], "cycles_reflected": 0}


def save(profile_key: str, mem: dict):
    with open(_path(profile_key), "w") as f:
        json.dump(mem, f, indent=2)


def add_entry(mem: dict, content: str, category: str, cycle: int, importance: int = 2, pnl_pct: float = None):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cycle": cycle,
        "category": category,
        "importance": max(1, min(3, int(importance))),
        "content": content,
    }
    if pnl_pct is not None:
        entry["pnl_pct"] = round(pnl_pct, 2)
    mem["entries"].append(entry)


def format_for_prompt(mem: dict) -> str:
    entries = mem.get("entries", [])
    if not entries:
        return ""

    summaries = [e for e in entries if e["category"] == "summary"]
    raw = [e for e in entries if e["category"] != "summary"]

    shown = summaries[-5:] + raw[-INJECT_LAST_N:]
    if not shown:
        return ""

    lines = ["\n--- YOUR ACCUMULATED KNOWLEDGE (use this to guide decisions) ---"]
    for e in shown:
        stars = "★" * e.get("importance", 2)
        pnl_str = f" | pnl={e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
        lines.append(f"[cycle#{e['cycle']} | {e['category']} {stars}{pnl_str}] {e['content']}")
    lines.append("--- END KNOWLEDGE ---\n")
    return "\n".join(lines)


def needs_summarization(mem: dict) -> bool:
    raw = [e for e in mem.get("entries", []) if e["category"] != "summary"]
    return len(raw) >= SUMMARIZE_THRESHOLD


def prune_after_summarization(mem: dict):
    summaries = [e for e in mem["entries"] if e["category"] == "summary"]
    raw = [e for e in mem["entries"] if e["category"] != "summary"]
    mem["entries"] = summaries + raw[-KEEP_RECENT_AFTER_SUMMARY:]


def format_raw_for_summarization(mem: dict) -> str:
    raw = [e for e in mem.get("entries", []) if e["category"] != "summary"]
    lines = []
    for e in raw:
        pnl_str = f" | pnl={e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
        lines.append(f"[cycle#{e['cycle']} | {e['category']} ★{e.get('importance',2)}{pnl_str}] {e['content']}")
    return "\n".join(lines)
