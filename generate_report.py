"""Genera web/index.html con portfolios, precios live, chart histórico y memorias."""
import os
import re
import json
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

CRON_MINUTE = {"moderate": 0, "aggressive": 5, "degen": 10}
ACCENT  = {"moderate": "#00d4ff", "aggressive": "#ffb800", "degen": "#ff3366"}
RISK_LABEL = {"moderate": "BAJO RIESGO", "aggressive": "ALTO RIESGO", "degen": "EXTREMO"}
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
    {"icon": "🤖", "name": "xAI Grok", "desc": "Modelo de decisión — analiza todo lo anterior y ejecuta trades", "url": "x.ai"},
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
        return f"""<div class="trade-item {a}">
          <span class="trade-action {a}">{a.upper()}</span>
          <span class="trade-coin">{html_module.escape(t['coin_id'])}</span>
          <span class="trade-eur">{_eur(t['amount_eur'])}</span>
          <span class="trade-price">@ {_eur(t['price_eur'])}</span>
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
    <table class="holdings-table" style="margin-bottom:12px">
      <thead><tr>
        <th style="text-align:left">Coin</th>
        <th>Trades</th><th>Aciertos</th><th>Media P&amp;L</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


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
    accent = ACCENT.get(key, "#888")
    risk   = RISK_LABEL.get(key, key.upper())
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

    cron_min = CRON_MINUTE.get(key, 0)

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
        <table class="holdings-table">
          <thead><tr>
            <th style="text-align:left">Coin</th>
            <th>Cantidad</th><th>Precio</th><th>Valor</th><th>P&amp;L%</th>
          </tr></thead>
          <tbody>{_holdings_rows(holdings, prices)}</tbody>
        </table>"""

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
          <div class="card-name" style="color:{accent}">{html_module.escape(profile['name'])}</div>
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
    datasets = []
    all_labels = set()
    for key, hist in histories.items():
        for pt in hist:
            all_labels.add(pt["cycle"])

    labels = sorted(all_labels)
    labels_json = json.dumps(labels)

    colors = {"moderate": "#00d4ff", "aggressive": "#ffb800", "degen": "#ff3366"}
    names  = {"moderate": "Moderate", "aggressive": "Aggressive", "degen": "Degen"}

    for key, hist in histories.items():
        val_map = {pt["cycle"]: pt["value"] for pt in hist}
        data    = [val_map.get(c) for c in labels]
        c       = colors.get(key, "#888")
        datasets.append({
            "label": names.get(key, key),
            "data": data,
            "borderColor": c,
            "backgroundColor": c + "18",
            "borderWidth": 2,
            "pointRadius": 3,
            "pointHoverRadius": 5,
            "tension": 0.3,
            "fill": False,
            "spanGaps": True,
        })

    datasets_json = json.dumps(datasets)

    return f"""
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function() {{
  const isDark = () => !document.body.classList.contains('light');
  const gridColor = () => isDark() ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.07)';
  const tickColor = () => isDark() ? '#4a4a6a' : '#8888a0';
  const tooltipBg = () => isDark() ? '#0f0f1c' : '#ffffff';
  const tooltipTxt = () => isDark() ? '#e8e8f0' : '#111128';

  const labels = {labels_json};
  const datasets = {datasets_json};

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

  const cfg = {{
    type: 'line',
    data: {{ labels, datasets }},
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
            title: ctx => 'Cycle #' + ctx[0].label,
            label: ctx => ' ' + ctx.dataset.label + ': €' + (ctx.raw ?? '—'),
          }}
        }}
      }},
      scales: {{
        x: {{
          title: {{ display: true, text: 'Ciclo', color: tickColor(), font: {{ size: 10 }} }},
          grid: {{ color: gridColor() }},
          ticks: {{ color: tickColor(), font: {{ family: "'JetBrains Mono', monospace", size: 10 }} }}
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

  // Rebuild chart on theme toggle so colors update
  window._rebuildChart = function() {{
    chart.destroy();
    cfg.options.plugins.legend.labels.color = tickColor();
    cfg.options.plugins.tooltip.backgroundColor = tooltipBg();
    cfg.options.plugins.tooltip.titleColor = tooltipTxt();
    cfg.options.plugins.tooltip.bodyColor = tickColor();
    cfg.options.plugins.tooltip.borderColor = isDark() ? '#1a1a2e' : '#d0d4e8';
    cfg.options.scales.x.grid.color = gridColor();
    cfg.options.scales.x.ticks.color = tickColor();
    cfg.options.scales.y.grid.color = gridColor();
    cfg.options.scales.y.ticks.color = tickColor();
    chart = new Chart(document.getElementById('portfolioChart'), cfg);
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
  --muted: #9090b8;
  --dim: #5a5a7e;
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
  --muted: #5a5a80;
  --dim: #9898b8;
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
  .header-title { font-size: 18px; }
  .header-meta { font-size: 10px; }
  .header-ts .ts { font-size: 11px; }
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
  font-size: 11px;
  margin-top: 8px;
  min-height: 16px;
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

    histories = {key: _load_history(key) for key in PROFILES}
    has_history = any(len(h) > 0 for h in histories.values())

    if has_history:
        chart_section = f"""
<div class="chart-section">
  <div class="section-label">Evolución del portfolio (€ por ciclo)</div>
  <div class="chart-wrap"><canvas id="portfolioChart"></canvas></div>
</div>"""
    else:
        chart_section = """
<div class="chart-section">
  <div class="section-label">Evolución del portfolio</div>
  <div class="chart-empty">Sin datos históricos aún — el gráfico aparecerá tras el primer ciclo.</div>
</div>"""

    now          = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    cards        = "\n".join(_profile_card(k, p, prices) for k, p in PROFILES.items())
    sources_html  = _data_sources_panel()
    subscribe_html = ""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryptoAiArena — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Syne:wght@600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
<style>{CSS}</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="header-title">
      <span class="live-dot"></span>
      Crypto<span class="ai">Ai</span>Arena
    </div>
    <div class="header-meta">Paper trading · 3 agentes</div>
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
    </div>
    <div class="subscribe-msg" id="sub-msg"></div>
  </div>

  <div class="header-right">
    <div class="header-ts">
      <span class="ts" id="localTime">{now}</span>
      <span id="tzLabel">UTC</span> · precios live · CoinGecko
    </div>
    <button class="theme-btn" id="themeBtn" onclick="toggleTheme()" title="Cambiar tema">☀️</button>
  </div>
</header>

{chart_section}

<div class="grid">
{cards}
</div>

{subscribe_html}

{sources_html}

{_chart_script(histories) if has_history else ''}

<script>
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


if __name__ == "__main__":
    generate()
