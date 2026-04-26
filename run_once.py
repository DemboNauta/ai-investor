"""Single-cycle runner — called by Windows Task Scheduler every hour."""
import sys
import traceback
from datetime import datetime, timezone

import data as market_data
import portfolio as pf
import agent
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

    print(f"Running agent (cycle #{portfolio['cycle_count']})...")
    try:
        portfolio, trade_log, summary = agent.run_cycle(
            portfolio, market_text, prices, system_prompt=profile["system_prompt"]
        )
    except Exception as e:
        traceback.print_exc()
        trade_log, summary = [], f"Agent error: {e}"

    portfolio["last_run"] = datetime.now(timezone.utc).isoformat()
    pf.save(portfolio, profile["portfolio_file"])

    total = pf.get_total_value(portfolio, prices)
    pnl = total - INITIAL_CAPITAL_EUR
    pnl_pct = (pnl / INITIAL_CAPITAL_EUR) * 100

    print(f"Total: €{total:.2f} | P&L: €{pnl:+.2f} ({pnl_pct:+.1f}%)")
    for t in trade_log:
        print(f"  {t}")
    if summary:
        print(f"Agent: {summary}")

    notifier.notify_cycle(
        cycle=portfolio["cycle_count"],
        trade_log=trade_log,
        agent_summary=summary,
        total_eur=total,
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
