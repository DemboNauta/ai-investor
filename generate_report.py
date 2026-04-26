"""Genera web/index.html con portfolios, precios live, chart histórico y memorias."""
import os
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

ACCENT  = {"moderate": "#00d4ff", "aggressive": "#ffb800", "degen": "#ff3366"}
RISK_LABEL = {"moderate": "LOW RISK", "aggressive": "HIGH RISK", "degen": "EXTREME"}
CATEGORY_COLOR = {
    "insight": "#00d4ff", "error": "#ff4466", "strategy": "#a78bfa",
    "market_pattern": "#ffb800", "lesson": "#00ff87", "summary": "#555570",
}


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


def _trade_items(trades: list) -> str:
    if not trades:
        return '<div class="no-data">sin trades aún</div>'
    items = []
    for t in reversed(trades[-10:]):
        a  = t["action"]
        ts = t["ts"][:16].replace("T", " ")
        items.append(f"""<div class="trade-item {a}">
          <span class="trade-action {a}">{a.upper()}</span>
          <span class="trade-coin">{html_module.escape(t['coin_id'])}</span>
          <span class="trade-eur">{_eur(t['amount_eur'])}</span>
          <span class="trade-price">@ {_eur(t['price_eur'])}</span>
          <span class="trade-ts">{ts}</span>
        </div>""")
    return "".join(items)


def _memory_summaries(summaries: list) -> str:
    if not summaries:
        return '<div class="no-data">sin lecciones aún</div>'
    items = "".join(f'<li>{html_module.escape(s)}</li>' for s in summaries)
    return f'<ul class="memory-summary">{items}</ul>'


def _memory_entries(entries: list) -> str:
    if not entries:
        return '<div class="no-data">sin entradas aún</div>'
    items = []
    for e in reversed(entries[-12:]):
        cat   = e["category"]
        color = CATEGORY_COLOR.get(cat, "#555570")
        stars = "★" * e.get("importance", 2) + "☆" * (3 - e.get("importance", 2))
        pnl_html = ""
        if "pnl_pct" in e:
            pnl_html = f'<span class="entry-pnl {_pc(e["pnl_pct"])}">{_pct(e["pnl_pct"])}</span>'
        items.append(f"""<div class="entry-item" style="border-left-color:{color}">
          <div class="entry-meta">
            <span class="entry-cat" style="background:{color}20;color:{color}">{html_module.escape(cat)}</span>
            <span class="entry-cycle">cycle#{e['cycle']}</span>
            <span class="entry-stars">{stars}</span>
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

    summaries = m.get("summaries", [])
    entries   = m.get("entries", [])

    return f"""<div class="card card-{key}">
      <div class="card-header">
        <div>
          <div class="card-name" style="color:{accent}">{html_module.escape(profile['name'])}</div>
          <div class="card-cycle">cycle #{cycle} · {last_run_str} UTC</div>
        </div>
        <div class="risk-badge" style="background:{accent}18;color:{accent};border:1px solid {accent}40">{risk}</div>
      </div>
      <div class="card-body">

        <div class="stats-row">
          <div class="stat-block">
            <div class="stat-label">Total Value</div>
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
        </table>

        <div class="section-label">Trades recientes</div>
        <div class="trade-list">{_trade_items(trades)}</div>

        <div class="section-label">Memoria
          <span class="mem-meta">{len(entries)} entradas · {len(summaries)} lecciones</span>
        </div>
        {_memory_summaries(summaries)}
        <div class="entry-list">{_memory_entries(entries)}</div>

      </div>
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
  --border: #1a1a2e;
  --text: #e8e8f0;
  --muted: #4a4a6a;
  --dim: #22223a;
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
  --muted: #7878a0;
  --dim: #c0c2d8;
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
.stat-sub.pos { color: var(--green); opacity: 0.7; }
.stat-sub.neg { color: var(--red); opacity: 0.7; }

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
  color: var(--muted);
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

.trade-action { font-weight: 700; font-size: 9px; letter-spacing: 1px; min-width: 28px; }
.trade-action.buy  { color: var(--green); }
.trade-action.sell { color: var(--red); }

.trade-coin  { color: var(--text); flex: 1; font-size: 11px; text-transform: uppercase; min-width: 60px; }
.trade-eur   { color: var(--muted); }
.trade-price { color: var(--dim); font-size: 10px; }
.trade-ts    { color: var(--dim); font-size: 10px; margin-left: auto; }

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
  color: var(--muted);
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
.entry-content { color: var(--muted); line-height: 1.55; }

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
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--dim); border-radius: 2px; }
"""


def generate():
    all_coin_ids = set()
    for profile in PROFILES.values():
        p = _load_portfolio(profile["portfolio_file"])
        all_coin_ids.update(p.get("holdings", {}).keys())

    print(f"[report] Precios para: {', '.join(all_coin_ids) or 'ninguno'}")
    prices = _fetch_prices(list(all_coin_ids))

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

    now   = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    cards = "\n".join(_profile_card(k, p, prices) for k, p in PROFILES.items())

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>AI Investor — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Syne:wght@600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="header-title">
      <span class="live-dot"></span>
      <span class="ai">AI</span><span class="sep">/</span>Investor
    </div>
    <div class="header-meta">Paper trading · 3 agentes · actualiza cada 5 min</div>
  </div>
  <div class="header-right">
    <div class="header-ts">
      <span class="ts">{now}</span>
      precios live · CoinGecko
    </div>
    <button class="theme-btn" id="themeBtn" onclick="toggleTheme()" title="Cambiar tema">☀️</button>
  </div>
</header>

{chart_section}

<div class="grid">
{cards}
</div>

{_chart_script(histories) if has_history else ''}

<script>
(function() {{
  if (localStorage.getItem('theme') === 'light') {{
    document.body.classList.add('light');
    const btn = document.getElementById('themeBtn');
    if (btn) btn.textContent = '🌙';
  }}
}})();
function toggleTheme() {{
  document.body.classList.toggle('light');
  const isLight = document.body.classList.contains('light');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = isLight ? '🌙' : '☀️';
  if (window._rebuildChart) window._rebuildChart();
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
