import requests
import xml.etree.ElementTree as ET
import re

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FEAR_GREED_URL = "https://api.alternative.me/fng/"

_NEWS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

# CoinGecko ID → Binance perpetual futures symbol
_BINANCE_SYMBOLS = {
    "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT",
    "binancecoin": "BNBUSDT", "ripple": "XRPUSDT", "cardano": "ADAUSDT",
    "avalanche-2": "AVAXUSDT", "dogecoin": "DOGEUSDT", "polkadot": "DOTUSDT",
    "chainlink": "LINKUSDT", "uniswap": "UNIUSDT", "litecoin": "LTCUSDT",
    "stellar": "XLMUSDT", "the-open-network": "TONUSDT", "sui": "SUIUSDT",
    "pepe": "PEPEUSDT", "shiba-inu": "SHIBUSDT", "near": "NEARUSDT",
    "aptos": "APTUSDT", "arbitrum": "ARBUSDT", "optimism": "OPUSDT",
    "render-token": "RENDERUSDT", "injective-protocol": "INJUSDT",
    "sei-network": "SEIUSDT", "celestia": "TIAUSDT", "internet-computer": "ICPUSDT",
    "filecoin": "FILUSDT", "hedera-hashgraph": "HBARUSDT", "cosmos": "ATOMUSDT",
    "algorand": "ALGOUSDT", "vechain": "VETUSDT", "tron": "TRXUSDT",
    "ondo-finance": "ONDOUSDT", "worldcoin-wld": "WLDUSDT",
}


# ── Fetch functions ────────────────────────────────────────────────────────────

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


def get_global_market() -> dict:
    """BTC/ETH dominance, total market cap EUR, 24h market cap change."""
    try:
        resp = requests.get(f"{COINGECKO_BASE}/global", timeout=10)
        resp.raise_for_status()
        d = resp.json()["data"]
        mcap = d.get("total_market_cap", {})
        return {
            "btc_dominance": round(d["market_cap_percentage"].get("btc", 0), 1),
            "eth_dominance": round(d["market_cap_percentage"].get("eth", 0), 1),
            "total_market_cap_eur": mcap.get("eur", 0),
            "market_cap_change_24h_pct": round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
            "active_cryptos": d.get("active_cryptocurrencies", 0),
        }
    except Exception:
        return {}


def get_trending() -> list[dict]:
    """Top 7 trending coins on CoinGecko right now."""
    try:
        resp = requests.get(f"{COINGECKO_BASE}/search/trending", timeout=10)
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        return [
            {
                "id": c["item"]["id"],
                "name": c["item"]["name"],
                "symbol": c["item"]["symbol"].upper(),
                "rank": c["item"].get("market_cap_rank"),
            }
            for c in coins[:7]
        ]
    except Exception:
        return []


def get_crypto_news(max_items: int = 12) -> list[str]:
    """Recent crypto headlines from Coindesk + Cointelegraph RSS (no API key needed)."""
    headlines = []
    for url in _NEWS_FEEDS:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:6]:
                title = (item.findtext("title") or "").strip()
                title = re.sub(r"<[^>]+>", "", title)
                if title:
                    headlines.append(title)
        except Exception:
            continue
    return headlines[:max_items]


def get_funding_rates() -> dict[str, float]:
    """
    Perpetual futures funding rates from Binance (free, no key).
    Positive rate = longs paying shorts = bearish pressure.
    Negative rate = shorts paying longs = bullish pressure.
    Returns {coin_id: rate_pct_per_8h}.
    """
    try:
        resp = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=10)
        resp.raise_for_status()
        all_rates = {item["symbol"]: float(item["lastFundingRate"]) for item in resp.json()}
        result = {}
        for coin_id, symbol in _BINANCE_SYMBOLS.items():
            if symbol in all_rates:
                result[coin_id] = round(all_rates[symbol] * 100, 4)
        return result
    except Exception:
        return {}


