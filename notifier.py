"""Envío de emails vía Resend SDK."""
import os
import resend
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL   = os.getenv("FROM_EMAIL", "noreply@send.cryptoaiarena.com")
FROM_NAME    = os.getenv("FROM_NAME", "CryptoAiArena")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "edgarmila10744@gmail.com")


def _send(to: str, subject: str, html: str) -> bool:
    if not resend.api_key:
        print("[notifier] RESEND_API_KEY no configurado")
        return False
    try:
        r = resend.Emails.send({
            "from": f"{FROM_NAME} <{FROM_EMAIL}>",
            "to": [to],
            "subject": subject,
            "html": html,
        })
        if "id" in r:
            return True
        print(f"[notifier] Resend error: {r}")
        return False
    except Exception as e:
        print(f"[notifier] Resend error: {e}")
        return False


def _unsub_footer(email: str) -> str:
    import subscribers as subs
    return f"""
    <hr style="border:none;border-top:1px solid #1e1e32;margin:28px 0">
    <p style="color:#5a5a7e;font-size:11px;text-align:center;font-family:monospace">
      Suscrito en <a href="https://cryptoaiarena.com" style="color:#5a5a7e">cryptoaiarena.com</a> ·
      <a href="{subs.unsub_url(email)}" style="color:#5a5a7e">Cancelar suscripción</a>
    </p>"""


def send_bulk(subscribers: list[str], subject: str, html: str) -> int:
    """Envía a cada suscriptor con link de baja personalizado. Devuelve nº enviados."""
    sent = 0
    for email in subscribers:
        if _send(email, subject, html + _unsub_footer(email)):
            sent += 1
    print(f"[notifier] Bulk: {sent}/{len(subscribers)} enviados — {subject[:50]}")
    return sent


# ── HTML helpers ──────────────────────────────────────────────────────────────

_BASE_STYLE = """
<style>
  body{font-family:'Segoe UI',sans-serif;background:#06060d;color:#e8e8f0;margin:0;padding:0}
  .wrap{max-width:640px;margin:0 auto;padding:32px 20px}
  .header{border-bottom:1px solid #1e1e32;padding-bottom:20px;margin-bottom:24px}
  .title{font-size:20px;font-weight:700;color:#00d4ff;letter-spacing:-0.3px}
  .meta{font-size:12px;color:#5a5a7e;margin-top:4px}
  .card{background:#0f0f1c;border:1px solid #1e1e32;border-radius:6px;padding:16px 20px;margin-bottom:12px}
  .card-title{font-size:13px;font-weight:700;margin-bottom:12px}
  .stats{display:flex;gap:20px;flex-wrap:wrap}
  .stat-label{font-size:10px;color:#5a5a7e;text-transform:uppercase;letter-spacing:1px}
  .stat-value{font-size:18px;font-weight:700;font-family:monospace}
  .pos{color:#00ff87}.neg{color:#ff4466}
  table{border-collapse:collapse;width:100%;font-size:12px;font-family:monospace}
  th{text-align:left;color:#5a5a7e;padding:4px 8px;font-weight:500;font-size:10px;text-transform:uppercase}
  td{padding:6px 8px;border-top:1px solid #1e1e32}
  .badge{display:inline-block;font-size:9px;font-weight:700;padding:2px 6px;border-radius:2px;letter-spacing:1px}
  .badge-buy{background:#00ff8720;color:#00ff87}.badge-sell{background:#ff446620;color:#ff4466}
  .btn{display:inline-block;background:#00d4ff;color:#06060d;font-weight:700;font-size:13px;
       padding:10px 24px;border-radius:4px;text-decoration:none;margin-top:16px}
  .footer{color:#5a5a7e;font-size:11px;margin-top:24px;padding-top:16px;border-top:1px solid #1e1e32}
  .no-data{color:#5a5a7e;font-size:12px;font-style:italic}
</style>
"""


def _wrap(content: str, title: str = "CryptoAiArena", subtitle: str = "") -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">{_BASE_STYLE}</head>
<body><div class="wrap">
  <div class="header">
    <div class="title">CryptoAiArena</div>
    <div class="meta">{title}{' · ' + subtitle if subtitle else ''} · {now}</div>
  </div>
  {content}
  <div class="footer">Paper trading · No es asesoramiento financiero.</div>
