import re
import os
from datetime import datetime, timezone

INJECT_LAST_N = 15
SUMMARIZE_THRESHOLD = 50
KEEP_RECENT_AFTER_SUMMARY = 10


def _path(profile_key: str) -> str:
    return f"memory_{profile_key}.md"


def load(profile_key: str) -> dict:
    path = _path(profile_key)
    if not os.path.exists(path):
        return {"summaries": [], "entries": [], "cycles_reflected": 0}
    with open(path, encoding="utf-8") as f:
        return _parse(f.read())


def _parse(content: str) -> dict:
    mem = {"summaries": [], "entries": [], "cycles_reflected": 0}

    meta = re.search(r'<!-- cycles_reflected=(\d+) -->', content)
    if meta:
        mem["cycles_reflected"] = int(meta.group(1))

    summaries_block = re.search(r'## Core Lessons.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if summaries_block:
        for line in summaries_block.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("- "):
                mem["summaries"].append(line[2:])

    entry_re = re.compile(
        r'### \[cycle#(\d+) \| (\w+) (★+)(?:\s*\|\s*([+-]?\d+\.?\d*)%)?\]\n(.*?)(?=\n###|\n##|\Z)',
        re.DOTALL,
    )
    for m in entry_re.finditer(content):
        entry = {
            "cycle": int(m.group(1)),
            "category": m.group(2),
            "importance": len(m.group(3)),
            "content": m.group(5).strip(),
        }
        if m.group(4):
            entry["pnl_pct"] = float(m.group(4))
        mem["entries"].append(entry)

    return mem


def save(profile_key: str, mem: dict, profile_name: str = None):
    name = profile_name or profile_key.capitalize()
    lines = [
        f"# Memory — {name} Agent",
        f"<!-- cycles_reflected={mem.get('cycles_reflected', 0)} -->",
        "",
        "## Core Lessons (distilled)",
    ]

    if mem.get("summaries"):
        for s in mem["summaries"]:
            lines.append(f"- {s}")
    else:
        lines.append("_(none yet)_")

    lines.append("")
    lines.append("## Recent Entries")

    if mem.get("entries"):
        for e in mem["entries"]:
            stars = "★" * e.get("importance", 2)
            pnl_str = f" | {e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
            lines.append(f"\n### [cycle#{e['cycle']} | {e['category']} {stars}{pnl_str}]")
            lines.append(e["content"])
    else:
        lines.append("_(none yet)_")

    with open(_path(profile_key), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def add_entry(mem: dict, content: str, category: str, cycle: int, importance: int = 2, pnl_pct: float = None):
    entry = {
        "cycle": cycle,
        "category": category,
        "importance": max(1, min(3, int(importance))),
        "content": content,
    }
    if pnl_pct is not None:
        entry["pnl_pct"] = round(pnl_pct, 2)
    mem["entries"].append(entry)


def add_summary(mem: dict, content: str, cycle: int):
    mem["summaries"].append(f"[cycle#{cycle} ★★★] {content}")


def format_for_prompt(mem: dict) -> str:
    summaries = mem.get("summaries", [])
    entries = mem.get("entries", [])
    if not summaries and not entries:
        return ""

    lines = ["\n--- YOUR ACCUMULATED KNOWLEDGE ---"]

    if summaries:
        lines.append("Core lessons (always apply):")
        for s in summaries:
            lines.append(f"  • {s}")

    if entries:
        recent = entries[-INJECT_LAST_N:]
        lines.append("Recent observations:")
        for e in recent:
            stars = "★" * e.get("importance", 2)
            pnl_str = f" | pnl={e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
            lines.append(f"  [cycle#{e['cycle']} | {e['category']} {stars}{pnl_str}] {e['content']}")

    lines.append("--- END KNOWLEDGE ---\n")
    return "\n".join(lines)


def needs_summarization(mem: dict) -> bool:
    return len(mem.get("entries", [])) >= SUMMARIZE_THRESHOLD


def prune_after_summarization(mem: dict):
    mem["entries"] = mem["entries"][-KEEP_RECENT_AFTER_SUMMARY:]


def format_raw_for_summarization(mem: dict) -> str:
    lines = []
    for e in mem.get("entries", []):
        pnl_str = f" | pnl={e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
        lines.append(f"[cycle#{e['cycle']} | {e['category']} ★{e.get('importance', 2)}{pnl_str}] {e['content']}")
    return "\n".join(lines)
