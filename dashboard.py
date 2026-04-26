from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box
from config import INITIAL_CAPITAL_EUR
import portfolio as pf

console = Console()


def _pct_color(val: float | None) -> Text:
    if val is None:
        return Text("  n/a", style="dim")
    style = "green" if val >= 0 else "red"
    return Text(f"{val:+.2f}%", style=style)


def _eur(val: float) -> str:
    return f"€{val:,.2f}"


def render(portfolio: dict, coins: list[dict], trade_log: list[str], agent_summary: str, next_run: datetime) -> None:
    console.clear()
    prices = {c["id"]: c["current_price"] for c in coins}
    total = pf.get_total_value(portfolio, prices)
    invested = total - portfolio["cash_eur"]
    pnl = total - INITIAL_CAPITAL_EUR
    pnl_pct = (pnl / INITIAL_CAPITAL_EUR) * 100
    now = datetime.now(timezone.utc)
    countdown = max(0, int((next_run - now).total_seconds()))
    mins, secs = divmod(countdown, 60)

    # ── Header ──────────────────────────────────────────────────────────────
    pnl_style = "bold green" if pnl >= 0 else "bold red"
    header_text = (
        f"[bold cyan]AI Crypto Investor[/bold cyan]  "
        f"[dim]Cycle #{portfolio['cycle_count']}  |  "
        f"Next run in [bold]{mins:02d}:{secs:02d}[/bold][/dim]"
    )
    console.print(Panel(header_text, box=box.ROUNDED))

    # ── Portfolio summary ────────────────────────────────────────────────────
    summary_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary_table.add_column(style="dim")
    summary_table.add_column(justify="right")

    summary_table.add_row("Total Value", f"[bold]{_eur(total)}[/bold]")
    summary_table.add_row("Cash", _eur(portfolio["cash_eur"]))
    summary_table.add_row("Invested", _eur(invested))
    summary_table.add_row("P&L", f"[{pnl_style}]{_eur(pnl)} ({pnl_pct:+.2f}%)[/{pnl_style}]")
    summary_table.add_row("Initial", _eur(INITIAL_CAPITAL_EUR))

    # ── Holdings ─────────────────────────────────────────────────────────────
    holdings_table = Table(title="Holdings", box=box.SIMPLE_HEAVY, show_lines=False)
    holdings_table.add_column("Coin", style="cyan", min_width=14)
    holdings_table.add_column("Amount", justify="right")
    holdings_table.add_column("Price", justify="right")
    holdings_table.add_column("Value", justify="right")
    holdings_table.add_column("Avg Buy", justify="right")
    holdings_table.add_column("P&L%", justify="right")
    holdings_table.add_column("Alloc%", justify="right")

    if portfolio["holdings"]:
        for coin_id, pos in portfolio["holdings"].items():
            price = prices.get(coin_id, 0)
            value = pos["amount"] * price
            avg = pos["avg_buy_price_eur"]
            pnl_pos = ((price - avg) / avg * 100) if avg > 0 else 0
            alloc = (value / total * 100) if total > 0 else 0
            pnl_style_pos = "green" if pnl_pos >= 0 else "red"
            holdings_table.add_row(
                coin_id,
                f"{pos['amount']:.6f}",
                f"€{price:.4f}",
                f"€{value:.2f}",
                f"€{avg:.4f}",
                f"[{pnl_style_pos}]{pnl_pos:+.1f}%[/{pnl_style_pos}]",
                f"{alloc:.1f}%",
            )
    else:
        holdings_table.add_row("[dim]No positions[/dim]", "", "", "", "", "", "")

    console.print(Columns([Panel(summary_table, title="Portfolio"), Panel(holdings_table)]))

    # ── Market overview: top movers ──────────────────────────────────────────
    market_table = Table(title="Market Overview (Top 20)", box=box.SIMPLE_HEAVY)
    market_table.add_column("Coin", style="cyan", min_width=14)
    market_table.add_column("Price", justify="right")
    market_table.add_column("1h", justify="right")
    market_table.add_column("24h", justify="right")
    market_table.add_column("7d", justify="right")
    market_table.add_column("Vol 24h (M€)", justify="right")

    for c in coins[:20]:
        def get_pct(key):
            return c.get(f"price_change_percentage_{key}_in_currency")

        market_table.add_row(
            c["id"],
            f"€{c['current_price']:.4f}",
            _pct_color(get_pct("1h")),
            _pct_color(get_pct("24h")),
            _pct_color(get_pct("7d")),
            f"{(c.get('total_volume') or 0) / 1_000_000:.1f}",
        )
    console.print(market_table)

    # ── Agent activity ────────────────────────────────────────────────────────
    if trade_log or agent_summary:
        activity_lines = []
        if trade_log:
            activity_lines.append("[bold]Trades this cycle:[/bold]")
            for t in trade_log:
                activity_lines.append(f"  [green]{t}[/green]" if t.startswith("BUY") else f"  [red]{t}[/red]")
        if agent_summary:
            activity_lines.append(f"\n[bold]Agent:[/bold] {agent_summary}")
        console.print(Panel("\n".join(activity_lines), title="Last Cycle Activity", box=box.ROUNDED))

    # ── Trade history ─────────────────────────────────────────────────────────
    if portfolio["trades"]:
        hist_table = Table(title="Trade History (last 15)", box=box.SIMPLE)
        hist_table.add_column("Time (UTC)", style="dim")
        hist_table.add_column("Action")
        hist_table.add_column("Coin", style="cyan")
        hist_table.add_column("EUR", justify="right")
        hist_table.add_column("Price", justify="right")

        for t in reversed(portfolio["trades"][-15:]):
            action_style = "green" if t["action"] == "buy" else "red"
            hist_table.add_row(
                t["ts"][:16].replace("T", " "),
                f"[{action_style}]{t['action'].upper()}[/{action_style}]",
                t["coin_id"],
                f"€{t['amount_eur']:.2f}",
                f"€{t['price_eur']:.4f}",
            )
        console.print(hist_table)
