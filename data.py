import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FEAR_GREED_URL = "https://api.alternative.me/fng/"


def get_market_data(limit: int = 50) -> list[dict]:
    url = f"{COINGECKO_BASE}/coins/markets"
    params = {
        "vs_currency": "eur",
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": True,
        "price_change_percentage": "1h,24h,7d,30d",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_fear_greed() -> dict:
    try:
        resp = requests.get(FEAR_GREED_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        return {"value": int(data["value"]), "label": data["value_classification"]}
    except Exception:
        return {"value": None, "label": "unavailable"}


def _rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)


def _ma_ratio(prices: list[float], short: int = 24, long: int = 168) -> float | None:
    """MA24/MA168 ratio. >1 = short-term above long-term (bullish)."""
    if len(prices) < long:
        return None
    ma_short = sum(prices[-short:]) / short
    ma_long = sum(prices[-long:]) / long
    if ma_long == 0:
        return None
    return round(ma_short / ma_long, 3)


def enrich_with_indicators(coins: list[dict]) -> list[dict]:
    """Add RSI14, MA ratio, ATH% to each coin using sparkline data."""
    for c in coins:
        sparkline = (c.get("sparkline_in_7d") or {}).get("price") or []
        c["rsi14"] = _rsi(sparkline)
        c["ma_ratio"] = _ma_ratio(sparkline)
        ath_pct = c.get("ath_change_percentage")
        c["ath_pct"] = round(ath_pct, 1) if ath_pct is not None else None
    return coins


def format_market_data_for_llm(coins: list[dict], fear_greed: dict | None = None) -> str:
    lines = []

    if fear_greed and fear_greed["value"] is not None:
        val = fear_greed["value"]
        label = fear_greed["label"]
        sentiment = "EXTREME FEAR" if val < 25 else "FEAR" if val < 45 else "NEUTRAL" if val < 55 else "GREED" if val < 75 else "EXTREME GREED"
        lines.append(f"MARKET SENTIMENT: Fear & Greed Index = {val}/100 ({label} / {sentiment})\n")

    lines.append("MARKET DATA (EUR) — top coins by market cap")
    lines.append(
        f"{'ID':<20} {'Price':>12} {'1h%':>7} {'24h%':>7} {'7d%':>7} {'30d%':>7} "
        f"{'RSI14':>6} {'MA24/168':>9} {'ATH%':>8} {'Vol24h(M)':>10}"
    )
    lines.append("-" * 115)

    for c in coins:
        def pct(key):
            v = c.get("price_change_percentage_" + key + "_in_currency")
            return f"{v:+.1f}%" if v is not None else "  n/a"

        rsi = f"{c['rsi14']:.0f}" if c.get("rsi14") is not None else " n/a"
        mar = f"{c['ma_ratio']:.3f}" if c.get("ma_ratio") is not None else "   n/a"
        ath = f"{c['ath_pct']:+.0f}%" if c.get("ath_pct") is not None else "   n/a"
        vol = (c.get("total_volume") or 0) / 1_000_000

        lines.append(
            f"{c['id']:<20} {c['current_price']:>12.4f} {pct('1h'):>7} {pct('24h'):>7} "
            f"{pct('7d'):>7} {pct('30d'):>7} {rsi:>6} {mar:>9} {ath:>8} {vol:>10.1f}"
        )

    lines.append("\nINDICATOR GUIDE:")
    lines.append("  RSI14: <30=oversold(buy signal), >70=overbought(sell signal), 30-70=neutral")
    lines.append("  MA24/168: >1.0=short-term bullish, <1.0=short-term bearish vs 7d average")
    lines.append("  ATH%: how far below all-time-high (e.g. -80% = deeply discounted)")

    return "\n".join(lines)
