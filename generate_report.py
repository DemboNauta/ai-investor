"""Genera web/index.html con portfolios, precios live, chart histórico y memorias."""
import os
import re
import json
import shutil
import html as html_module
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from profiles import PROFILES
import memory as mem

WEB_DIR = os.getenv("WEB_DIR", os.path.join(os.path.dirname(__file__), "web"))
INITIAL_CAPITAL_EUR = 1000.0
os.makedirs(WEB_DIR, exist_ok=True)

CRON_MINUTE = {
    "moderate": 0, "aggressive": 5, "degen": 10,
    "moderate_openai": 15, "aggressive_openai": 20, "degen_openai": 25,
}
ACCENT = {
    "moderate": "#00d4ff", "aggressive": "#ffb800", "degen": "#ff3366",
    "moderate_openai": "#00d4ff", "aggressive_openai": "#ffb800", "degen_openai": "#ff3366",
}
RISK_LABEL = {
    "moderate": "BAJO RIESGO", "aggressive": "ALTO RIESGO", "degen": "EXTREMO",
    "moderate_openai": "BAJO RIESGO", "aggressive_openai": "ALTO RIESGO", "degen_openai": "EXTREMO",
}
PROVIDER_LABEL = {
    "xai": "Grok 4.1 fast reasoning", "openai": "GPT-4o mini",
}
PROVIDER_COLOR = {
    "xai": "#00d4ff", "openai": "#10b981",
}
# Base key → (grok_key, openai_key)
STRATEGY_PAIRS = [
    ("moderate", "moderate_openai"),
    ("aggressive", "aggressive_openai"),
    ("degen", "degen_openai"),
]
CATEGORY_COLOR = {
    "insight": "#00d4ff", "error": "#ff4466", "strategy": "#a78bfa",
    "market_pattern": "#ffb800", "lesson": "#00ff87", "summary": "#555570",
}
CATEGORY_ES = {
    "insight": "observación", "error": "error", "strategy": "estrategia",
    "market_pattern": "patrón", "lesson": "lección", "summary": "resumen",
}
REGIME_COLOR = {"bull": "#00ff87", "bear": "#ff4466", "neutral": "#ffb800"}
REGIME_ES = {"bull": "alcista", "bear": "bajista", "neutral": "lateral"}

DATA_SOURCES = [
    {"icon": "📊", "name": "CoinGecko", "desc": "Precios, capitalización, RSI, trending, datos globales", "url": "coingecko.com"},
    {"icon": "😱", "name": "Alternative.me", "desc": "Fear & Greed Index (sentimiento del mercado)", "url": "alternative.me/crypto/fear-and-greed-index"},
    {"icon": "🏦", "name": "Binance Futures", "desc": "Funding rates — posicionamiento del mercado de futuros", "url": "binance.com/futures"},
    {"icon": "📈", "name": "Yahoo Finance", "desc": "DXY (dólar) y S&P 500 — contexto macro", "url": "finance.yahoo.com"},
    {"icon": "📰", "name": "Coindesk + Cointelegraph", "desc": "Noticias crypto vía RSS (sin API key)", "url": "coindesk.com"},
    {"icon": "🤖", "name": "xAI Grok", "desc": "Equipo Grok: 3 agentes (Moderate / Aggressive / Degen)", "url": "x.ai"},
    {"icon": "⚡", "name": "OpenAI GPT-4o mini", "desc": "Equipo GPT: 3 agentes con mismas estrategias que Grok", "url": "openai.com"},
]


# ── Data helpers ──────────────────────────────────────────────────────────────

def _fetch_prices(coin_ids: list) -> dict:
    if not coin_ids:
        return {}
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
        print(f"[warn] precios no disponibles: {e}")
        return {}


def _load_portfolio(filename: str) -> dict:
    if os.path.exists(filename):
        with open(filename) as f:
            return json.load(f)
    return {"cash_eur": INITIAL_CAPITAL_EUR, "holdings": {}, "trades": [], "cycle_count": 0, "last_run": None}


def _load_history(profile_key: str) -> list:
    path = f"history_{profile_key}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


# ── HTML fragment builders ────────────────────────────────────────────────────

def _pc(val: float) -> str:
    return "pos" if val >= 0 else "neg"

def _eur(val: float) -> str:
    return f"€{val:,.2f}"

def _pct(val: float) -> str:
    return f"{'+' if val >= 0 else ''}{val:.2f}%"


def _holdings_rows(holdings: dict, prices: dict) -> str:
    if not holdings:
        return '<tr><td colspan="5" class="no-data-cell">— sin posiciones —</td></tr>'
    rows = []
    for coin_id, pos in holdings.items():
        price = prices.get(coin_id, 0)
        value = pos["amount"] * price
        avg   = pos["avg_buy_price_eur"]
        pp    = ((price - avg) / avg * 100) if avg > 0 else 0
        rows.append(f"""<tr>
          <td class="coin-name">{html_module.escape(coin_id)}</td>
          <td>{pos['amount']:.5f}</td>
          <td>{_eur(price)}</td>
          <td>{_eur(value)}</td>
          <td class="{_pc(pp)}">{_pct(pp)}</td>
        </tr>""")
    return "".join(rows)


def _trade_items(trades: list, last_run: str = "") -> str:
    if not trades:
        return '<div class="no-data">sin trades aún</div>'

    # Split into last-cycle vs previous using last_run timestamp
    last_cycle, previous = [], []
    try:
        cutoff = datetime.fromisoformat(last_run) if last_run else None
    except Exception:
        cutoff = None

    for t in trades[-15:]:
        if cutoff:
            try:
                tdt = datetime.fromisoformat(t["ts"])
                # naive/aware mismatch guard
                if tdt.tzinfo is None:
                    tdt = tdt.replace(tzinfo=timezone.utc)
                delta = (cutoff - tdt).total_seconds()
                (last_cycle if 0 <= delta < 3900 else previous).append(t)
            except Exception:
                previous.append(t)
        else:
            previous.append(t)

    def _row(t):
        a  = t["action"]
        ts = t["ts"][:16].replace("T", " ")
        sell_price = t.get("price_eur", 0)
        avg_buy    = t.get("avg_buy_price_eur")
        if a == "sell" and avg_buy:
            pnl_pct = (sell_price - avg_buy) / avg_buy * 100 if avg_buy > 0 else 0
            pnl_cls = "pos" if pnl_pct >= 0 else "neg"
            price_html = (
                f'<span class="trade-price">'
                f'{_eur(avg_buy)} → {_eur(sell_price)}'
                f'</span>'
                f'<span class="trade-pnl {pnl_cls}">{pnl_pct:+.1f}%</span>'
            )
        else:
            price_html = f'<span class="trade-price">@ {_eur(sell_price)}</span>'
        return f"""<div class="trade-item {a}">
          <span class="trade-action {a}">{a.upper()}</span>
          <span class="trade-coin">{html_module.escape(t['coin_id'])}</span>
          <span class="trade-eur">{_eur(t['amount_eur'])}</span>
          {price_html}
          <span class="trade-ts">{ts}</span>
        </div>"""

    html = []
    if last_cycle:
        html.append('<div class="trade-group-label">Último ciclo</div>')
        html.extend(_row(t) for t in reversed(last_cycle))
    if previous:
        if last_cycle:
            html.append('<div class="trade-group-label muted">Anteriores</div>')
        html.extend(_row(t) for t in reversed(previous[-8:]))
    return "".join(html)


def _memory_thesis(thesis: str) -> str:
    if not thesis:
        return ""
    return f"""<div class="thesis-box">
      <span class="thesis-label">VISIÓN ACTUAL</span>
      <div class="thesis-text">{html_module.escape(thesis)}</div>
    </div>"""


def _memory_coin_stats(coin_stats: dict) -> str:
    if not coin_stats:
        return ""
    rows = []
    for cid, s in sorted(coin_stats.items(), key=lambda x: -x[1]["trades"])[:8]:
        bar_cls = "pos" if s["avg_pnl_pct"] > 0 else "neg"
        rows.append(f"""<tr>
          <td class="coin-name">{html_module.escape(cid)}</td>
          <td>{s['trades']}</td>
          <td>{s['win_rate']}%</td>
          <td class="{bar_cls}">{'+' if s['avg_pnl_pct'] >= 0 else ''}{s['avg_pnl_pct']:.1f}%</td>
        </tr>""")
    if not rows:
        return ""
    return f"""<div class="section-label" style="margin-top:12px">Historial por coin</div>
    <div class="table-scroll" style="margin-bottom:12px">
    <table class="holdings-table" style="margin-bottom:0">
      <thead><tr>
        <th style="text-align:left">Coin</th>
        <th>Trades</th><th>Aciertos</th><th>Media P&amp;L</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table></div>"""


