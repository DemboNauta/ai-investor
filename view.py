"""Read-only dashboard — ranking + comparison of all 3 profiles."""
import sys
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich import box

import data as market_data
import portfolio as pf
import dashboard
from config import INITIAL_CAPITAL_EUR
from profiles import PROFILES

console = Console()

MEDALS = ["🥇", "🥈", "🥉"]
PROFILE_COLORS = {
    "moderate":   "cyan",
    "aggressive": "yellow",
    "degen":      "red",
}


def get_cycle_interval() -> float:
    import os
    from dotenv import load_dotenv
    load_dotenv(override=True)
    return float(os.getenv("CYCLE_INTERVAL_HOURS", "1"))


def show_comparison(coins: list[dict]) -> None:
    prices = {c["id"]: c["current_price"] for c in coins}
    portfolios = {key: pf.load(p["portfolio_file"]) for key, p in PROFILES.items()}

    # Rank by P&L%
    ranked = sorted(
        PROFILES.keys(),
        key=lambda k: pf.get_total_value(portfolios[k], prices),
        reverse=True,
    )

    # ── Winner banner ────────────────────────────────────────────────────────
    winner_key = ranked[0]
    winner_profile = PROFILES[winner_key]
    winner_port = portfolios[winner_key]
    winner_total = pf.get_total_value(winner_port, prices)
    winner_pnl = winner_total - INITIAL_CAPITAL_EUR
    winner_pct = (winner_pnl / INITIAL_CAPITAL_EUR) * 100
    sign = "+" if winner_pnl >= 0 else ""
    color = PROFILE_COLORS[winner_key]

    banner = Text(justify="center")
    banner.append("LEADING: ", style="bold white")
    banner.append(f"{winner_profile['name'].upper()}  ", style=f"bold {color}")
    banner.append(f"€{winner_total:,.2f}  ", style="bold white")
    banner.append(f"{sign}€{abs(winner_pnl):,.2f} ({sign}{winner_pct:.2f}%)", style=f"bold {'green' if winner_pnl >= 0 else 'red'}")
    console.print(Panel(banner, box=box.HEAVY, style=color))

    # ── Ranking table ────────────────────────────────────────────────────────
    rank_table = Table(box=box.ROUNDED, show_lines=True, title="Ranking")
    rank_table.add_column("#",        width=4,  justify="center")
    rank_table.add_column("Profile",  min_width=12)
    rank_table.add_column("Total",    justify="right", min_width=12)
    rank_table.add_column("P&L",      justify="right", min_width=16)
    rank_table.add_column("Cash",     justify="right", min_width=10)
    rank_table.add_column("Invested", justify="right", min_width=10)
    rank_table.add_column("Positions",justify="right")
    rank_table.add_column("Trades",   justify="right")
    rank_table.add_column("Cycles",   justify="right")
    rank_table.add_column("Last run", style="dim", min_width=16)

    for i, key in enumerate(ranked):
        profile = PROFILES[key]
        p = portfolios[key]
        total = pf.get_total_value(p, prices)
        pnl = total - INITIAL_CAPITAL_EUR
        pct = (pnl / INITIAL_CAPITAL_EUR) * 100
        sign = "+" if pnl >= 0 else ""
        pnl_color = "green" if pnl >= 0 else "red"
        col = PROFILE_COLORS[key]
        last = (p.get("last_run") or "never")[:16].replace("T", " ")

        rank_table.add_row(
            MEDALS[i] if i < 3 else str(i + 1),
            f"[bold {col}]{profile['name']}[/bold {col}]",
            f"[bold]€{total:,.2f}[/bold]",
            f"[{pnl_color}]{sign}€{abs(pnl):,.2f} ({sign}{pct:.2f}%)[/{pnl_color}]",
            f"€{p['cash_eur']:,.2f}",
            f"€{total - p['cash_eur']:,.2f}",
            str(len(p["holdings"])),
            str(len(p["trades"])),
            str(p["cycle_count"]),
            last,
        )

    console.print(rank_table)

    # ── Holdings per profile ─────────────────────────────────────────────────
    holdings_panels = []
    for key in ranked:
        profile = PROFILES[key]
        p = portfolios[key]
        col = PROFILE_COLORS[key]

        h_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        h_table.add_column("Coin",  style="cyan", min_width=14)
        h_table.add_column("Value", justify="right")
        h_table.add_column("P&L%",  justify="right")
        h_table.add_column("Alloc", justify="right")

        total = pf.get_total_value(p, prices)
        if p["holdings"]:
            for coin_id, pos in p["holdings"].items():
                price = prices.get(coin_id, 0)
                value = pos["amount"] * price
                avg = pos["avg_buy_price_eur"]
                coin_pnl = ((price - avg) / avg * 100) if avg > 0 else 0
                alloc = (value / total * 100) if total > 0 else 0
                c = "green" if coin_pnl >= 0 else "red"
                h_table.add_row(
                    coin_id,
                    f"€{value:.2f}",
                    f"[{c}]{coin_pnl:+.1f}%[/{c}]",
                    f"{alloc:.0f}%",
                )
        else:
            h_table.add_row("[dim]all cash[/dim]", "", "", "")

        holdings_panels.append(Panel(h_table, title=f"[bold {col}]{profile['name']}[/bold {col}]", box=box.ROUNDED))

    console.print(Columns(holdings_panels, equal=True))

    # ── Recent trades all profiles ───────────────────────────────────────────
    all_trades = []
    for key, profile in PROFILES.items():
        p = portfolios[key]
        for t in p["trades"][-5:]:
            all_trades.append({**t, "profile": profile["name"], "profile_key": key})
    all_trades.sort(key=lambda t: t["ts"], reverse=True)

    if all_trades:
        t_table = Table(title="Recent Trades (all profiles)", box=box.SIMPLE_HEAVY)
        t_table.add_column("Time (UTC)", style="dim")
        t_table.add_column("Profile")
        t_table.add_column("Action")
        t_table.add_column("Coin",   style="cyan")
        t_table.add_column("EUR",    justify="right")
        t_table.add_column("Price",  justify="right")

        for t in all_trades[:15]:
            action_style = "green" if t["action"] == "buy" else "red"
            col = PROFILE_COLORS[t["profile_key"]]
            t_table.add_row(
                t["ts"][:16].replace("T", " "),
                f"[{col}]{t['profile']}[/{col}]",
                f"[{action_style}]{t['action'].upper()}[/{action_style}]",
                t["coin_id"],
                f"€{t['amount_eur']:.2f}",
                f"€{t['price_eur']:.4f}",
            )
        console.print(t_table)

    console.print("\n[dim]Tip: pass profile name for full detail — moderate / aggressive / degen[/dim]")


def show_profile_detail(key: str, coins: list[dict]) -> None:
    profile = PROFILES[key]
    port = pf.load(profile["portfolio_file"])
    last = port.get("last_run")
    interval = get_cycle_interval()
    next_run = (
        datetime.fromisoformat(last) + timedelta(hours=interval)
        if last else datetime.now(timezone.utc)
    )
    dashboard.render(port, coins, [], f"Profile: {profile['name']}", next_run)


if __name__ == "__main__":
    console.print("[cyan]Fetching market data...[/cyan]")
    coins = market_data.get_market_data(limit=50)
    coins = market_data.enrich_with_indicators(coins)
    console.clear()

    if len(sys.argv) > 1 and sys.argv[1] in PROFILES:
        show_profile_detail(sys.argv[1], coins)
    else:
        show_comparison(coins)
