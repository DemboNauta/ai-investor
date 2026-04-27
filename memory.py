import re
import os
from datetime import datetime, timezone

INJECT_TOP_N = 15
SUMMARIZE_THRESHOLD = 25
KEEP_RECENT_AFTER_SUMMARY = 10


def _path(profile_key: str) -> str:
    return f"memory_{profile_key}.md"


def load(profile_key: str) -> dict:
    path = _path(profile_key)
    if not os.path.exists(path):
        return {"summaries": [], "entries": [], "cycles_reflected": 0, "thesis": ""}
    with open(path, encoding="utf-8") as f:
        return _parse(f.read())


def _parse(content: str) -> dict:
    mem = {"summaries": [], "entries": [], "cycles_reflected": 0, "thesis": ""}

    meta = re.search(r'<!-- cycles_reflected=(\d+) -->', content)
    if meta:
        mem["cycles_reflected"] = int(meta.group(1))

    thesis_meta = re.search(r'<!-- thesis:(.*?)-->', content, re.DOTALL)
    if thesis_meta:
        mem["thesis"] = thesis_meta.group(1).strip()

    summaries_block = re.search(r'## Core Lessons.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if summaries_block:
        for line in summaries_block.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("- "):
                mem["summaries"].append(line[2:])

    entry_re = re.compile(
        r'### \[cycle#(\d+) \| (\w+) (★+)(?:\s*\|\s*([+-]?\d+\.?\d*)%)?(?:\s*\|\s*(bull|bear|neutral))?(?:\s*\|\s*fg=(\d+))?(?:\s*\|\s*btcd=([\d.]+))?\]\n(.*?)(?=\n###|\n##|\Z)',
        re.DOTALL,
    )
    for m in entry_re.finditer(content):
        entry = {
            "cycle": int(m.group(1)),
            "category": m.group(2),
            "importance": len(m.group(3)),
            "content": m.group(8).strip(),
        }
        if m.group(4):
            entry["pnl_pct"] = float(m.group(4))
        if m.group(5):
            entry["regime"] = m.group(5)
        if m.group(6):
            entry["fear_greed"] = int(m.group(6))
        if m.group(7):
            entry["btc_dominance"] = float(m.group(7))
        mem["entries"].append(entry)

    return mem


def save(profile_key: str, mem: dict, profile_name: str = None):
    name = profile_name or profile_key.capitalize()
    lines = [
        f"# Memory — {name} Agent",
        f"<!-- cycles_reflected={mem.get('cycles_reflected', 0)} -->",
    ]

    if mem.get("thesis"):
        lines.append(f"<!-- thesis: {mem['thesis']} -->")
        lines.append("")
        lines.append("## Current Market Thesis")
        lines.append(mem["thesis"])

    lines.append("")
    lines.append("## Core Lessons (distilled)")

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
            regime_str = f" | {e['regime']}" if e.get("regime") else ""
            fg_str = f" | fg={e['fear_greed']}" if e.get("fear_greed") is not None else ""
            btcd_str = f" | btcd={e['btc_dominance']}" if e.get("btc_dominance") is not None else ""
            lines.append(f"\n### [cycle#{e['cycle']} | {e['category']} {stars}{pnl_str}{regime_str}{fg_str}{btcd_str}]")
            lines.append(e["content"])
    else:
        lines.append("_(none yet)_")

    with open(_path(profile_key), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _classify_regime(fear_greed: int | None, btc_dominance: float | None, mcap_change: float | None) -> str:
    score = 0
    if fear_greed is not None:
        if fear_greed >= 60:
            score += 1
        elif fear_greed <= 40:
            score -= 1
    if mcap_change is not None:
        if mcap_change >= 1.0:
            score += 1
        elif mcap_change <= -1.0:
            score -= 1
    if score >= 1:
        return "bull"
    if score <= -1:
        return "bear"
    return "neutral"


def add_entry(
    mem: dict,
    content: str,
    category: str,
    cycle: int,
    importance: int = 2,
    pnl_pct: float = None,
    regime: str = None,
    fear_greed: int = None,
    btc_dominance: float = None,
):
    entry = {
        "cycle": cycle,
        "category": category,
        "importance": max(1, min(3, int(importance))),
        "content": content,
    }
    if pnl_pct is not None:
        entry["pnl_pct"] = round(pnl_pct, 2)
    if regime:
        entry["regime"] = regime
    if fear_greed is not None:
        entry["fear_greed"] = fear_greed
    if btc_dominance is not None:
        entry["btc_dominance"] = round(btc_dominance, 1)
    mem["entries"].append(entry)


def add_summary(mem: dict, content: str, cycle: int):
    mem["summaries"].append(f"[cycle#{cycle} ★★★] {content}")


def update_thesis(mem: dict, thesis: str):
    mem["thesis"] = thesis.strip()


def _entry_score(entry: dict, current_regime: str, current_cycle: int) -> float:
    """Score entry for injection relevance. Higher = more relevant to inject."""
    score = entry.get("importance", 2) * 2.0

    # Regime match bonus
    entry_regime = entry.get("regime")
    if entry_regime is None:
        score += 1.0  # untagged = neutral, compatible with anything
    elif entry_regime == current_regime:
        score += 3.0
    elif current_regime == "neutral" or entry_regime == "neutral":
        score += 1.5
    # opposite regime: no bonus

    # Recency bonus (max +1 for very recent, decays)
    cycle_age = current_cycle - entry.get("cycle", 0)
    if cycle_age <= 5:
        score += 1.0
    elif cycle_age <= 15:
        score += 0.5

    return score


def compute_coin_stats(trades: list[dict]) -> dict[str, dict]:
    """
    Compute per-coin trade stats from portfolio trade history.
    Returns {coin_id: {trades, wins, avg_pnl_pct, win_rate}}.
    Pairs buys→sells using FIFO cost basis.
    """
    open_lots: dict[str, list[dict]] = {}  # coin_id -> [{amount, price}]
    stats: dict[str, dict] = {}

    for t in trades:
        cid = t["coin_id"]
        if t["action"] == "buy":
            open_lots.setdefault(cid, []).append({
                "amount": t["coin_amount"],
                "price": t["price_eur"],
            })
        elif t["action"] == "sell":
            sell_price = t["price_eur"]
            sell_amount = t["coin_amount"]
            lots = open_lots.get(cid, [])

            # Compute weighted avg cost for sold amount (FIFO)
            remaining = sell_amount
            total_cost = 0.0
            total_matched = 0.0
            new_lots = []
            for lot in lots:
                if remaining <= 0:
                    new_lots.append(lot)
                    continue
                take = min(lot["amount"], remaining)
                total_cost += take * lot["price"]
                total_matched += take
                remaining -= take
                if lot["amount"] - take > 1e-10:
                    new_lots.append({"amount": lot["amount"] - take, "price": lot["price"]})
            open_lots[cid] = new_lots

            if total_matched > 1e-10:
                avg_cost = total_cost / total_matched
                pnl_pct = (sell_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
                s = stats.setdefault(cid, {"trades": 0, "wins": 0, "total_pnl_pct": 0.0})
                s["trades"] += 1
                s["total_pnl_pct"] += pnl_pct
                if pnl_pct > 0:
                    s["wins"] += 1

    for cid, s in stats.items():
        s["avg_pnl_pct"] = round(s["total_pnl_pct"] / s["trades"], 1) if s["trades"] > 0 else 0.0
        s["win_rate"] = round(s["wins"] / s["trades"] * 100) if s["trades"] > 0 else 0
        del s["total_pnl_pct"]

    return stats


def format_for_prompt(
    mem: dict,
    current_regime: dict | None = None,
    coin_stats: dict | None = None,
    current_cycle: int = 0,
) -> str:
    """
    current_regime: {"label": "bull/bear/neutral", "fear_greed": int, "btc_dominance": float}
    coin_stats: output of compute_coin_stats()
    """
    summaries = mem.get("summaries", [])
    entries = mem.get("entries", [])
    thesis = mem.get("thesis", "")

    if not summaries and not entries and not thesis and not coin_stats:
        return ""

    regime_label = (current_regime or {}).get("label", "neutral")
    lines = ["\n--- YOUR ACCUMULATED KNOWLEDGE ---"]

    # ── Working thesis ──
    if thesis:
        lines.append(f"YOUR CURRENT MARKET THESIS: {thesis}")

    # ── Core lessons ──
    if summaries:
        lines.append("Core lessons (always apply):")
        for s in summaries:
            lines.append(f"  • {s}")

    # ── Per-coin performance ──
    if coin_stats:
        completed = {cid: s for cid, s in coin_stats.items() if s["trades"] >= 1}
        if completed:
            lines.append("Your historical performance per coin (completed trades):")
            for cid, s in sorted(completed.items(), key=lambda x: -x[1]["trades"])[:15]:
                bar = "+" if s["avg_pnl_pct"] > 0 else "-"
                lines.append(
                    f"  {bar} {cid:<20} {s['trades']} trades | "
                    f"win {s['win_rate']}% | avg {s['avg_pnl_pct']:+.1f}%"
                )

    # ── Recent observations (regime-smart) ──
    if entries:
        scored = sorted(
            entries,
            key=lambda e: _entry_score(e, regime_label, current_cycle),
            reverse=True,
        )
        top = scored[:INJECT_TOP_N]
        # Sort selected by cycle for readability
        top.sort(key=lambda e: e["cycle"])

        lines.append(f"Relevant observations (prioritized for current {regime_label} regime):")
        for e in top:
            stars = "★" * e.get("importance", 2)
            pnl_str = f" | pnl={e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
            reg_str = f" | {e.get('regime', '?')}" if e.get("regime") else ""
            lines.append(
                f"  [cycle#{e['cycle']} | {e['category']} {stars}{pnl_str}{reg_str}] {e['content']}"
            )

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
        reg_str = f" | {e['regime']}" if e.get("regime") else ""
        lines.append(
            f"[cycle#{e['cycle']} | {e['category']} ★{e.get('importance', 2)}{pnl_str}{reg_str}] {e['content']}"
        )
    return "\n".join(lines)