</div></body></html>"""


def _activity_html(activity_log: list[dict]) -> str:
    if not activity_log:
        return ""
    rows = ""
    for entry in activity_log:
        tool = entry["tool"]
        if tool == "buy":
            coin = entry.get("coin_id", "?")
            eur  = entry.get("amount_eur", 0)
            price = entry.get("price") or "?"
            reasoning = entry.get("reasoning", "")
            rows += f"""<tr>
              <td><span class="badge badge-buy">BUY</span></td>
              <td style="text-transform:uppercase">{coin}</td>
              <td>€{eur:.2f} @ €{price}</td>
              <td style="color:#9090b8;font-size:11px">{reasoning[:80]}</td>
            </tr>"""
        elif tool == "sell":
            coin  = entry.get("coin_id", "?")
            eur   = entry.get("amount_eur", 0)
            price = entry.get("price") or "?"
            label = "ALL" if eur < 0 else f"€{eur:.2f}"
            reasoning = entry.get("reasoning", "")
            rows += f"""<tr>
              <td><span class="badge badge-sell">SELL</span></td>
              <td style="text-transform:uppercase">{coin}</td>
              <td>{label} @ €{price}</td>
              <td style="color:#9090b8;font-size:11px">{reasoning[:80]}</td>
            </tr>"""
        elif tool == "done":
            summary = entry.get("args", {}).get("summary", "")
            if summary:
                rows += f"""<tr>
                  <td colspan="4" style="color:#5a5a7e;font-style:italic;font-size:11px">
                    {summary[:120]}
                  </td>
                </tr>"""
    if not rows:
        return ""
    return f"""<table style="margin-top:8px">
      <thead><tr><th>Acción</th><th>Coin</th><th>Importe</th><th>Razonamiento</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


# ── Notificaciones ────────────────────────────────────────────────────────────

def notify_cycle(
    cycle: int,
    trade_log: list[str],
    agent_summary: str,
    total_eur: float,
    pnl_eur: float,
    pnl_pct: float,
    cash_eur: float,
    profile_name: str = "Default",
    activity_log: list[dict] | None = None,
) -> None:
    """Notificación por ciclo al owner."""
    pnl_cls  = "pos" if pnl_eur >= 0 else "neg"
    pnl_sign = "+" if pnl_eur >= 0 else ""
    trades_html = _activity_html(activity_log or [])
    if not trades_html and not trade_log:
        trades_section = '<p class="no-data">Sin trades este ciclo.</p>'
    elif not trades_html:
        rows = "".join(
            f'<tr><td><span class="badge {"badge-buy" if t.startswith("BUY") else "badge-sell"}">'
            f'{"BUY" if t.startswith("BUY") else "SELL"}</span></td>'
            f'<td colspan="3">{t}</td></tr>'
            for t in trade_log
        )
        trades_section = f"<table><tbody>{rows}</tbody></table>"
    else:
        trades_section = trades_html

    summary_html = f'<p style="font-style:italic;color:#9090b8;font-size:13px">{agent_summary}</p>' if agent_summary else ""

    content = f"""
    <div class="card">
      <div class="stats">
        <div>
          <div class="stat-label">Valor total</div>
          <div class="stat-value">€{total_eur:,.2f}</div>
        </div>
        <div>
          <div class="stat-label">P&amp;L</div>
          <div class="stat-value {pnl_cls}">{pnl_sign}€{abs(pnl_eur):,.2f} ({pnl_sign}{pnl_pct:.1f}%)</div>
        </div>
        <div>
          <div class="stat-label">Cash</div>
          <div class="stat-value">€{cash_eur:,.2f}</div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Trades · ciclo #{cycle}</div>
      {trades_section}
    </div>
    {('<div class="card">' + summary_html + '</div>') if summary_html else ''}
    <a class="btn" href="https://cryptoaiarena.com">Ver dashboard</a>
    """
    subject = f"[{profile_name}] Ciclo #{cycle} — €{total_eur:,.2f} ({pnl_sign}{pnl_pct:.1f}%)"
    _send(NOTIFY_EMAIL, subject, _wrap(content, profile_name, f"Ciclo #{cycle}"))


