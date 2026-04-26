"""Smoke test — verifica deps, API keys y datos de mercado. Sin LLM ni email."""
import sys

print("Comprobando dependencias...")
try:
    import openai, requests, dotenv, rich
    print("  OK — openai, requests, dotenv, rich")
except ImportError as e:
    print(f"  ERROR — {e}")
    sys.exit(1)

print("Comprobando .env y config...")
try:
    from config import XAI_API_KEY, XAI_BASE_URL, MODEL
    assert XAI_API_KEY, "XAI_API_KEY vacía"
    print(f"  OK — modelo={MODEL}")
except Exception as e:
    print(f"  ERROR — {e}")
    sys.exit(1)

print("Comprobando perfiles y portfolios...")
try:
    from profiles import PROFILES
    import portfolio as pf
    for key, profile in PROFILES.items():
        p = pf.load(profile["portfolio_file"])
        print(f"  OK — {profile['name']}: cash=€{p['cash_eur']:.2f} cycle=#{p['cycle_count']}")
except Exception as e:
    print(f"  ERROR — {e}")
    sys.exit(1)

print("Comprobando datos de mercado (CoinGecko)...")
try:
    import data as market_data
    coins = market_data.get_market_data(limit=5)
    print(f"  OK — {len(coins)} coins obtenidos, BTC=€{coins[0]['current_price']:,.0f}")
except Exception as e:
    print(f"  ERROR — {e}")
    sys.exit(1)

print("Comprobando memoria...")
try:
    import memory as mem
    for key in ["moderate", "aggressive", "degen"]:
        m = mem.load(key)
        print(f"  OK — {key}: {len(m['entries'])} entries, {len(m['summaries'])} summaries")
except Exception as e:
    print(f"  ERROR — {e}")
    sys.exit(1)

print("")
print("Todo OK. El sistema está listo.")