def get_macro_context() -> dict:
    """
    DXY (dollar index) and S&P 500 from Yahoo Finance (free, no key).
    DXY rising → crypto headwind. SPY falling → risk-off.
    """
    tickers = {"DXY": "DX-Y.NYB", "SP500": "^GSPC"}
    result = {}
    for name, symbol in tickers.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            resp = requests.get(
                url,
                params={"interval": "1d", "range": "5d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            resp.raise_for_status()
            chart = resp.json()["chart"]["result"][0]
            closes = [c for c in chart["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) >= 2:
                chg = (closes[-1] - closes[-2]) / closes[-2] * 100
                result[name] = {"price": round(closes[-1], 2), "change_1d_pct": round(chg, 2)}
            else:
                result[name] = None
        except Exception:
            result[name] = None
    return result


# ── Technical indicators ───────────────────────────────────────────────────────

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


def _ema_series(prices: list[float], period: int) -> list[float]:
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(prices[:period]) / period]
    for p in prices[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def _macd_histogram(prices: list[float]) -> float | None:
    """MACD histogram (MACD line - signal line). Positive = bullish momentum."""
    ema12 = _ema_series(prices, 12)
    ema26 = _ema_series(prices, 26)
    if not ema12 or not ema26:
        return None
    offset = len(ema12) - len(ema26)
    macd_series = [ema12[i + offset] - ema26[i] for i in range(len(ema26))]
    if len(macd_series) < 9:
        return None
    signal_series = _ema_series(macd_series, 9)
    if not signal_series:
        return None
    hist = macd_series[-1] - signal_series[-1]
    # Normalize as % of current price so it's comparable across coins
    current = prices[-1]
    if current == 0:
        return None
    return round(hist / current * 100, 3)


def _bollinger_pct_b(prices: list[float], period: int = 20, std_dev: float = 2.0) -> float | None:
    """%B position within Bollinger Bands. 0=lower band, 1=upper band, 0.5=middle."""
    if len(prices) < period:
        return None
    window = prices[-period:]
    ma = sum(window) / period
    variance = sum((p - ma) ** 2 for p in window) / period
    std = variance ** 0.5
    if std == 0:
        return None
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    pct_b = (prices[-1] - lower) / (upper - lower)
    return round(max(0.0, min(1.0, pct_b)), 3)


def enrich_with_indicators(coins: list[dict]) -> list[dict]:
    """Add RSI14, MA ratio, ATH%, MACD histogram, Bollinger %B to each coin."""
    for c in coins:
        sparkline = (c.get("sparkline_in_7d") or {}).get("price") or []
        c["rsi14"] = _rsi(sparkline)
        c["ma_ratio"] = _ma_ratio(sparkline)
        c["macd_hist"] = _macd_histogram(sparkline)
        c["bb_pct_b"] = _bollinger_pct_b(sparkline)
        ath_pct = c.get("ath_change_percentage")
        c["ath_pct"] = round(ath_pct, 1) if ath_pct is not None else None
    return coins


# ── Formatting ─────────────────────────────────────────────────────────────────

def format_market_data_for_llm(
    coins: list[dict],
    fear_greed: dict | None = None,
    global_market: dict | None = None,
    trending: list[dict] | None = None,
    funding_rates: dict[str, float] | None = None,
    macro: dict | None = None,
) -> str:
    lines = []

    # ── Macro context ──
    if macro:
        parts = []
        dxy = macro.get("DXY")
        spy = macro.get("SP500")
        if dxy:
            arrow = "↑" if dxy["change_1d_pct"] > 0 else "↓"
            signal = "CRYPTO HEADWIND" if dxy["change_1d_pct"] > 0.3 else "CRYPTO TAILWIND" if dxy["change_1d_pct"] < -0.3 else "neutral"
            parts.append(f"DXY {dxy['price']} ({dxy['change_1d_pct']:+.2f}% {arrow}, {signal})")
        if spy:
            arrow = "↑" if spy["change_1d_pct"] > 0 else "↓"
            risk = "RISK-ON" if spy["change_1d_pct"] > 0.5 else "RISK-OFF" if spy["change_1d_pct"] < -0.5 else "neutral"
            parts.append(f"S&P500 {spy['price']:,.0f} ({spy['change_1d_pct']:+.2f}% {arrow}, {risk})")
        if parts:
            lines.append("MACRO: " + " | ".join(parts))

    # ── Sentiment + global ──
    if fear_greed and fear_greed["value"] is not None:
        val = fear_greed["value"]
        label = fear_greed["label"]
        sentiment = "EXTREME FEAR" if val < 25 else "FEAR" if val < 45 else "NEUTRAL" if val < 55 else "GREED" if val < 75 else "EXTREME GREED"
        lines.append(f"SENTIMENT: Fear & Greed = {val}/100 ({label} / {sentiment})")

    if global_market:
        mcap_b = global_market.get("total_market_cap_eur", 0) / 1e9
        chg = global_market.get("market_cap_change_24h_pct", 0)
        btc_dom = global_market.get("btc_dominance", 0)
        eth_dom = global_market.get("eth_dominance", 0)
        alt_dom = round(100 - btc_dom - eth_dom, 1)
        direction = "RISK-ON" if chg > 1 else "RISK-OFF" if chg < -1 else "SIDEWAYS"
        lines.append(
            f"GLOBAL: Total cap €{mcap_b:.0f}B ({chg:+.2f}% 24h, {direction}) | "
            f"BTC dom {btc_dom}% | ETH dom {eth_dom}% | ALT dom {alt_dom}%"
        )
        if btc_dom > 55:
            lines.append("  → BTC dominance HIGH: prefer BTC/ETH over alts")
        elif btc_dom < 45:
            lines.append("  → BTC dominance LOW: alt season possible")

    if trending:
        symbols = ", ".join(f"{t['symbol']}(#{t['rank'] or '?'})" for t in trending)
        lines.append(f"TRENDING: {symbols}")

    # ── Funding rates ──
    if funding_rates:
        extremes = {cid: r for cid, r in funding_rates.items() if abs(r) >= 0.05}
        if extremes:
            lines.append("\nFUNDING RATES (8h %) — notable only:")
            for cid, rate in sorted(extremes.items(), key=lambda x: abs(x[1]), reverse=True)[:10]:
                signal = "OVERLEVERAGED LONG (bearish)" if rate > 0.1 else "HIGH LONG BIAS" if rate > 0.05 else "SHORT SQUEEZE RISK" if rate < -0.05 else ""
                lines.append(f"  {cid:<20} {rate:+.4f}%  {signal}")
            lines.append("  (funding >+0.1% = longs overextended, likely dump; <-0.05% = shorts overextended, likely squeeze)")

    lines.append("")

    # ── Per-coin table ──
    lines.append("MARKET DATA (EUR) — top coins by market cap")
    lines.append(
        f"{'ID':<20} {'Price':>12} {'1h%':>7} {'24h%':>7} {'7d%':>7} {'30d%':>7} "
        f"{'RSI':>5} {'MA24/168':>9} {'BB%B':>6} {'MACDh%':>8} {'ATH%':>7} {'Vol(M€)':>8}"
    )
    lines.append("-" * 131)

    for c in coins:
        def pct(key):
            v = c.get("price_change_percentage_" + key + "_in_currency")
            return f"{v:+.1f}%" if v is not None else "  n/a"

        rsi = f"{c['rsi14']:.0f}" if c.get("rsi14") is not None else " n/a"
        mar = f"{c['ma_ratio']:.3f}" if c.get("ma_ratio") is not None else "   n/a"
        bb = f"{c['bb_pct_b']:.2f}" if c.get("bb_pct_b") is not None else "  n/a"
        mh = f"{c['macd_hist']:+.3f}" if c.get("macd_hist") is not None else "   n/a"
        ath = f"{c['ath_pct']:+.0f}%" if c.get("ath_pct") is not None else "  n/a"
        vol = (c.get("total_volume") or 0) / 1_000_000

        # Funding rate inline if available
        fr = funding_rates.get(c["id"]) if funding_rates else None
        fr_str = f" [FR:{fr:+.3f}%]" if fr is not None else ""

        lines.append(
            f"{c['id']:<20} {c['current_price']:>12.4f} {pct('1h'):>7} {pct('24h'):>7} "
            f"{pct('7d'):>7} {pct('30d'):>7} {rsi:>5} {mar:>9} {bb:>6} {mh:>8} {ath:>7} {vol:>8.1f}{fr_str}"
        )

    lines.append("\nINDICATOR GUIDE:")
    lines.append("  RSI: <30=oversold, >70=overbought")
    lines.append("  MA24/168: >1.0=short-term bullish vs 7d avg")
    lines.append("  BB%B: <0.2=near lower band (oversold), >0.8=near upper band (overbought)")
    lines.append("  MACDh%: positive=bullish momentum building, negative=bearish momentum, crossing zero=signal")
    lines.append("  ATH%: distance from all-time-high")
    lines.append("  FR: funding rate per 8h — >+0.1%=overleveraged longs, <-0.05%=overleveraged shorts")

    return "\n".join(lines)
