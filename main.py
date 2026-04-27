import time
import traceback
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from rich.console import Console

import data as market_data
import portfolio as pf
import agent
import dashboard
import notifier
from config import INITIAL_CAPITAL_EUR


def get_cycle_interval() -> float:
    load_dotenv(override=True)
    return float(os.getenv("CYCLE_INTERVAL_HOURS", "1"))

console = Console()


def run_cycle(next_run: datetime) -> datetime:
    console.print(f"\n[cyan]Fetching market data...[/cyan]")
    try:
        coins = market_data.get_market_data(limit=50)
    except Exception as e:
        console.print(f"[red]Market data error: {e}[/red]")
        return next_run

    prices = {c["id"]: c["current_price"] for c in coins}
    market_text = market_data.format_market_data_for_llm(coins)

    portfolio = pf.load()
    portfolio["cycle_count"] += 1

    console.print(f"[cyan]Running Grok agent (cycle #{portfolio['cycle_count']})...[/cyan]")
    try:
        portfolio, trade_log, summary, _activity_log, _memories = agent.run_cycle(portfolio, market_text, prices)
    except Exception as e:
        console.print(f"[red]Agent error: {e}[/red]")
        traceback.print_exc()
        trade_log, summary = [], f"Agent error: {e}"

    portfolio["last_run"] = datetime.now(timezone.utc).isoformat()
    pf.save(portfolio)

    next_run = datetime.now(timezone.utc) + timedelta(hours=get_cycle_interval())

    dashboard.render(portfolio, coins, trade_log, summary, next_run)

    # Email notification
    total = pf.get_total_value(portfolio, prices)
    pnl = total - INITIAL_CAPITAL_EUR
    pnl_pct = (pnl / INITIAL_CAPITAL_EUR) * 100
    notifier.notify_cycle(
        cycle=portfolio["cycle_count"],
        trade_log=trade_log,
        agent_summary=summary,
        total_eur=total,
        pnl_eur=pnl,
        pnl_pct=pnl_pct,
        cash_eur=portfolio["cash_eur"],
    )

    return next_run


def main():
    console.print("[bold cyan]AI Crypto Investor — Paper Trading[/bold cyan]")
    console.print(f"Starting capital: €{INITIAL_CAPITAL_EUR:.2f} | Cycle: every {get_cycle_interval()}h\n")

    next_run = datetime.now(timezone.utc)

    while True:
        now = datetime.now(timezone.utc)
        if now >= next_run:
            next_run = run_cycle(next_run)
        else:
            wait = int((next_run - now).total_seconds())
            mins, secs = divmod(wait, 60)
            # Refresh dashboard with countdown every 30s
            try:
                coins = market_data.get_market_data(limit=50)
                portfolio = pf.load()
                dashboard.render(portfolio, coins, [], "", next_run)
            except Exception:
                pass
            time.sleep(30)


if __name__ == "__main__":
    main()
