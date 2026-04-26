"""Single-cycle runner — called by Windows Task Scheduler every hour."""
import sys
import traceback
from datetime import datetime, timezone

import data as market_data
import portfolio as pf
import agent
import memory as mem
import notifier
from config import INITIAL_CAPITAL_EUR
from profiles import PROFILES

PYTHON = r"C:\Users\edgar\AppData\Local\Programs\Python\Python310\python.exe"


def main(profile_key: str = "moderate"):
    profile = PROFILES.get(profile_key)
    if not profile:
        print(f"Unknown profile '{profile_key}'. Available: {list(PROFILES.keys())}")
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc).isoformat()}] [{profile['name']}] Cycle start")

    try:
        coins = market_data.get_market_data(limit=50)
        coins = market_data.enrich_with_indicators(coins)
        fear_greed = market_data.get_fear_greed()
    except Exception as e:
        print(f"Market data error: {e}")
        return

    prices = {c["id"]: c["current_price"] for c in coins}
    market_text = market_data.format_market_data_for_llm(coins, fear_greed)

    portfolio = pf.load(profile["portfolio_file"])
    portfolio["cycle_count"] += 1
    cycle = portfolio["cycle_count"]

    # Load memory and inject into system prompt
    profile_memory = mem.load(profile_key)
    memory_prompt = mem.format_for_prompt(profile_memory)
    full_system_prompt = profile["system_prompt"] + memory_prompt

    value_before = pf.get_total_value(portfolio, prices)

    print(f"Running agent (cycle #{cycle})...")
    try:
        portfolio, trade_log, summary, activity_log, in_cycle_memories = agent.run_cycle(
            portfolio, market_text, prices, system_prompt=full_system_prompt
        )
    except Exception as e:
        traceback.print_exc()
        trade_log, summary, activity_log, in_cycle_memories = [], f"Agent error: {e}", [], []

    portfolio["last_run"] = datetime.now(timezone.utc).isoformat()
    pf.save(portfolio, profile["portfolio_file"])

    value_after = pf.get_total_value(portfolio, prices)
    pnl = value_after - INITIAL_CAPITAL_EUR
    pnl_pct = (pnl / INITIAL_CAPITAL_EUR) * 100

    print(f"Total: €{value_after:.2f} | P&L: €{pnl:+.2f} ({pnl_pct:+.1f}%)")
    for t in trade_log:
        print(f"  {t}")
    if summary:
        print(f"Agent: {summary}")

    # Save in-cycle memories (logged during trading)
    for m in in_cycle_memories:
        mem.add_entry(profile_memory, m["content"], m["category"], cycle, m["importance"])
    if in_cycle_memories:
        print(f"  [{profile['name']}] {len(in_cycle_memories)} in-cycle memory/memories saved")

    # Post-cycle reflection
    print(f"  [{profile['name']}] Running post-cycle reflection...")
    try:
        reflection_memories = agent.run_reflection(
            profile_name=profile["name"],
            system_prompt=profile["system_prompt"],
            cycle=cycle,
            trade_log=trade_log,
            summary=summary,
            value_before=value_before,
            value_after=value_after,
            memory_prompt=memory_prompt,
        )
        delta_pct = ((value_after - value_before) / value_before * 100) if value_before else 0
        for m in reflection_memories:
            mem.add_entry(
                profile_memory, m["content"], m["category"], cycle,
                m["importance"], pnl_pct=delta_pct
            )
        if reflection_memories:
            print(f"  [{profile['name']}] {len(reflection_memories)} reflection memory/memories saved")
    except Exception as e:
        print(f"  [{profile['name']}] Reflection error: {e}")

    profile_memory["cycles_reflected"] = profile_memory.get("cycles_reflected", 0) + 1

    # Summarization when raw entries exceed threshold
    if mem.needs_summarization(profile_memory):
        print(f"  [{profile['name']}] Memory full — running summarization...")
        try:
            raw_text = mem.format_raw_for_summarization(profile_memory)
            summaries = agent.run_summarization(
                profile_name=profile["name"],
                system_prompt=profile["system_prompt"],
                raw_entries_text=raw_text,
            )
            mem.prune_after_summarization(profile_memory)
            for s in summaries:
                mem.add_entry(profile_memory, s["content"], "summary", cycle, 3)
            print(f"  [{profile['name']}] Summarized into {len(summaries)} entries")
        except Exception as e:
            print(f"  [{profile['name']}] Summarization error: {e}")

    mem.save(profile_key, profile_memory)

    notifier.notify_cycle(
        cycle=cycle,
        trade_log=trade_log,
        agent_summary=summary,
        activity_log=activity_log,
        total_eur=value_after,
        pnl_eur=pnl,
        pnl_pct=pnl_pct,
        cash_eur=portfolio["cash_eur"],
        profile_name=profile["name"],
    )
    print("Done.")


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "all"
    if key == "all":
        for k in PROFILES:
            main(k)
    else:
        main(key)