def _memory_summaries(summaries: list) -> str:
    if not summaries:
        return '<div class="no-data">sin lecciones aún</div>'
    color = CATEGORY_COLOR["summary"]
    items = []
    for s in summaries:
        # Parse "[cycle#25 ★★★] content" or just plain text
        m = re.match(r'\[cycle#(\d+)[^\]]*\]\s*(.*)', s, re.DOTALL)
        cycle_str = f"ciclo #{m.group(1)}" if m else ""
        content = m.group(2).strip() if m else s.strip()
        items.append(f"""<div class="entry-item" data-cat="summary" style="border-left-color:{color}">
          <div class="entry-meta">
            <span class="entry-cat" style="background:{color}20;color:{color}">lección destilada</span>
            {f'<span class="entry-cycle">{cycle_str}</span>' if cycle_str else ''}
            <span class="entry-stars">●●●</span>
          </div>
          <div class="entry-content">{html_module.escape(content)}</div>
        </div>""")
    return f'<div class="entry-list" style="margin-bottom:10px">{"".join(items)}</div>'


def _memory_filters(key: str, entries: list) -> str:
    if not entries:
        return ""
    cats_present = sorted({e["category"] for e in entries[-12:]})
    if len(cats_present) <= 1:
        return ""
    btns = ['<button class="filter-btn active" onclick="filterEntries(\'all\',\'entries-{key}\')" data-list="entries-{key}">todas</button>'.format(key=key)]
    for cat in cats_present:
        color = CATEGORY_COLOR.get(cat, "#555570")
        cat_es = CATEGORY_ES.get(cat, cat)
        btns.append(
            f'<button class="filter-btn" onclick="filterEntries(\'{cat}\',\'entries-{key}\')" '
            f'data-list="entries-{key}" style="--fc:{color}">{html_module.escape(cat_es)}</button>'
        )
    return f'<div class="filter-row">{"".join(btns)}</div>'


def _memory_entries(entries: list) -> str:
    if not entries:
        return '<div class="no-data">sin entradas aún</div>'
    items = []
    for e in reversed(entries[-12:]):
        cat   = e["category"]
        color = CATEGORY_COLOR.get(cat, "#555570")
        cat_es = CATEGORY_ES.get(cat, cat)
        imp = e.get("importance", 2)
        stars = "●" * imp + "○" * (3 - imp)
        pnl_html = ""
        if "pnl_pct" in e:
            pnl_html = f'<span class="entry-pnl {_pc(e["pnl_pct"])}">{_pct(e["pnl_pct"])}</span>'
        regime_html = ""
        if e.get("regime"):
            rc = REGIME_COLOR.get(e["regime"], "#888")
            re_es = REGIME_ES.get(e["regime"], e["regime"])
            fg_str = f' · F&G {e["fear_greed"]}' if e.get("fear_greed") is not None else ""
            regime_html = f'<span class="entry-regime" style="color:{rc};border-color:{rc}40">{re_es}{fg_str}</span>'
        items.append(f"""<div class="entry-item" data-cat="{html_module.escape(cat)}" style="border-left-color:{color}">
          <div class="entry-meta">
            <span class="entry-cat" style="background:{color}20;color:{color}">{html_module.escape(cat_es)}</span>
            <span class="entry-cycle">ciclo #{e['cycle']}</span>
            <span class="entry-stars">{stars}</span>
            {regime_html}
            {pnl_html}
          </div>
          <div class="entry-content">{html_module.escape(e['content'])}</div>
        </div>""")
    return "".join(items)


def _profile_card(key: str, profile: dict, prices: dict) -> str:
    accent   = ACCENT.get(key, "#888")
    risk     = RISK_LABEL.get(key, key.upper())
    provider = profile.get("provider", "xai")
    prov_lbl = PROVIDER_LABEL.get(provider, provider)
    prov_col = PROVIDER_COLOR.get(provider, "#888")
    p = _load_portfolio(profile["portfolio_file"])
    m = mem.load(key)

    cash     = p.get("cash_eur", 0)
    cycle    = p.get("cycle_count", 0)
    holdings = p.get("holdings", {})
    trades   = p.get("trades", [])

    last_run = p.get("last_run", "")
    last_run_str = "—"
    if last_run:
        try:
            last_run_str = datetime.fromisoformat(last_run).strftime("%d/%m %H:%M")
        except Exception:
            last_run_str = last_run[:16]

    invested = sum(pos["amount"] * prices.get(cid, 0) for cid, pos in holdings.items())
    total    = cash + invested
    pnl      = total - INITIAL_CAPITAL_EUR
    pnl_pct  = (pnl / INITIAL_CAPITAL_EUR) * 100
    pnl_cls  = _pc(pnl)

    summaries  = m.get("summaries", [])
    entries    = m.get("entries", [])
    thesis     = m.get("thesis", "")
    coin_stats = mem.compute_coin_stats(p.get("trades", []))

    cron_min     = CRON_MINUTE.get(key, 0)
    provider_badge = f'<span class="provider-badge" style="background:{prov_col}18;color:{prov_col};border-color:{prov_col}40">{html_module.escape(prov_lbl)}</span>'

    tab_portfolio = f"""
        <div class="stats-row">
          <div class="stat-block">
            <div class="stat-label">Valor Total</div>
            <div class="stat-value">{_eur(total)}</div>
            <div class="stat-sub">inicial {_eur(INITIAL_CAPITAL_EUR)}</div>
          </div>
          <div class="stat-block">
            <div class="stat-label">P&amp;L</div>
            <div class="stat-value {pnl_cls}">{_eur(pnl)}</div>
            <div class="stat-sub {pnl_cls}">{_pct(pnl_pct)}</div>
          </div>
          <div class="stat-block">
            <div class="stat-label">Cash</div>
            <div class="stat-value">{_eur(cash)}</div>
            <div class="stat-sub">{(cash/total*100 if total else 0):.1f}% del total</div>
          </div>
          <div class="stat-block">
            <div class="stat-label">Invertido</div>
            <div class="stat-value">{_eur(invested)}</div>
            <div class="stat-sub">{len(holdings)} posicion{'es' if len(holdings) != 1 else ''}</div>
          </div>
        </div>
        <div class="section-label">Holdings</div>
        <div class="table-scroll">
        <table class="holdings-table">
          <thead><tr>
            <th style="text-align:left">Coin</th>
            <th>Cantidad</th><th>Precio</th><th>Valor</th><th>P&amp;L%</th>
          </tr></thead>
          <tbody>{_holdings_rows(holdings, prices)}</tbody>
        </table></div>"""

    tab_trades = f"""
        <div class="trade-list" style="max-height:340px">{_trade_items(trades, last_run)}</div>"""

    tab_memoria = f"""
        {_memory_thesis(thesis)}
        {'<div class="section-label" style="font-size:8px;margin-bottom:6px">Lecciones destiladas</div>' + _memory_summaries(summaries) if summaries else ''}
        {_memory_coin_stats(coin_stats)}
        <div class="section-label" style="margin-top:{'12px' if coin_stats or summaries else '4px'}">Observaciones recientes
          <span class="mem-meta">{len(entries)} obs · {len(summaries)} lecc</span>
        </div>
        {_memory_filters(key, entries)}
        <div class="entry-list" id="entries-{key}">{_memory_entries(entries)}</div>"""

    tab_chat = f"""
        <div class="chat-box" id="chat-{key}" style="border:none;background:transparent">
          <div style="display:flex;justify-content:flex-end;margin-bottom:4px">
            <button class="chat-new" onclick="clearChat('{key}')" title="Nuevo chat">&#10005; Nuevo chat</button>
          </div>
          <div class="chat-messages" id="chat-msgs-{key}" style="min-height:80px;max-height:280px"></div>
          <div class="chat-input-row" style="border:1px solid var(--border);border-radius:3px;margin-top:8px">
            <input class="chat-input" id="chat-in-{key}" type="text"
              placeholder="Pregunta algo al agente {profile['name']}..."
              onkeydown="if(event.key==='Enter')sendChat('{key}')">
            <button class="chat-send" onclick="sendChat('{key}')">&#9658;</button>
          </div>
          <div class="chat-rl" id="chat-rl-{key}"></div>
        </div>"""

    n_trades = len(trades)
    return f"""<div class="card card-{key}" data-cron-minute="{cron_min}">
      <div class="card-header">
        <div>
          <div class="card-name" style="color:{accent}">{html_module.escape(profile['name'])} {provider_badge}</div>
          <div class="card-cycle">ciclo #{cycle} · {last_run_str} · próximo <span class="next-cycle">--:--</span></div>
        </div>
        <div class="risk-badge" style="background:{accent}18;color:{accent};border:1px solid {accent}40">{risk}</div>
      </div>
      <div class="tab-bar" style="--tab-accent:{accent}">
        <button class="tab-btn active" onclick="switchTab(this,'tp-{key}')">Portfolio</button>
        <button class="tab-btn" onclick="switchTab(this,'tt-{key}')">Trades{'<span class=tab-badge>' + str(n_trades) + '</span>' if n_trades else ''}</button>
        <button class="tab-btn" onclick="switchTab(this,'tm-{key}')">Memoria{'<span class=tab-badge>' + str(len(entries)) + '</span>' if entries else ''}</button>
        <button class="tab-btn" onclick="switchTab(this,'tc-{key}')">Chat</button>
      </div>
      <div class="card-body">
        <div class="tab-panel active" id="tp-{key}">{tab_portfolio}</div>
        <div class="tab-panel" id="tt-{key}">{tab_trades}</div>
        <div class="tab-panel" id="tm-{key}">{tab_memoria}</div>
        <div class="tab-panel" id="tc-{key}">{tab_chat}</div>
      </div>
    </div>"""


