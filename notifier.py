import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "AI Investor")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "edgarxiaomi10744@gmail.com")


def _send(subject: str, body_html: str) -> None:
    if not SMTP_USER or not SMTP_PASS:
        print("[notifier] SMTP not configured, skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(body_html, "html"))

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
    except Exception as e:
        print(f"[notifier] Email failed: {e}")


def _activity_html(activity_log: list[dict]) -> str:
    if not activity_log:
        return ""

    rows = ""
    for entry in activity_log:
        tool = entry["tool"]
        status = entry.get("status", "ok")
        err_style = ' style="background:#fef2f2"' if status == "error" else ""

        if tool == "buy":
            icon = "🟢 BUY"
            coin = entry.get("coin_id", "?")
            eur = entry.get("amount_eur", 0)
            price = entry.get("price") or "?"
            reasoning = entry.get("reasoning", "")
            result = entry.get("result", "")
            rows += f"""
            <tr{err_style}>
              <td style="padding:6px 8px;font-weight:bold;white-space:nowrap">{icon}</td>
              <td style="padding:6px 8px;font-family:monospace">{coin}</td>
              <td style="padding:6px 8px">€{eur:.2f} @ €{price}</td>
              <td style="padding:6px 8px;color:#64748b;font-size:12px">{reasoning}</td>
              <td style="padding:6px 8px;font-size:12px;color:{'#dc2626' if status=='error' else '#16a34a'}">{result}</td>
            </tr>"""
        elif tool == "sell":
            icon = "🔴 SELL"
            coin = entry.get("coin_id", "?")
            eur = entry.get("amount_eur", 0)
            price = entry.get("price") or "?"
            label = "ALL" if eur < 0 else f"€{eur:.2f}"
            reasoning = entry.get("reasoning", "")
            result = entry.get("result", "")
            rows += f"""
            <tr{err_style}>
              <td style="padding:6px 8px;font-weight:bold;white-space:nowrap">{icon}</td>
              <td style="padding:6px 8px;font-family:monospace">{coin}</td>
              <td style="padding:6px 8px">{label} @ €{price}</td>
              <td style="padding:6px 8px;color:#64748b;font-size:12px">{reasoning}</td>
              <td style="padding:6px 8px;font-size:12px;color:{'#dc2626' if status=='error' else '#16a34a'}">{result}</td>
            </tr>"""
        elif tool == "done":
            rows += f"""
            <tr style="background:#f8fafc">
              <td colspan="5" style="padding:6px 8px;color:#64748b;font-size:12px">
                ⏹ <strong>DONE</strong> — {entry.get('args', {}).get('summary', '')}
              </td>
            </tr>"""

    return f"""
    <h3 style="margin:20px 0 8px">Agent Tool Calls</h3>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead>
        <tr style="background:#f1f5f9;color:#64748b">
          <th style="padding:6px 8px;text-align:left">Action</th>
          <th style="padding:6px 8px;text-align:left">Coin</th>
          <th style="padding:6px 8px;text-align:left">Amount</th>
          <th style="padding:6px 8px;text-align:left">Reasoning</th>
          <th style="padding:6px 8px;text-align:left">Result</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pnl_color = "#16a34a" if pnl_eur >= 0 else "#dc2626"
    pnl_sign = "+" if pnl_eur >= 0 else ""

    if not trade_log:
        trades_html = '<p style="color:#6b7280">No trades this cycle — held position.</p>'
    else:
        rows = ""
        for t in trade_log:
            color = "#16a34a" if t.startswith("BUY") else "#dc2626"
            rows += f'<tr><td style="color:{color};font-family:monospace;padding:4px 8px">{t}</td></tr>'
        trades_html = f"""
        <h3 style="margin:16px 0 8px">Trades ({len(trade_log)})</h3>
        <table style="border-collapse:collapse;width:100%">{rows}</table>
        """

    summary_html = f'<p style="background:#f3f4f6;padding:12px;border-radius:6px;font-style:italic">{agent_summary}</p>' if agent_summary else ""
    activity_html = _activity_html(activity_log or [])

    body = f"""
    <html><body style="font-family:sans-serif;max-width:700px;margin:0 auto;padding:20px">
      <h2 style="color:#1e293b">AI Investor [{profile_name}] — Cycle #{cycle}</h2>
      <p style="color:#64748b">{now}</p>

      <table style="width:100%;border-collapse:collapse;margin:16px 0">
        <tr>
          <td style="padding:12px;background:#f8fafc;border-radius:6px">
            <div style="font-size:24px;font-weight:bold">€{total_eur:,.2f}</div>
            <div style="color:#64748b">Portfolio Value</div>
          </td>
          <td style="padding:12px">
            <div style="font-size:24px;font-weight:bold;color:{pnl_color}">{pnl_sign}€{abs(pnl_eur):,.2f}</div>
            <div style="color:{pnl_color}">{pnl_sign}{pnl_pct:.2f}% total P&L</div>
          </td>
          <td style="padding:12px">
            <div style="font-size:20px;font-weight:bold">€{cash_eur:,.2f}</div>
            <div style="color:#64748b">Cash available</div>
          </td>
        </tr>
      </table>

      {trades_html}
      {activity_html}

      <h3 style="margin:16px 0 8px">Agent Analysis</h3>
      {summary_html}

      <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
      <p style="color:#94a3b8;font-size:12px">AI Investor — paper trading simulation. Not financial advice.</p>
    </body></html>
    """

    subject = f"[AI Investor/{profile_name}] Cycle #{cycle} — €{total_eur:,.2f} ({pnl_sign}{pnl_pct:.1f}%)"
    _send(subject, body)
