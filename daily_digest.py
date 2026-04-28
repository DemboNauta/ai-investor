"""Resumen diario a todos los suscriptores. Ejecutar vía cron a las 20:00 UTC."""
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

import portfolio as pf
import notifier
import subscribers as subs
from config import INITIAL_CAPITAL_EUR
from profiles import PROFILES

ACCENT = {"moderate": "#00d4ff", "aggressive": "#ffb800", "degen": "#ff3366"}
RISK   = {"moderate": "Bajo riesgo", "aggressive": "Alto riesgo", "degen": "Extremo"}


def _load_history(key: str) -> list:
    path = f"history_{key}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _fetch_prices(coin_ids: list) -> dict:
    if not coin_ids:
        return {}
    import urllib.request, urllib.parse
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={urllib.parse.quote(','.join(coin_ids))}&vs_currencies=eur"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-investor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return {k: v.get("eur", 0) for k, v in data.items()}
    except Exception as e:
        print(f"[digest] Precios no disponibles: {e}")
        return {}


def _profile_card_html(key: str, p: dict, prices: dict) -> str:
    accent = ACCENT.get(key, "#888")
    risk   = RISK.get(key, key)
    port   = pf.load(p["portfolio_file"])
    cash   = port.get("cash_eur", 0)
    cycle  = port.get("cycle_count", 0)
    holdings = port.get("holdings", {})
    trades   = port.get("trades", [])

    invested = sum(pos["amount"] * prices.get(cid, 0) for cid, pos in holdings.items())
    total    = cash + invested
    pnl      = total - INITIAL_CAPITAL_EUR
    pnl_pct  = (pnl / INITIAL_CAPITAL_EUR) * 100
    pnl_cls  = "pos" if pnl >= 0 else "neg"
    pnl_sign = "+" if pnl >= 0 else ""

    # Last trades (max 3)
    recent = trades[-3:] if trades else []
    trade_rows = ""
    for t in reversed(recent):
        action = t["action"].upper()
        badge_cls = "badge-buy" if t["action"] == "buy" else "badge-sell"
        ts = t["ts"][:16].replace("T", " ")
        trade_rows += f"""<tr>
          <td><span class="badge {badge_cls}">{action}</span></td>
          <td style="text-transform:uppercase">{t['coin_id']}</td>
          <td>€{t['amount_eur']:.2f}</td>
          <td style="color:#5a5a7e">{ts}</td>
        </tr>"""
    trades_html = (
        f"<table><thead><tr><th>Acción</th><th>Coin</th><th>€</th><th>Hora</th></tr></thead>"
        f"<tbody>{trade_rows}</tbody></table>"
    ) if trade_rows else '<p class="no-data">Sin trades recientes.</p>'

    # Holdings (max 3)
    holding_rows = ""
    for cid, pos in list(holdings.items())[:3]:
        price = prices.get(cid, 0)
        val   = pos["amount"] * price
        avg   = pos["avg_buy_price_eur"]
        pp    = ((price - avg) / avg * 100) if avg > 0 else 0
        pp_cls = "pos" if pp >= 0 else "neg"
        holding_rows += f"""<tr>
          <td style="text-transform:uppercase">{cid}</td>
          <td>€{val:.2f}</td>
          <td class="{pp_cls}">{"+" if pp >= 0 else ""}{pp:.1f}%</td>
        </tr>"""
    holdings_html = (
        f"<table><thead><tr><th>Coin</th><th>Valor</th><th>P&L%</th></tr></thead>"
        f"<tbody>{holding_rows}</tbody></table>"
    ) if holding_rows else '<p class="no-data">Sin posiciones.</p>'

    return f"""
    <div class="card" style="border-top:2px solid {accent}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px">
        <div>
          <div class="card-title" style="color:{accent}">{p['name']}</div>
          <div style="font-size:10px;color:#5a5a7e;text-transform:uppercase;letter-spacing:1px">{risk} · ciclo #{cycle}</div>
        </div>
        <div style="text-align:right">
          <div class="stat-value">€{total:,.2f}</div>
          <div class="stat-value {pnl_cls}" style="font-size:14px">{pnl_sign}€{abs(pnl):,.2f} ({pnl_sign}{pnl_pct:.1f}%)</div>
        </div>
      </div>
      <div style="margin-bottom:10px">
        <div style="font-size:9px;color:#5a5a7e;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px">Holdings</div>
        {holdings_html}
      </div>
      <div>
        <div style="font-size:9px;color:#5a5a7e;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px">Últimos trades</div>
        {trades_html}
      </div>
    </div>"""


def build_and_send() -> int:
    recipients = subs.get_all()
    if not recipients:
        print("[digest] Sin suscriptores, omitiendo.")
        return 0

    # Fetch prices
    all_coins: set[str] = set()
    for p in PROFILES.values():
        port = pf.load(p["portfolio_file"])
        all_coins.update(port.get("holdings", {}).keys())
    prices = _fetch_prices(list(all_coins))

    cards = "".join(_profile_card_html(k, p, prices) for k, p in PROFILES.items())
    now   = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    content = f"""
    <p style="color:#9090b8;font-size:13px;margin-bottom:20px">
      Resumen de los 3 portfolios. Precios live vía CoinGecko.
    </p>
    {cards}
    <a class="btn" href="https://cryptoaiarena.com">Ver dashboard completo</a>
    """

    subject = f"[CryptoAiArena] Resumen diario — {now}"
    sent = notifier.send_bulk(recipients, subject, notifier._wrap(content, "Resumen diario", now))
    print(f"[digest] Enviado a {sent}/{len(recipients)} suscriptores.")
    return sent


if __name__ == "__main__":
    build_and_send()