def notify_alert(
    profile_name: str,
    cycle: int,
    reason: str,
    total_eur: float,
    pnl_pct: float,
    trade_log: list[str],
    activity_log: list[dict],
    fear_greed: dict | None,
) -> int:
    """Alerta urgente a todos los suscriptores. Devuelve nº enviados."""
    import subscribers as subs

    recipients = subs.get_all()
    if not recipients:
        return 0

    pnl_sign = "+" if pnl_pct >= 0 else ""
    pnl_cls  = "pos" if pnl_pct >= 0 else "neg"
    fg_val   = fear_greed.get("value") if fear_greed else None
    fg_label = fear_greed.get("value_classification", "") if fear_greed else ""
    fg_html  = f'<p style="margin:0 0 12px">Fear &amp; Greed: <strong>{fg_val} — {fg_label}</strong></p>' if fg_val is not None else ""

    trades_html = _activity_html(activity_log) or '<p class="no-data">Sin trades este ciclo.</p>'

    content = f"""
    <div class="card" style="border-color:#ff446640">
      <div class="card-title" style="color:#ff4466">⚡ Alerta de mercado — {profile_name}</div>
      <p style="color:#9090b8;font-size:13px;margin:0 0 12px">{reason}</p>
      {fg_html}
      <div class="stats">
        <div>
          <div class="stat-label">Portfolio</div>
          <div class="stat-value">€{total_eur:,.2f}</div>
        </div>
        <div>
          <div class="stat-label">P&amp;L total</div>
          <div class="stat-value {pnl_cls}">{pnl_sign}{pnl_pct:.1f}%</div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Actividad · ciclo #{cycle}</div>
      {trades_html}
    </div>
    <a class="btn" href="https://cryptoaiarena.com">Ver dashboard en vivo</a>
    """
    subject = f"⚡ [{profile_name}] Alerta: {reason[:60]}"
    return send_bulk(recipients, subject, _wrap(content, "Alerta", profile_name))


def notify_confirmation(email: str, confirm_url: str) -> None:
    """Email de confirmación doble opt-in."""
    content = f"""
    <div class="card">
      <div class="card-title">Confirma tu suscripción</div>
      <p style="color:#9090b8;font-size:13px;line-height:1.6">
        Alguien (esperamos que tú) solicitó recibir alertas de <strong>CryptoAiArena</strong>
        en esta dirección. Haz clic para confirmar.
      </p>
      <p style="color:#5a5a7e;font-size:12px">
        Si no fuiste tú, ignora este email. Sin tu confirmación no recibirás nada más.
      </p>
    </div>
    <a class="btn" href="{confirm_url}" style="background:#00d4ff;color:#06060d">
      Confirmar suscripción
    </a>
    <p style="color:#5a5a7e;font-size:11px;margin-top:12px;font-family:monospace">
      O copia este enlace: {confirm_url}
    </p>
    """
    _send(email, "Confirma tu suscripción — CryptoAiArena", _wrap(content, "Confirmación"))


def notify_welcome(email: str) -> None:
    """Email de bienvenida tras confirmar."""
    content = f"""
    <div class="card">
      <div class="card-title" style="color:#00ff87">✓ Suscripción activa</div>
      <p style="color:#9090b8;font-size:13px;line-height:1.6">
        Ya estás suscrito a las alertas de <strong>CryptoAiArena</strong>.
        Esto es lo que recibirás:
      </p>
      <ul style="color:#9090b8;font-size:13px;line-height:1.9;padding-left:18px">
        <li>📊 Resumen diario a las 18:00 UTC con el estado de los 6 portfolios (Grok vs GPT-4o mini)</li>
        <li>⚡ Alertas puntuales cuando haya movimientos relevantes en el mercado</li>
      </ul>
    </div>
    <a class="btn" href="https://cryptoaiarena.com">Ver dashboard ahora</a>
    {_unsub_footer(email)}
    """
    _send(email, "Bienvenido a CryptoAiArena Alerts", _wrap(content, "Bienvenido"))