def _comparison_scoreboard(prices: dict) -> str:
    rows = []
    grok_total_pnl = 0.0
    gpt_total_pnl  = 0.0

    strategy_names = {"moderate": "Moderate", "aggressive": "Aggressive", "degen": "Degen"}

    for base, openai_key in STRATEGY_PAIRS:
        pg  = _load_portfolio(PROFILES[base]["portfolio_file"])
        po  = _load_portfolio(PROFILES[openai_key]["portfolio_file"])

        def _val(p):
            cash = p.get("cash_eur", 0)
            inv  = sum(pos["amount"] * prices.get(cid, 0) for cid, pos in p.get("holdings", {}).items())
            return cash + inv

        vg = _val(pg)
        vo = _val(po)
        pnl_g = vg - INITIAL_CAPITAL_EUR
        pnl_o = vo - INITIAL_CAPITAL_EUR
        grok_total_pnl += pnl_g
        gpt_total_pnl  += pnl_o

        pct_g = (pnl_g / INITIAL_CAPITAL_EUR) * 100
        pct_o = (pnl_o / INITIAL_CAPITAL_EUR) * 100

        cls_g = "pos" if pnl_g >= 0 else "neg"
        cls_o = "pos" if pnl_o >= 0 else "neg"

        if pg.get("cycle_count", 0) == 0 and po.get("cycle_count", 0) == 0:
            leader_html = '<span class="vs-pending">pendiente</span>'
        elif pnl_g > pnl_o:
            leader_html = '<span class="vs-winner grok-winner">GROK ↑</span>'
        elif pnl_o > pnl_g:
            leader_html = '<span class="vs-winner gpt-winner">GPT ↑</span>'
        else:
            leader_html = '<span class="vs-tie">EMPATE</span>'

        rows.append(f"""<div class="sb-row">
          <span class="sb-strategy">{strategy_names[base]}</span>
          <span class="sb-val {cls_g}">{_eur(pnl_g)} <span class="sb-pct">({_pct(pct_g)})</span></span>
          {leader_html}
          <span class="sb-val {cls_o}">{_eur(pnl_o)} <span class="sb-pct">({_pct(pct_o)})</span></span>
        </div>""")

    # Totals row
    cls_tg = "pos" if grok_total_pnl >= 0 else "neg"
    cls_to = "pos" if gpt_total_pnl >= 0 else "neg"
    pct_tg = (grok_total_pnl / (INITIAL_CAPITAL_EUR * 3)) * 100
    pct_to = (gpt_total_pnl  / (INITIAL_CAPITAL_EUR * 3)) * 100
    if grok_total_pnl > gpt_total_pnl:
        total_leader = '<span class="vs-winner grok-winner">GROK ↑</span>'
    elif gpt_total_pnl > grok_total_pnl:
        total_leader = '<span class="vs-winner gpt-winner">GPT ↑</span>'
    else:
        total_leader = '<span class="vs-tie">EMPATE</span>'

    total_row = f"""<div class="sb-row sb-total">
      <span class="sb-strategy">TOTAL</span>
      <span class="sb-val {cls_tg}">{_eur(grok_total_pnl)} <span class="sb-pct">({_pct(pct_tg)})</span></span>
      {total_leader}
      <span class="sb-val {cls_to}">{_eur(gpt_total_pnl)} <span class="sb-pct">({_pct(pct_to)})</span></span>
    </div>"""

    return f"""<div class="scoreboard-section">
  <div class="scoreboard-header">
    <div class="sb-col-label provider-grok-label">🤖 Grok</div>
    <div class="sb-col-center">vs</div>
    <div class="sb-col-label provider-gpt-label">⚡ ChatGPT</div>
  </div>
  <div class="scoreboard-rows">
    {"".join(rows)}
    {total_row}
  </div>
</div>"""


def _subscribe_section() -> str:
    return """<div class="subscribe-section">
  <div class="section-label">Alertas por email</div>
  <div class="subscribe-box">
    <p class="subscribe-desc">Resumen diario + alertas de mercado importantes.</p>
    <div class="subscribe-row">
      <input class="subscribe-input" id="sub-email" type="email" placeholder="tu@email.com"
        onkeydown="if(event.key==='Enter')subscribe()">
      <button class="subscribe-btn" onclick="subscribe()">Suscribirse</button>
    </div>
    <div class="subscribe-msg" id="sub-msg"></div>
  </div>
</div>"""


def _data_sources_panel() -> str:
    cards = []
    for s in DATA_SOURCES:
        cards.append(f"""<div class="source-card">
          <div class="source-icon">{s['icon']}</div>
          <div class="source-info">
            <div class="source-name">{html_module.escape(s['name'])}</div>
            <div class="source-desc">{html_module.escape(s['desc'])}</div>
            <div class="source-url">{html_module.escape(s['url'])}</div>
          </div>
        </div>""")
    return f"""<div class="sources-section">
  <div class="section-label">Fuentes de datos</div>
  <div class="sources-grid">{"".join(cards)}</div>
</div>"""


