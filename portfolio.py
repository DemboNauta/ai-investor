import json
import os
from datetime import datetime, timezone
from config import INITIAL_CAPITAL_EUR

PORTFOLIO_FILE = "portfolio.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(filename: str = PORTFOLIO_FILE) -> dict:
    if os.path.exists(filename):
        with open(filename) as f:
            return json.load(f)
    portfolio = {
        "cash_eur": INITIAL_CAPITAL_EUR,
        "holdings": {},
        "trades": [],
        "created_at": _now(),
        "last_run": None,
        "cycle_count": 0,
    }
    save(portfolio, filename)
    return portfolio


def save(portfolio: dict, filename: str = PORTFOLIO_FILE) -> None:
    with open(filename, "w") as f:
        json.dump(portfolio, f, indent=2)


def get_total_value(portfolio: dict, prices: dict[str, float]) -> float:
    """Total portfolio value in EUR using current prices."""
    total = portfolio["cash_eur"]
    for coin_id, pos in portfolio["holdings"].items():
        price = prices.get(coin_id, 0)
        total += pos["amount"] * price
    return total


def buy(portfolio: dict, coin_id: str, amount_eur: float, price: float) -> tuple[bool, str]:
    if amount_eur <= 0:
        return False, "amount_eur must be positive"
    if portfolio["cash_eur"] < amount_eur:
        amount_eur = portfolio["cash_eur"]
        if amount_eur <= 0:
            return False, "insufficient cash"

    coin_amount = amount_eur / price

    if coin_id in portfolio["holdings"]:
        pos = portfolio["holdings"][coin_id]
        total_cost = pos["amount"] * pos["avg_buy_price_eur"] + amount_eur
        total_amount = pos["amount"] + coin_amount
        pos["avg_buy_price_eur"] = total_cost / total_amount
        pos["amount"] = total_amount
    else:
        portfolio["holdings"][coin_id] = {
            "amount": coin_amount,
            "avg_buy_price_eur": price,
        }

    portfolio["cash_eur"] -= amount_eur
    portfolio["trades"].append({
        "ts": _now(),
        "action": "buy",
        "coin_id": coin_id,
        "amount_eur": amount_eur,
        "coin_amount": coin_amount,
        "price_eur": price,
    })
    return True, f"Bought {coin_amount:.6f} {coin_id} for €{amount_eur:.2f} @ €{price:.4f}"


def sell(portfolio: dict, coin_id: str, amount_eur: float, price: float) -> tuple[bool, str]:
    if coin_id not in portfolio["holdings"]:
        return False, f"no position in {coin_id}"

    pos = portfolio["holdings"][coin_id]
    current_value = pos["amount"] * price

    # -1 means sell all
    if amount_eur < 0 or amount_eur >= current_value:
        amount_eur = current_value
        coin_amount = pos["amount"]
        del portfolio["holdings"][coin_id]
    else:
        coin_amount = amount_eur / price
        pos["amount"] -= coin_amount
        if pos["amount"] < 1e-10:
            del portfolio["holdings"][coin_id]

    portfolio["cash_eur"] += amount_eur
    portfolio["trades"].append({
        "ts": _now(),
        "action": "sell",
        "coin_id": coin_id,
        "amount_eur": amount_eur,
        "coin_amount": coin_amount,
        "price_eur": price,
    })
    return True, f"Sold {coin_amount:.6f} {coin_id} for €{amount_eur:.2f} @ €{price:.4f}"


def format_portfolio_for_llm(portfolio: dict, prices: dict[str, float]) -> str:
    total = get_total_value(portfolio, prices)
    pnl = total - INITIAL_CAPITAL_EUR
    pnl_pct = (pnl / INITIAL_CAPITAL_EUR) * 100

    lines = [
        f"PORTFOLIO STATE",
        f"  Cash:        €{portfolio['cash_eur']:.2f}",
        f"  Invested:    €{total - portfolio['cash_eur']:.2f}",
        f"  Total value: €{total:.2f}",
        f"  P&L:         €{pnl:+.2f} ({pnl_pct:+.1f}%)",
        f"  Cycle:       #{portfolio['cycle_count']}",
    ]

    if portfolio["holdings"]:
        lines.append("\nHOLDINGS:")
        lines.append(f"  {'Coin':<20} {'Amount':>14} {'Price':>12} {'Value(€)':>10} {'P&L%':>8}")
        for coin_id, pos in portfolio["holdings"].items():
            price = prices.get(coin_id, 0)
            value = pos["amount"] * price
            avg = pos["avg_buy_price_eur"]
            pnl_pos = ((price - avg) / avg * 100) if avg > 0 else 0
            lines.append(f"  {coin_id:<20} {pos['amount']:>14.6f} {price:>12.4f} {value:>10.2f} {pnl_pos:>+7.1f}%")
    else:
        lines.append("\nHOLDINGS: none (fully in cash)")

    recent = portfolio["trades"][-5:]
    if recent:
        lines.append("\nRECENT TRADES (last 5):")
        for t in reversed(recent):
            lines.append(f"  [{t['ts'][:16]}] {t['action'].upper():4} {t['coin_id']:<15} €{t['amount_eur']:.2f}")

    return "\n".join(lines)
