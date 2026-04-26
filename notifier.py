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


def notify_cycle(
    cycle: int,
    trade_log: list[str],
    agent_summary: str,
    total_eur: float,
    pnl_eur: float,
    pnl_pct: float,
    cash_eur: float,
    profile_name: str = "Default",
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pnl_color = "#16a34a" if pnl_eur >= 0 else "#dc2626"
    pnl_sign = "+" if pnl_eur >= 0 else ""

    trades_html = ""
    if trade_log:
        rows = ""
        for t in trade_log:
            color = "#16a34a" if t.startswith("BUY") else "#dc2626"
            rows += f'<tr><td style="color:{color};font-family:monospace;padding:4px 8px">{t}</td></tr>'
        trades_html = f"""
        <h3 style="margin:16px 0 8px">Trades ({len(trade_log)})</h3>
        <table style="border-collapse:collapse;width:100%">{rows}</table>
        """
    else:
        trades_html = '<p style="color:#6b7280">No trades this cycle — held position.</p>'

    summary_html = f'<p style="background:#f3f4f6;padding:12px;border-radius:6px;font-style:italic">{agent_summary}</p>' if agent_summary else ""

    body = f"""
    <html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px">
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

      <h3 style="margin:16px 0 8px">Agent Analysis</h3>
      {summary_html}

      <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
      <p style="color:#94a3b8;font-size:12px">AI Investor — paper trading simulation. Not financial advice.</p>
    </body></html>
    """

    subject = f"[AI Investor/{profile_name}] Cycle #{cycle} — €{total_eur:,.2f} ({pnl_sign}{pnl_pct:.1f}%)"
    _send(subject, body)