def _chart_script(histories: dict) -> str:
    # Build unified timeline keyed by hour — all agents in same hour align on x-axis
    hour_keys: set = set()
    for hist in histories.values():
        for pt in hist:
            ts = pt.get("ts", "")
            if ts:
                hour_keys.add(ts[:13] + ":00")  # "YYYY-MM-DDTHH:00"

    labels = sorted(hour_keys)          # sorted "YYYY-MM-DDTHH:00" strings
    timestamps = labels                  # same — used by JS for display/aggregation
    labels_json = json.dumps(labels)
    timestamps_json = json.dumps(timestamps)

    colors = {
        "moderate": "#00d4ff", "aggressive": "#ffb800", "degen": "#ff3366",
        "moderate_openai": "#00d4ff", "aggressive_openai": "#ffb800", "degen_openai": "#ff3366",
    }
    names = {
        "moderate": "Moderate (Grok)", "aggressive": "Aggressive (Grok)", "degen": "Degen (Grok)",
        "moderate_openai": "Moderate (GPT)", "aggressive_openai": "Aggressive (GPT)", "degen_openai": "Degen (GPT)",
    }
    is_openai = {"moderate_openai", "aggressive_openai", "degen_openai"}

    ordered_keys = ["moderate", "aggressive", "degen", "moderate_openai", "aggressive_openai", "degen_openai"]
    datasets = []
    for key in ordered_keys:
        hist = histories.get(key, [])
        val_map = {pt["ts"][:13] + ":00": pt["value"] for pt in hist if pt.get("ts")}
        data  = [val_map.get(ts) for ts in labels]
        col   = colors.get(key, "#888")
        dashed = key in is_openai
        d = {
            "label": names.get(key, key),
            "data": data,
            "borderColor": col,
            "backgroundColor": col + "12",
            "borderWidth": 2 if not dashed else 1.5,
            "pointRadius": 3,
            "pointHoverRadius": 5,
            "tension": 0.3,
            "fill": False,
            "spanGaps": True,
        }
        if dashed:
            d["borderDash"] = [5, 4]
            d["pointStyle"] = "triangle"
        datasets.append(d)

    datasets_json = json.dumps(datasets)

    return f"""
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function() {{
  const isDark = () => !document.body.classList.contains('light');
  const gridColor  = () => isDark() ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.07)';
  const tickColor  = () => isDark() ? '#7070a0' : '#4a4a72';
  const tooltipBg  = () => isDark() ? '#0f0f1c' : '#ffffff';
  const tooltipTxt = () => isDark() ? '#e8e8f0' : '#111128';

  const allCycles     = {labels_json};
  const allTimestamps = {timestamps_json};
  const allDatasets   = {datasets_json};

  let currentWindow = 24; // default 1D

  // Aggregate raw hourly data to one point per day (last value of day)
  function aggregateDaily(cycles, timestamps, rawDatasets, sliceN) {{
    const n     = sliceN == null ? cycles.length : sliceN;
    const cyc   = cycles.slice(-n);
    const tss   = timestamps.slice(-n);
    const raws  = rawDatasets.map(ds => ds.data.slice(-n));

    // dateMap: date string -> last index in sliced array
    const dateMap = {{}};
    tss.forEach((ts, i) => {{
      const day = ts ? ts.slice(0, 10) : String(cyc[i]);
      dateMap[day] = i;
    }});

    const indices     = Object.values(dateMap).sort((a, b) => a - b);
    const dailyLabels = indices.map(i => {{
      const ts = tss[i];
      if (!ts) return String(cyc[i]);
      const [, mm, dd] = ts.slice(0, 10).split('-');
      return dd + '/' + mm;
    }});
    const dailyDatasets = rawDatasets.map((ds, di) => ({{
      ...ds, data: indices.map(i => raws[di][i]),
    }}));
    return {{ lbs: dailyLabels, dss: dailyDatasets }};
  }}

  function buildData(n) {{
    if (n === 24) {{
      // Hourly — last 24 cycles, label as HH:mm
      const cyc  = allCycles.slice(-24);
      const tss  = allTimestamps.slice(-24);
      const lbs  = tss.map((ts, i) => ts ? ts.slice(11, 16) : String(cyc[i]));
      const dss  = allDatasets.map(ds => ({{ ...ds, data: ds.data.slice(-24) }}));
      return {{ lbs, dss, xTitle: 'Hora' }};
    }}
    const {{ lbs, dss }} = aggregateDaily(allCycles, allTimestamps, allDatasets, n);
    return {{ lbs, dss, xTitle: 'Día' }};
  }}

  const baselinePlugin = {{
    id: 'baseline',
    afterDraw(chart) {{
      const {{ctx, chartArea, scales}} = chart;
      if (!scales.y) return;
      const y = scales.y.getPixelForValue({INITIAL_CAPITAL_EUR});
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = isDark() ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(chartArea.left, y);
      ctx.lineTo(chartArea.right, y);
      ctx.stroke();
      ctx.restore();
    }}
  }};

  const initData = buildData(currentWindow);
  const cfg = {{
    type: 'line',
    data: {{ labels: initData.lbs, datasets: initData.dss }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{
          labels: {{
            color: tickColor(),
            font: {{ family: "'JetBrains Mono', monospace", size: 11 }},
            boxWidth: 12, boxHeight: 2, useBorderRadius: true, borderRadius: 1,
          }}
        }},
        tooltip: {{
          backgroundColor: tooltipBg(),
          titleColor: tooltipTxt(),
          bodyColor: tickColor(),
          borderColor: isDark() ? '#1a1a2e' : '#d0d4e8',
          borderWidth: 1,
          padding: 10,
          titleFont: {{ family: "'Syne', sans-serif", size: 12, weight: '700' }},
          bodyFont: {{ family: "'JetBrains Mono', monospace", size: 11 }},
          callbacks: {{
            label: ctx => ' ' + ctx.dataset.label + ': €' + (ctx.raw ?? '—'),
          }}
        }}
      }},
      scales: {{
        x: {{
          title: {{ display: false }},
          grid: {{ color: gridColor() }},
          ticks: {{
            color: tickColor(),
            font: {{ family: "'JetBrains Mono', monospace", size: 10 }},
            maxTicksLimit: 8,
            maxRotation: 0,
          }}
        }},
        y: {{
          title: {{ display: true, text: 'Valor (€)', color: tickColor(), font: {{ size: 10 }} }},
          grid: {{ color: gridColor() }},
          ticks: {{
            color: tickColor(),
            font: {{ family: "'JetBrains Mono', monospace", size: 10 }},
            callback: v => '€' + v.toLocaleString('es')
          }}
        }}
      }}
    }},
    plugins: [baselinePlugin],
  }};

  let chart = new Chart(document.getElementById('portfolioChart'), cfg);

  function _applyColors() {{
    cfg.options.plugins.legend.labels.color       = tickColor();
    cfg.options.plugins.tooltip.backgroundColor   = tooltipBg();
    cfg.options.plugins.tooltip.titleColor        = tooltipTxt();
    cfg.options.plugins.tooltip.bodyColor         = tickColor();
    cfg.options.plugins.tooltip.borderColor       = isDark() ? '#1a1a2e' : '#d0d4e8';
    cfg.options.scales.x.grid.color               = gridColor();
    cfg.options.scales.x.ticks.color              = tickColor();
    cfg.options.scales.y.grid.color               = gridColor();
    cfg.options.scales.y.ticks.color              = tickColor();
    cfg.options.scales.y.title.color              = tickColor();
  }}

  window._rebuildChart = function() {{
    const d = buildData(currentWindow);
    chart.destroy();
    cfg.data.labels   = d.lbs;
    cfg.data.datasets = d.dss;
    _applyColors();
    chart = new Chart(document.getElementById('portfolioChart'), cfg);
  }};

  window.filterChart = function(n) {{
    currentWindow = n;
    document.querySelectorAll('.time-btn').forEach(btn => {{
      const map = {{ 24: '1D', 168: '1W', 720: '1M', null: 'ALL' }};
      btn.classList.toggle('active', btn.textContent === (map[n] ?? 'ALL'));
    }});
    const d = buildData(n);
    chart.data.labels   = d.lbs;
    chart.data.datasets = d.dss;
    chart.update('none');
  }};
}})();

function toggleTheme() {{
  document.body.classList.toggle('light');
  const isLight = document.body.classList.contains('light');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = isLight ? '🌙' : '☀️';
  if (window._rebuildChart) window._rebuildChart();
}}

(function() {{
  if (localStorage.getItem('theme') === 'light') {{
    document.body.classList.add('light');
    const btn = document.getElementById('themeBtn');
    if (btn) btn.textContent = '🌙';
  }}
}})();
</script>"""


CSS = """
:root {
  --bg: #06060d;
  --surface: #0d0d18;
  --card: #0f0f1c;
  --border: #1e1e32;
  --text: #e8e8f0;
  --muted: #a0a0c8;
  --dim: #7070a0;
  --green: #00ff87;
  --red: #ff4466;
  --mono: 'JetBrains Mono', 'Fira Code', monospace;
  --display: 'Syne', sans-serif;
}

body.light {
  --bg: #f2f3f8;
  --surface: #e8eaf2;
  --card: #ffffff;
  --border: #d0d4e8;
  --text: #111128;
  --muted: #4a4a72;
  --dim: #6868a0;
  --green: #00a858;
  --red: #e0284a;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--mono);
  min-height: 100vh;
  padding: 20px 24px;
  background-image:
    radial-gradient(ellipse 90% 50% at 50% -10%, rgba(0,180,255,0.05) 0%, transparent 70%),
    radial-gradient(ellipse 50% 30% at 90% 100%, rgba(255,51,102,0.03) 0%, transparent 60%);
  transition: background 0.2s, color 0.2s;
}

body::before {
  content: '';
  position: fixed;
  inset: 0;
  background: repeating-linear-gradient(
    0deg, transparent, transparent 3px,
    rgba(0,0,0,0.025) 3px, rgba(0,0,0,0.025) 4px
  );
  pointer-events: none;
  z-index: 9999;
}
body.light::before { display: none; }

/* ── Header ── */
header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {}

.header-title {
  font-family: var(--display);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.3px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-title .ai { color: #00d4ff; }
.header-title .sep { color: var(--muted); font-weight: 400; }

.live-dot {
  width: 7px; height: 7px;
  background: var(--green);
  border-radius: 50%;
  display: inline-block;
  box-shadow: 0 0 8px var(--green);
  animation: blink 2.5s ease-in-out infinite;
}

@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.2;} }

.header-meta {
  font-size: 11px;
  color: var(--muted);
  margin-top: 5px;
  letter-spacing: 0.5px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.header-sub-row {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.header-subscribe {
  display: flex;
  align-items: center;
  gap: 6px;
  position: relative;
}

.sub-tooltip-wrap {
  position: relative;
}

.sub-tooltip {
  display: none;
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 14px;
  width: 240px;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.6;
  z-index: 100;
  box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}

.sub-tooltip::before {
  content: '';
  position: absolute;
  top: -5px;
  left: 50%;
  transform: translateX(-50%);
  width: 8px; height: 8px;
  background: var(--card);
  border-left: 1px solid var(--border);
  border-top: 1px solid var(--border);
  rotate: 45deg;
}

.sub-tooltip strong { color: var(--text); display: block; margin-bottom: 4px; }
.sub-tooltip ul { margin: 4px 0 0; padding-left: 16px; }
.sub-tooltip li { margin-bottom: 2px; }

.sub-tooltip-wrap:hover .sub-tooltip,
.sub-tooltip-wrap:focus-within .sub-tooltip {
  display: block;
}

.header-sub-input {
  width: 180px;
  padding: 5px 8px;
  font-size: 11px;
}

.header-subscribe .subscribe-msg {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  white-space: nowrap;
  font-size: 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 3px 8px;
  z-index: 10;
}
.header-subscribe .subscribe-msg:empty { display: none; }

.header-ts {
  text-align: right;
  font-size: 11px;
  color: var(--muted);
}

.header-ts .ts {
  font-size: 13px;
  color: var(--text);
  font-family: var(--mono);
  display: block;
  margin-bottom: 2px;
}

.theme-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: 16px;
  cursor: pointer;
  padding: 6px 10px;
  transition: background 0.2s;
  line-height: 1;
}
.theme-btn:hover { background: var(--dim); }

#infoBtn {
  font-family: var(--display);
  font-weight: 800;
  font-size: 14px;
  color: var(--muted);
  min-width: 32px;
}
#infoBtn:hover { color: var(--text); }

/* ── Chart section ── */
.chart-section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 18px 20px 14px;
  margin-bottom: 20px;
}

.chart-section .section-label { margin-bottom: 14px; }

.chart-wrap {
  position: relative;
  height: 220px;
}

.chart-empty {
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  padding: 60px 0;
  letter-spacing: 0.5px;
}

/* ── Grid ── */
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

/* ── Card ── */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  z-index: 1;
}

.card-moderate::before  { background: linear-gradient(90deg, transparent 5%, #00d4ff 50%, transparent 95%); }
.card-aggressive::before { background: linear-gradient(90deg, transparent 5%, #ffb800 50%, transparent 95%); }
.card-degen::before      { background: linear-gradient(90deg, transparent 5%, #ff3366 50%, transparent 95%); }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}

.card-name {
  font-family: var(--display);
  font-size: 15px;
  font-weight: 700;
}

.card-cycle {
  font-size: 10px;
  color: var(--muted);
  margin-top: 3px;
}

.next-cycle {
  font-family: var(--mono);
  color: var(--text);
  font-weight: 600;
}

.risk-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
  padding: 3px 8px;
  border-radius: 2px;
  text-transform: uppercase;
  white-space: nowrap;
}

.card-body { padding: 16px; }

/* ── Stats ── */
.stats-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 18px;
}

.stat-block {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 10px 12px;
}

.stat-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--muted);
  margin-bottom: 4px;
}

.stat-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  font-family: var(--mono);
  line-height: 1;
}

.stat-value.pos { color: var(--green); }
.stat-value.neg { color: var(--red); }

.stat-sub { font-size: 10px; color: var(--muted); margin-top: 3px; }
.stat-sub.pos { color: var(--green); opacity: 0.85; }
.stat-sub.neg { color: var(--red); opacity: 0.85; }

/* ── Section label ── */
.section-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: var(--muted);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}

.mem-meta { color: var(--dim); font-size: 9px; letter-spacing: 1px; }

/* ── Holdings ── */
.holdings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
  margin-bottom: 18px;
}

.holdings-table th {
  text-align: right;
  color: var(--muted);
  font-weight: 500;
  font-size: 9px;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 0 6px 8px;
  border-bottom: 1px solid var(--border);
}

.holdings-table th:first-child { text-align: left; padding-left: 0; }

.holdings-table td {
  padding: 7px 6px;
  text-align: right;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}

.holdings-table td:first-child {
  text-align: left;
  padding-left: 0;
  color: var(--text);
  font-weight: 500;
}

.coin-name { text-transform: uppercase; letter-spacing: 0.5px; }
.holdings-table tr:last-child td { border-bottom: none; }
.holdings-table td.pos { color: var(--green); }
.holdings-table td.neg { color: var(--red); }
.no-data-cell { text-align: center; color: var(--dim); padding: 12px; font-size: 11px; }

.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 18px;
}
.table-scroll .holdings-table { margin-bottom: 0; }

@media (max-width: 520px) {
  .holdings-table { font-size: 10px; }
  .holdings-table th, .holdings-table td { padding: 5px 4px; }
  .holdings-table td:nth-child(3) { display: none; }
  .holdings-table th:nth-child(3) { display: none; }
}

/* ── Trades ── */
.trade-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 18px;
  max-height: 190px;
  overflow-y: auto;
}

.trade-item {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  padding: 6px 10px;
  background: var(--surface);
  border-radius: 2px;
  border-left: 2px solid transparent;
  flex-wrap: wrap;
}

.trade-item.buy  { border-left-color: var(--green); }
.trade-item.sell { border-left-color: var(--red); }

.trade-group-label {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--text);
  padding: 4px 2px 3px;
  margin-top: 2px;
}
.trade-group-label.muted { color: var(--muted); margin-top: 6px; }

.trade-action { font-weight: 700; font-size: 9px; letter-spacing: 1px; min-width: 28px; }
.trade-action.buy  { color: var(--green); }
.trade-action.sell { color: var(--red); }

.trade-coin  { color: var(--text); flex: 1; font-size: 11px; text-transform: uppercase; min-width: 60px; }
.trade-eur   { color: var(--text); font-weight: 500; }
.trade-price { color: var(--muted); font-size: 10px; }
.trade-pnl   { font-size: 10px; font-weight: 600; margin-left: 4px; }
.trade-pnl.pos { color: var(--green); }
.trade-pnl.neg { color: var(--red); }
.trade-ts    { color: var(--muted); font-size: 10px; margin-left: auto; opacity: 0.7; }

/* ── No data ── */
.no-data {
  color: var(--dim);
  font-size: 11px;
  text-align: center;
  padding: 12px;
  background: var(--surface);
  border-radius: 3px;
  margin-bottom: 10px;
}

/* ── Memory ── */
.memory-summary {
  list-style: none;
  background: var(--surface);
  border-radius: 3px;
  padding: 10px 14px;
  margin-bottom: 10px;
}

.memory-summary li {
  padding: 4px 0 4px 12px;
  font-size: 11.5px;
  color: var(--text);
  opacity: 0.85;
  position: relative;
  line-height: 1.55;
  border-bottom: 1px solid var(--border);
}

.memory-summary li:last-child { border-bottom: none; }
.memory-summary li::before { content: '›'; position: absolute; left: 0; color: var(--dim); }

.entry-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}

.entry-item {
  background: var(--surface);
  border-radius: 2px;
  padding: 9px 12px;
  font-size: 11px;
  border-left: 2px solid var(--dim);
}

.entry-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
  flex-wrap: wrap;
}

.entry-cat {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 2px;
}

.entry-cycle { font-size: 9px; color: var(--muted); }
.entry-stars { color: #ffb800; font-size: 10px; }
.entry-pnl { font-size: 10px; margin-left: auto; }
.entry-pnl.pos { color: var(--green); }
.entry-pnl.neg { color: var(--red); }
.entry-content { color: var(--text); line-height: 1.55; opacity: 0.85; }

/* ── Tabs ── */
.tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border);
  padding: 0 16px;
  gap: 0;
  background: var(--surface);
}

.tab-btn {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  padding: 9px 12px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}

.tab-btn:hover { color: var(--text); }

.tab-btn.active {
  color: var(--text);
  border-bottom-color: var(--tab-accent, #888);
}

.tab-badge {
  font-size: 8px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0 4px;
  color: var(--dim);
  line-height: 14px;
  min-width: 14px;
  text-align: center;
}

.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* ── Responsive ── */
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 680px) {
  body { padding: 12px 14px; }
  .grid { grid-template-columns: 1fr; }
  .chart-wrap { height: 180px; }

  /* ── Header: clean vertical stack ── */
  header {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .header-title { font-size: 18px; }
  .header-meta { font-size: 10px; }
  .header-center {
    align-items: stretch;
    width: 100%;
  }
  .header-subscribe {
    width: 100%;
  }
  .header-right {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header-ts { text-align: left; }
  .header-ts .ts { font-size: 11px; }

  /* ── Scoreboard: no pct on narrow screens ── */
  .scoreboard-section { padding: 12px 14px; }
  .sb-row {
    grid-template-columns: 62px 1fr auto 1fr;
    font-size: 11px;
    padding: 6px 8px;
    gap: 6px;
  }
  .sb-pct { display: none; }
  .sb-val { font-size: 11px; }
  .sb-strategy { font-size: 9px; }
  .vs-winner, .vs-tie, .vs-pending { font-size: 8px; padding: 2px 6px; }

  .stat-value { font-size: 13px; }
  .trade-price { display: none; }
  .entry-list { max-height: 240px; }
  .trade-list { max-height: 160px; }
  .tab-btn { padding: 8px 9px; font-size: 8px; letter-spacing: 1px; }
}

/* ── Chat ── */
.chat-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
}

.chat-messages {
  min-height: 60px;
  max-height: 240px;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-msg {
  font-size: 11.5px;
  line-height: 1.5;
  max-width: 90%;
}

.chat-msg.user {
  align-self: flex-end;
  background: var(--dim);
  color: var(--text);
  padding: 6px 10px;
  border-radius: 10px 10px 2px 10px;
}

.chat-msg.agent {
  align-self: flex-start;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 10px;
  border-radius: 2px 10px 10px 10px;
}

.chat-msg.agent.loading { color: var(--muted); font-style: italic; }
.chat-msg.agent.error   { color: var(--red); }

.chat-input-row {
  display: flex;
  border-top: 1px solid var(--border);
}

.chat-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  padding: 8px 12px;
}

.chat-input::placeholder { color: var(--muted); }

.chat-send {
  background: transparent;
  border: none;
  border-left: 1px solid var(--border);
  color: var(--muted);
  font-size: 13px;
  padding: 0 12px;
  cursor: pointer;
  transition: color 0.15s;
}
.chat-send:hover { color: var(--text); }

.chat-new {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 9px;
  cursor: pointer;
  padding: 2px 4px;
  transition: color 0.15s;
}
.chat-new:hover { color: var(--text); }

.chat-rl {
  font-size: 9px;
  color: var(--red);
  padding: 0 10px 4px;
  min-height: 14px;
}

/* ── Chat markdown rendering ── */
.chat-msg p { margin: 0 0 6px; }
.chat-msg p:last-child { margin-bottom: 0; }
.chat-msg ul, .chat-msg ol { padding-left: 16px; margin: 4px 0 6px; }
.chat-msg li { margin-bottom: 2px; }
.chat-msg strong { color: var(--text); font-weight: 700; }
.chat-msg em { font-style: italic; opacity: 0.9; }
.chat-msg code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 1px 4px;
  font-size: 10px;
  font-family: var(--mono);
}
.chat-msg pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 8px 10px;
  overflow-x: auto;
  margin: 6px 0;
}
.chat-msg pre code { background: none; border: none; padding: 0; font-size: 10px; }
.chat-msg h1, .chat-msg h2, .chat-msg h3 {
  font-family: var(--display);
  font-size: 12px;
  margin: 6px 0 4px;
  color: var(--text);
}

/* ── Memory filters ── */
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 8px;
}

.filter-btn {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 2px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.filter-btn:hover {
  border-color: var(--fc, var(--muted));
  color: var(--fc, var(--text));
}

.filter-btn.active {
  background: color-mix(in srgb, var(--fc, #888) 15%, transparent);
  border-color: var(--fc, var(--muted));
  color: var(--fc, var(--text));
}

/* ── Thesis box ── */
.thesis-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid #a78bfa;
  border-radius: 3px;
  padding: 10px 14px;
  margin-bottom: 10px;
}

.thesis-label {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #a78bfa;
  text-transform: uppercase;
  display: block;
  margin-bottom: 5px;
}

.thesis-text {
  font-size: 11.5px;
  color: var(--text);
  line-height: 1.55;
  font-style: italic;
}

/* ── Entry regime badge ── */
.entry-regime {
  font-size: 8px;
  letter-spacing: 1px;
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid;
  text-transform: uppercase;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--dim); border-radius: 2px; }

/* ── Subscribe ── */
.subscribe-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}

.subscribe-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 16px 20px;
  max-width: 480px;
}

.subscribe-desc {
  font-size: 12px;
  color: var(--muted);
  margin: 0 0 12px;
}

.subscribe-row {
  display: flex;
  gap: 8px;
}

.subscribe-input {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  padding: 7px 10px;
  outline: none;
  transition: border-color 0.15s;
}
.subscribe-input:focus { border-color: #00d4ff; }
.subscribe-input::placeholder { color: var(--dim); }

.subscribe-btn {
  background: #00d4ff18;
  border: 1px solid #00d4ff40;
  border-radius: 3px;
  color: #00d4ff;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1px;
  padding: 7px 14px;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}
.subscribe-btn:hover { background: #00d4ff30; }

.subscribe-msg {
  font-size: 10px;
}
.subscribe-msg.ok  { color: var(--green); }
.subscribe-msg.err { color: var(--red); }

/* ── Data sources ── */
.sources-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}

.sources-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.source-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 10px 14px;
}

.source-icon { font-size: 18px; line-height: 1; flex-shrink: 0; padding-top: 2px; }

.source-info { min-width: 0; }

.source-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}

.source-desc {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.45;
  margin-bottom: 3px;
}

.source-url {
  font-size: 9px;
  color: var(--dim);
  letter-spacing: 0.3px;
}

/* ── Provider badge (inside card name) ── */
.provider-badge {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 2px;
  border: 1px solid;
  vertical-align: middle;
  margin-left: 6px;
  font-family: var(--mono);
}

/* ── OpenAI card top borders (same strategy color) ── */
.card-moderate_openai::before  { background: linear-gradient(90deg, transparent 5%, #00d4ff 50%, transparent 95%); opacity: 0.55; }
.card-aggressive_openai::before { background: linear-gradient(90deg, transparent 5%, #ffb800 50%, transparent 95%); opacity: 0.55; }
.card-degen_openai::before      { background: linear-gradient(90deg, transparent 5%, #ff3366 50%, transparent 95%); opacity: 0.55; }

/* ── Battle grid (2-col, 3 strategy rows) ── */
.battle-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 0;
}

/* ── Provider column headers ── */
.provider-columns-header {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 8px;
  margin-top: 20px;
}

.provider-col-label {
  font-family: var(--display);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  padding: 7px 14px;
  border-radius: 3px;
  text-align: center;
}

.grok-col {
  background: rgba(0,212,255,0.06);
  border: 1px solid rgba(0,212,255,0.2);
  color: #00d4ff;
}

.gpt-col {
  background: rgba(16,185,129,0.06);
  border: 1px solid rgba(16,185,129,0.2);
  color: #10b981;
}

/* ── Scoreboard section ── */
.scoreboard-section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 16px 20px;
  margin-bottom: 20px;
  overflow: hidden;
}

.scoreboard-header {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
  gap: 8px;
}

.sb-col-label {
  font-family: var(--display);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.provider-grok-label { color: #00d4ff; }
.provider-gpt-label  { color: #10b981; text-align: right; }

.sb-col-center {
  font-family: var(--display);
  font-size: 11px;
  font-weight: 800;
  color: var(--muted);
  letter-spacing: 3px;
  text-align: center;
}

.scoreboard-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sb-row {
  display: grid;
  grid-template-columns: 80px 1fr auto 1fr;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  background: var(--surface);
  border-radius: 2px;
  font-size: 12px;
  font-family: var(--mono);
}

.sb-total {
  border-top: 1px solid var(--border);
  margin-top: 4px;
  background: transparent;
  font-weight: 700;
}

.sb-strategy {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-total .sb-strategy { color: var(--text); }

.sb-val { font-size: 12px; }
.sb-val.pos { color: var(--green); }
.sb-val.neg { color: var(--red); }
.sb-val:last-child { text-align: right; }

.sb-pct {
  font-size: 10px;
  opacity: 0.7;
}

.vs-winner {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
  padding: 2px 8px;
  border-radius: 2px;
  text-align: center;
  white-space: nowrap;
}

.grok-winner {
  background: rgba(0,212,255,0.12);
  color: #00d4ff;
  border: 1px solid rgba(0,212,255,0.3);
}

.gpt-winner {
  background: rgba(16,185,129,0.12);
  color: #10b981;
  border: 1px solid rgba(16,185,129,0.3);
}

.vs-tie {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--muted);
  text-align: center;
}

.vs-pending {
  font-size: 9px;
  color: var(--dim);
  text-align: center;
}

/* ── Chart header with legend hint ── */
.chart-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 8px;
}

.chart-legend-hint {
  font-size: 10px;
  color: var(--muted);
  font-family: var(--mono);
  letter-spacing: 0.5px;
}

/* ── Chart time-range filter ── */
.chart-time-filters {
  display: flex;
  gap: 4px;
}

.time-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.3px;
}

.time-btn:hover { color: var(--text); border-color: var(--text); }

.time-btn.active {
  background: #00d4ff;
  border-color: #00d4ff;
  color: #06060d;
}

/* ── Responsive battle grid ── */
@media (max-width: 900px) {
  .battle-grid { grid-template-columns: 1fr; }
  .provider-columns-header { display: none; }
  .scoreboard-header { grid-template-columns: 1fr auto 1fr; }
}

/* ── Welcome modal ── */
.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(6,6,13,0.85);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  z-index: 10000;
  align-items: center;
  justify-content: center;
  padding: 20px;
  overflow-y: auto;
  animation: fadeIn 0.3s ease;
}

.modal-overlay.visible { display: flex; }

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  max-width: 560px;
  max-height: calc(100svh - 40px);
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  box-shadow: 0 24px 80px rgba(0,0,0,0.7);
  animation: slideUp 0.3s cubic-bezier(0.16,1,0.3,1);
}

@keyframes slideUp {
  from { transform: translateY(24px); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}

.modal-top-bar {
  height: 2px;
  background: linear-gradient(90deg, #00d4ff, #ffb800, #ff3366);
}

.modal-body {
  padding: 28px 32px 24px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.modal-title {
  font-family: var(--display);
  font-size: 20px;
  font-weight: 800;
  color: var(--text);
  margin-bottom: 6px;
  letter-spacing: -0.3px;
}

.modal-title .ai { color: #00d4ff; }

.modal-subtitle {
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.5px;
  margin-bottom: 22px;
  text-transform: uppercase;
}

.modal-section {
  margin-bottom: 18px;
}

.modal-section-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.8px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-section-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}

.modal-agents {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  margin-bottom: 4px;
}

.modal-agent {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 10px 12px;
}

.modal-agent-name {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 3px;
}

.modal-agent-desc {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.45;
}

.modal-providers {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.modal-provider {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.modal-provider-icon { font-size: 18px; }

.modal-provider-info { min-width: 0; }

.modal-provider-name {
  font-size: 11px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 2px;
}

.modal-provider-desc {
  font-size: 10px;
  color: var(--muted);
}

.modal-disclaimer {
  background: rgba(255,180,0,0.08);
  border: 1px solid rgba(255,180,0,0.25);
  border-radius: 3px;
  padding: 10px 14px;
  font-size: 11px;
  color: #d4a030;
  line-height: 1.5;
}

body.light .chat-msg.user {
  background: #dde0f0;
  color: #111128;
}

body.light .modal-disclaimer {
  background: rgba(180,120,0,0.07);
  border-color: rgba(180,120,0,0.25);
  color: #8a5c00;
}

.modal-footer {
  padding: 16px 32px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.modal-url {
  font-size: 10px;
  color: var(--muted);
  font-family: var(--mono);
}

.modal-close-btn {
  background: #00d4ff18;
  border: 1px solid #00d4ff40;
  border-radius: 3px;
  color: #00d4ff;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  padding: 9px 20px;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}

.modal-close-btn:hover { background: #00d4ff30; }

@media (max-width: 520px) {
  .modal-overlay { padding: 12px; }
  .modal-box { max-height: calc(100svh - 24px); }
  .modal-body { padding: 18px 16px 14px; }
  .modal-footer { padding: 12px 16px 14px; }
  .modal-agents { grid-template-columns: 1fr; }
  .modal-providers { flex-direction: column; }
  .modal-title { font-size: 17px; }
}
"""


def generate(prices: dict = None):
    all_coin_ids = set()
    for profile in PROFILES.values():
        p = _load_portfolio(profile["portfolio_file"])
        all_coin_ids.update(p.get("holdings", {}).keys())

    if prices is None:
        # Only fetch if caller didn't supply prices (avoids rate limit)
        print(f"[report] Fetching prices: {', '.join(all_coin_ids) or 'none'}")
        prices = _fetch_prices(list(all_coin_ids))
    else:
        # Filter to only coins we actually hold; fetch any missing ones
        missing = all_coin_ids - set(prices.keys())
        if missing:
            extra = _fetch_prices(list(missing))
            prices = {**prices, **extra}
        print(f"[report] Using {len(prices)} cached prices, fetched {len(missing)} extra")

    histories    = {key: _load_history(key) for key in PROFILES}
    has_history  = any(len(h) > 0 for h in histories.values())
    scoreboard   = _comparison_scoreboard(prices)

    if has_history:
        chart_section = f"""
<div class="chart-section">
  <div class="chart-section-header">
    <div class="section-label" style="margin-bottom:0">Evolución del portfolio (€ por ciclo)</div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      <div class="chart-time-filters">
        <button class="time-btn active" onclick="filterChart(24)">1D</button>
        <button class="time-btn" onclick="filterChart(168)">1W</button>
        <button class="time-btn" onclick="filterChart(720)">1M</button>
        <button class="time-btn" onclick="filterChart(null)">ALL</button>
      </div>
      <div class="chart-legend-hint">— Grok &nbsp;&nbsp; ╌ GPT-4o mini</div>
    </div>
  </div>
  <div class="chart-wrap"><canvas id="portfolioChart"></canvas></div>
</div>"""
    else:
        chart_section = """
<div class="chart-section">
  <div class="section-label">Evolución del portfolio</div>
  <div class="chart-empty">Sin datos históricos aún — el gráfico aparecerá tras el primer ciclo.</div>
</div>"""

    # Build battle grid — 2 cols: Grok | GPT, paired by strategy
    battle_cards = []
    for grok_key, openai_key in STRATEGY_PAIRS:
        grok_profile  = PROFILES[grok_key]
        openai_profile = PROFILES[openai_key]
        battle_cards.append(_profile_card(grok_key,  grok_profile,  prices))
        battle_cards.append(_profile_card(openai_key, openai_profile, prices))

    battle_grid = "\n".join(battle_cards)

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    sources_html = _data_sources_panel()

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryptoAiArena — Grok vs GPT: Batalla de IAs en Crypto Paper Trading</title>
<meta name="description" content="6 agentes de IA (Grok vs GPT-4o) compiten en paper trading de criptomonedas en tiempo real. Sigue el rendimiento de cada portafolio, decisiones de compra/venta y estadísticas en vivo.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://cryptoaiarena.com/">
<link rel="icon" type="image/png" href="/assets/img/favicon.png">
<link rel="apple-touch-icon" href="/assets/img/favicon.png">
<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:url" content="https://cryptoaiarena.com/">
<meta property="og:title" content="CryptoAiArena — Grok vs GPT: Batalla de IAs en Crypto">
<meta property="og:description" content="6 agentes de IA compiten en paper trading de criptomonedas. Grok 4.1 vs GPT-4o mini — ¿quién gana más dinero?">
<meta property="og:image" content="https://cryptoaiarena.com/assets/img/og.png">
<meta property="og:site_name" content="CryptoAiArena">
<meta property="og:locale" content="es_ES">
<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="CryptoAiArena — Grok vs GPT en Crypto Paper Trading">
<meta name="twitter:description" content="6 agentes de IA compiten en paper trading de criptomonedas en tiempo real. ¿Qué modelo gana más?">
<meta name="twitter:image" content="https://cryptoaiarena.com/assets/img/og.png">
<!-- Structured data -->
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "CryptoAiArena",
  "url": "https://cryptoaiarena.com",
  "description": "6 agentes de inteligencia artificial (Grok 4.1 vs GPT-4o mini) compiten en paper trading de criptomonedas. Portafolios en tiempo real, decisiones autónomas, comparativa de modelos.",
  "applicationCategory": "FinanceApplication",
  "operatingSystem": "Web",
  "offers": {{
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "EUR"
  }},
  "author": {{
    "@type": "Person",
    "name": "Edgar Milá"
  }}
}}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Syne:wght@600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
<style>{CSS}</style>
</head>
<body>

<!-- Welcome modal — shown once via localStorage -->
<div class="modal-overlay" id="welcomeModal">
  <div class="modal-box">
    <div class="modal-top-bar"></div>
    <div class="modal-body">
      <div class="modal-title">Crypto<span class="ai">Ai</span>Arena</div>
      <div class="modal-subtitle">Paper trading · batalla de inteligencias artificiales</div>

      <div class="modal-section">
        <div class="modal-section-title">Qué es esto</div>
        <p style="font-size:12.5px;color:var(--text);line-height:1.65;opacity:0.85">
          6 agentes de IA compiten en trading de criptomonedas con <strong>€1.000 virtuales</strong> cada uno.
          Cada hora analizan el mercado en tiempo real y deciden qué comprar o vender.
          Dos modelos de IA enfrentados: Grok 4.1 fast reasoning (xAI) vs GPT-4o mini (OpenAI).
        </p>
      </div>

      <div class="modal-section">
        <div class="modal-section-title">3 estrategias por modelo</div>
        <div class="modal-agents">
          <div class="modal-agent">
            <div class="modal-agent-name" style="color:#00d4ff">Moderate</div>
            <div class="modal-agent-desc">Top 10 coins · Max 25% por posición · Conservador</div>
          </div>
          <div class="modal-agent">
            <div class="modal-agent-name" style="color:#ffb800">Aggressive</div>
            <div class="modal-agent-desc">Top 50 coins · Momentum · Alta rotación</div>
          </div>
          <div class="modal-agent">
            <div class="modal-agent-name" style="color:#ff3366">Degen</div>
            <div class="modal-agent-desc">Todo en alts · FOMO válido · 10x o nada</div>
          </div>
        </div>
      </div>

      <div class="modal-section">
        <div class="modal-section-title">Los dos equipos</div>
        <div class="modal-providers">
          <div class="modal-provider">
            <div class="modal-provider-icon">🤖</div>
            <div class="modal-provider-info">
              <div class="modal-provider-name" style="color:#00d4ff">Grok (xAI)</div>
              <div class="modal-provider-desc">grok-4-1-fast-reasoning · ciclos 0/5/10 min</div>
            </div>
          </div>
          <div class="modal-provider">
            <div class="modal-provider-icon">⚡</div>
            <div class="modal-provider-info">
              <div class="modal-provider-name" style="color:#10b981">GPT-4o mini (OpenAI)</div>
              <div class="modal-provider-desc">Modelo gpt-4o-mini · ciclos 15/20/25 min</div>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-disclaimer">
        ⚠ <strong>Paper trading</strong> — dinero ficticio. No hay dinero real invertido.
        Esto es un experimento, no asesoramiento financiero.
      </div>
    </div>
    <div class="modal-footer">
      <span class="modal-url">cryptoaiarena.com</span>
      <button class="modal-close-btn" onclick="closeWelcome()">Entendido, ver arena →</button>
    </div>
  </div>
</div>

<header>
  <div class="header-left">
    <div class="header-title">
      <span class="live-dot"></span>
      Crypto<span class="ai">Ai</span>Arena
    </div>
    <div class="header-meta">Paper trading · 6 agentes · Grok vs GPT-4o mini</div>
  </div>

  <div class="header-center">
    <div class="header-subscribe">
      <div class="sub-tooltip-wrap">
        <input class="subscribe-input" id="sub-email" type="email" placeholder="tu@email.com"
          onkeydown="if(event.key==='Enter')subscribe()">
        <div class="sub-tooltip">
          <strong>Alertas por email</strong>
          <ul>
            <li>📊 Resumen diario a las 18:00 UTC</li>
            <li>⚡ Alertas de mercado (Fear &amp; Greed extremo, trades grandes)</li>
          </ul>
          Máx. 2-3 emails/día. Baja cuando quieras.
        </div>
      </div>
      <button class="subscribe-btn" onclick="subscribe()">Recibir alertas</button>
      <div class="subscribe-msg" id="sub-msg"></div>
    </div>
  </div>

  <div class="header-right">
    <div class="header-ts">
      <span class="ts" id="localTime">{now}</span>
      <span id="tzLabel">UTC</span> · precios live · CoinGecko
    </div>
    <button class="theme-btn" id="infoBtn" onclick="openWelcome()" title="¿Qué es esto?">?</button>
    <button class="theme-btn" id="themeBtn" onclick="toggleTheme()" title="Cambiar tema">☀️</button>
  </div>
</header>

{scoreboard}

{chart_section}

<div class="provider-columns-header">
  <div class="provider-col-label grok-col">🤖 Grok</div>
  <div class="provider-col-label gpt-col">⚡ GPT-4o mini</div>
</div>
<div class="battle-grid">
{battle_grid}
</div>

{sources_html}

{_chart_script(histories) if has_history else ''}

<script>
(function() {{
  // Welcome modal — show once
  if (!localStorage.getItem('caa_welcomed')) {{
    document.getElementById('welcomeModal').classList.add('visible');
  }}
}})();

function closeWelcome() {{
  localStorage.setItem('caa_welcomed', '1');
  const modal = document.getElementById('welcomeModal');
  modal.style.animation = 'fadeIn 0.2s ease reverse forwards';
  setTimeout(() => modal.classList.remove('visible'), 180);
}}

function openWelcome() {{
  const modal = document.getElementById('welcomeModal');
  modal.style.animation = '';
  modal.classList.add('visible');
}}

// Close on backdrop click
document.getElementById('welcomeModal').addEventListener('click', function(e) {{
  if (e.target === this) closeWelcome();
}});

(function() {{
  // Theme init — apply before first paint, then fix chart colors
  if (localStorage.getItem('theme') === 'light') {{
    document.body.classList.add('light');
    const btn = document.getElementById('themeBtn');
    if (btn) btn.textContent = '🌙';
    // Chart initialized with dark colors before this ran — rebuild with light colors
    if (window._rebuildChart) window._rebuildChart();
  }}

  // Per-agent cycle countdown (cron fires at fixed minute past each hour)
  (function() {{
    function secsUntilMinute(targetMin) {{
      const now = new Date();
      const cur = now.getMinutes() * 60 + now.getSeconds();
      const tgt = targetMin * 60;
      return tgt > cur ? tgt - cur : 3600 - cur + tgt;
    }}
    function fmt(s) {{
      const m = Math.floor(s / 60);
      return m + ':' + String(s % 60).padStart(2, '0');
    }}
    function updateAll() {{
      document.querySelectorAll('[data-cron-minute]').forEach(card => {{
        const min = parseInt(card.dataset.cronMinute, 10);
        const el = card.querySelector('.next-cycle');
        if (el) el.textContent = fmt(secsUntilMinute(min));
      }});
    }}
    updateAll();
    setInterval(updateAll, 1000);
  }})();

  // Convert UTC timestamp to local timezone
  try {{
    const utcStr = "{now}".replace(' UTC','');  // e.g. "27/04/2026 14:32"
    const [datePart, timePart] = utcStr.split(' ');
    const [d, mo, y] = datePart.split('/');
    const [h, mi] = timePart.split(':');
    const utcDate = new Date(Date.UTC(+y, +mo-1, +d, +h, +mi));
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const localStr = utcDate.toLocaleString('es-ES', {{
      timeZone: tz,
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    }});
    document.getElementById('localTime').textContent = localStr;
    // Show short tz name
    const tzShort = utcDate.toLocaleTimeString('es-ES', {{timeZone: tz, timeZoneName: 'short'}}).split(' ').pop();
    document.getElementById('tzLabel').textContent = tzShort || tz;
  }} catch(e) {{
    // fallback: keep UTC as-is
  }}
}})();

const CHAT_API = window.location.protocol + '//' + window.location.hostname;

if (typeof marked !== 'undefined') {{
  marked.use({{ mangle: false, headerIds: false, breaks: true }});
}}
function _renderMd(text) {{
  return typeof marked !== 'undefined' ? marked.parse(text) : text.replace(/\\n/g, '<br>');
}}

function _appendMsg(msgsEl, role, text) {{
  const el = document.createElement('div');
  el.className = 'chat-msg ' + role;
  el.textContent = text;
  msgsEl.appendChild(el);
  msgsEl.scrollTop = msgsEl.scrollHeight;
  return el;
}}

function clearChat(profileKey) {{
  document.getElementById('chat-msgs-' + profileKey).innerHTML = '';
}}

async function sendChat(profileKey) {{
  const input = document.getElementById('chat-in-' + profileKey);
  const msgs  = document.getElementById('chat-msgs-' + profileKey);
  const rl    = document.getElementById('chat-rl-' + profileKey);
  const text  = (input.value || '').trim();
  if (!text) return;

  input.value = '';
  rl.textContent = '';

  _appendMsg(msgs, 'user', text);
  const aBubble = _appendMsg(msgs, 'agent loading', 'pensando...');

  try {{
    const res = await fetch(CHAT_API + '/api/chat/' + profileKey, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ message: text }}),
    }});
    const data = await res.json();
    if (res.status === 429) {{
      aBubble.className = 'chat-msg agent error';
      aBubble.textContent = 'Rate limit: max 5 preguntas por minuto.';
    }} else if (res.ok) {{
      aBubble.className = 'chat-msg agent';
      aBubble.innerHTML = _renderMd(data.response || '(sin respuesta)');
    }} else {{
      aBubble.className = 'chat-msg agent error';
      aBubble.textContent = 'Error: ' + (data.error || res.status);
    }}
  }} catch(e) {{
    aBubble.className = 'chat-msg agent error';
    aBubble.textContent = 'No se pudo conectar con el servidor de chat (puerto 5001).';
  }}
  msgs.scrollTop = msgs.scrollHeight;
}}

function switchTab(btn, panelId) {{
  const card = btn.closest('.card');
  card.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  card.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  const panel = document.getElementById(panelId);
  if (panel) panel.classList.add('active');
}}

// Auto-reload when an agent finishes its cycle (cron fires + 60s grace)
(function() {{
  const CRON_MINUTES = [0, 5, 10, 15, 20, 25];
  const GRACE_MS = 60000;

  function secsUntil(targetMin) {{
    const now = new Date();
    const cur = now.getMinutes() * 60 + now.getSeconds();
    const tgt = targetMin * 60;
    return tgt > cur ? tgt - cur : 3600 - cur + tgt;
  }}

  function saveAndReload() {{
    const tabs = [];
    document.querySelectorAll('.tab-btn.active').forEach(btn => {{
      const m = (btn.getAttribute('onclick') || '').match(/'([^']+)'/);
      if (m) tabs.push(m[1]);
    }});
    sessionStorage.setItem('_tabState', JSON.stringify(tabs));
    sessionStorage.setItem('_scrollY', window.scrollY);
    location.reload();
  }}

  CRON_MINUTES.forEach(min => {{
    const delay = secsUntil(min) * 1000 + GRACE_MS;
    setTimeout(saveAndReload, delay);
  }});

  // Restore state after reload
  try {{
    const tabs = JSON.parse(sessionStorage.getItem('_tabState') || '[]');
    const scrollY = parseInt(sessionStorage.getItem('_scrollY') || '0', 10);
    sessionStorage.removeItem('_tabState');
    sessionStorage.removeItem('_scrollY');
    tabs.forEach(panelId => {{
      const btn = document.querySelector(`.tab-btn[onclick*="'${{panelId}}'"]`);
      if (btn) switchTab(btn, panelId);
    }});
    if (scrollY) window.scrollTo(0, scrollY);
  }} catch(e) {{}}
}})();

function filterEntries(cat, listId) {{
  const list = document.getElementById(listId);
  if (!list) return;
  list.querySelectorAll('.entry-item').forEach(el => {{
    el.style.display = (cat === 'all' || el.dataset.cat === cat) ? '' : 'none';
  }});
  const row = list.previousElementSibling;
  if (row && row.classList.contains('filter-row')) {{
    row.querySelectorAll('.filter-btn').forEach(btn => {{
      const onclick = btn.getAttribute('onclick') || '';
      btn.classList.toggle('active', onclick.includes("'" + cat + "'"));
    }});
  }}
}}

function toggleTheme() {{
  document.body.classList.toggle('light');
  const isLight = document.body.classList.contains('light');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = isLight ? '🌙' : '☀️';
  if (window._rebuildChart) window._rebuildChart();
}}

async function subscribe() {{
  const input = document.getElementById('sub-email');
  const msg   = document.getElementById('sub-msg');
  const email = (input.value || '').trim();
  if (!email) return;
  msg.className = 'subscribe-msg';
  msg.textContent = '...';
  try {{
    const res  = await fetch(CHAT_API + '/api/subscribe', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ email }}),
    }});
    const data = await res.json();
    msg.className = 'subscribe-msg ' + (data.ok ? 'ok' : 'err');
    msg.textContent = data.ok
      ? '✓ Revisa tu email y confirma la suscripción.'
      : (data.message || 'Error al suscribirse.');
    if (data.ok) input.value = '';
  }} catch(e) {{
    msg.className = 'subscribe-msg err';
    msg.textContent = 'No se pudo conectar.';
  }}
}}
</script>

</body>
</html>"""

    out = os.path.join(WEB_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] Generado: {out}")

    # Publicar memorias de agentes como archivos estáticos para LLM crawlers
    base_dir = os.path.dirname(__file__)
    for profile_key in PROFILES:
        mem_src = os.path.join(base_dir, f"memory_{profile_key}.md")
        if os.path.exists(mem_src):
            agent_dir = os.path.join(WEB_DIR, "agents", profile_key)
            os.makedirs(agent_dir, exist_ok=True)
            shutil.copy2(mem_src, os.path.join(agent_dir, "memory.md"))
    print("[report] Memorias de agentes publicadas en /agents/")


if __name__ == "__main__":
    generate()
