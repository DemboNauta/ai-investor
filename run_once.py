"""Single-cycle runner — called by Windows Task Scheduler every hour."""
import sys
import traceback
import json
import os
from datetime import datetime, timezone, timedelta

from openai import OpenAI
import data as market_data
import portfolio as pf
import agent
import memory as mem
import notifier
import generate_report
import subscribers
from config import INITIAL_CAPITAL_EUR, XAI_API_KEY, XAI_BASE_URL, MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from profiles import PROFILES


def _make_client(provider: str):
    if provider == "openai":
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL), OPENAI_MODEL
    return OpenAI(api_key=XAI_API_KEY, base_url=XAI_BASE_URL), MODEL

PYTHON = r"C:\Users\edgar\AppData\Local\Programs\Python\Python310\python.exe"

_ALERT_STATE_FILE = os.path.join(os.path.dirname(__file__), "alert_state.json")
_ALERT_COOLDOWN_H = 24   # horas mínimas entre alertas urgentes
_BIG_MOVE_PCT     = 20   # cambio >= 20% en portfolio en un ciclo = alerta
_FG_EXTREME_LOW   = 15   # miedo extremo real
_FG_EXTREME_HIGH  = 85   # codicia extrema real
_BTC_CRASH_PCT    = 15   # BTC sube/baja >= 15% en 24h = alerta


def _last_alert_ts() -> datetime | None:
    if not os.path.exists(_ALERT_STATE_FILE):
        return None
    try:
        with open(_ALERT_STATE_FILE) as f:
            ts = json.load(f).get("last_alert_ts")
        return datetime.fromisoformat(ts) if ts else None
    except Exception:
        return None


def _save_alert_ts():
    with open(_ALERT_STATE_FILE, "w") as f:
        json.dump({"last_alert_ts": datetime.now(timezone.utc).isoformat()}, f)


def _maybe_send_alert(
    profile_key: str,
    profile_name: str,
    cycle: int,
    fear_greed: dict | None,
    value_before: float,
    value_after: float,
    trade_log: list,
    activity_log: list,
    pnl_pct: float,
    coins: list | None = None,
):
    # Check cooldown
    last = _last_alert_ts()
    if last:
        elapsed = datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc) if last.tzinfo is None else datetime.now(timezone.utc) - last
        if elapsed < timedelta(hours=_ALERT_COOLDOWN_H):
            return

    # Check conditions
    fg_val     = fear_greed.get("value") if fear_greed else None
    fg_label   = fear_greed.get("value_classification", "") if fear_greed else ""
    fg_extreme = fg_val is not None and (fg_val < _FG_EXTREME_LOW or fg_val > _FG_EXTREME_HIGH)

    delta_pct = abs((value_after - value_before) / value_before * 100) if value_before else 0
    big_move  = delta_pct >= _BIG_MOVE_PCT

    btc_24h = None
    btc_crash = False
    if coins:
        btc = next((c for c in coins if c["id"] == "bitcoin"), None)
        if btc:
            btc_24h = btc.get("price_change_percentage_24h_in_currency")
            if btc_24h is not None and abs(btc_24h) >= _BTC_CRASH_PCT:
                btc_crash = True

    if not (fg_extreme or big_move or btc_crash):
        return

    reasons = []
    if fg_extreme:
        direction = "Miedo extremo" if fg_val < _FG_EXTREME_LOW else "Codicia extrema"
        reasons.append(f"{direction} (F&G: {fg_val} — {fg_label})")
    if big_move:
        reasons.append(f"Portfolio: {delta_pct:.1f}% en 1 ciclo")
    if btc_crash:
        sign = "+" if btc_24h > 0 else ""
        reasons.append(f"BTC 24h: {sign}{btc_24h:.1f}%")

    reason = " · ".join(reasons)
    recipients = subscribers.get_all()
    if not recipients:
        return

    sent = notifier.notify_alert(
        profile_name=profile_name,
        cycle=cycle,
        reason=reason,
        total_eur=value_after,
        pnl_pct=pnl_pct,
        trade_log=trade_log,
        activity_log=activity_log,
        fear_greed=fear_greed,
    )
    if sent > 0:
        _save_alert_ts()
        print(f"  [alert] Alerta enviada a {sent} suscriptores: {reason}")


def main(profile_key: str = "moderate"):
    profile = PROFILES.get(profile_key)
    if not profile:
        print(f"Unknown profile '{profile_key}'. Available: {list(PROFILES.keys())}")
        sys.exit(1)

    llm_client, llm_model = _make_client(profile.get("provider", "xai"))

    print(f"[{datetime.now(timezone.utc).isoformat()}] [{profile['name']}] Cycle start")

    try:
        coins = market_data.get_market_data(limit=50)
        coins = market_data.enrich_with_indicators(coins)
        fear_greed = market_data.get_fear_greed()
        global_mkt = market_data.get_global_market()
        trending = market_data.get_trending()
        funding_rates = market_data.get_funding_rates()
        macro = market_data.get_macro_context()
    except Exception as e:
        print(f"Market data error: {e}")
        return

    prices = {c["id"]: c["current_price"] for c in coins}
    market_text = market_data.format_market_data_for_llm(
        coins, fear_greed,
        global_market=global_mkt,
        trending=trending,
        funding_rates=funding_rates,
        macro=macro,
    )

    portfolio = pf.load(profile["portfolio_file"])
    portfolio["cycle_count"] += 1
    cycle = portfolio["cycle_count"]

    # Load memory
    profile_memory = mem.load(profile_key)

    # Compute current regime for smart memory injection
    fg_val = fear_greed.get("value") if fear_greed else None
    btcd = global_mkt.get("btc_dominance") if global_mkt else None
    mcap_chg = global_mkt.get("market_cap_change_24h_pct") if global_mkt else None
    current_regime_label = mem._classify_regime(fg_val, btcd, mcap_chg)
    current_regime = {"label": current_regime_label, "fear_greed": fg_val, "btc_dominance": btcd}

    # Compute per-coin trade stats from portfolio history
    coin_stats = mem.compute_coin_stats(portfolio.get("trades", []))

    memory_prompt = mem.format_for_prompt(
        profile_memory,
        current_regime=current_regime,
        coin_stats=coin_stats,
        current_cycle=cycle,
    )
    full_system_prompt = profile["system_prompt"] + memory_prompt

    value_before = pf.get_total_value(portfolio, prices)

    print(f"Running agent (cycle #{cycle}, regime={current_regime_label})...")
    try:
        portfolio, trade_log, summary, activity_log, in_cycle_memories = agent.run_cycle(
            portfolio, market_text, prices, system_prompt=full_system_prompt, mem=profile_memory,
            llm_client=llm_client, llm_model=llm_model,
        )
    except Exception as e:
        traceback.print_exc()
        trade_log, summary, activity_log, in_cycle_memories = [], f"Agent error: {e}", [], []

    portfolio["last_run"] = datetime.now(timezone.utc).isoformat()
    pf.save(portfolio, profile["portfolio_file"])

    value_after = pf.get_total_value(portfolio, prices)
    pnl = value_after - INITIAL_CAPITAL_EUR
    pnl_pct = (pnl / INITIAL_CAPITAL_EUR) * 100

    # Append to history for chart
    import json as _json, os as _os
    _hist_file = f"history_{profile_key}.json"
    _hist = _json.load(open(_hist_file)) if _os.path.exists(_hist_file) else []
    _hist.append({"ts": portfolio["last_run"], "cycle": cycle, "value": round(value_after, 2)})
    with open(_hist_file, "w") as _f:
        _json.dump(_hist, _f)

    print(f"Total: €{value_after:.2f} | P&L: €{pnl:+.2f} ({pnl_pct:+.1f}%)")
    for t in trade_log:
        print(f"  {t}")
    if summary:
        print(f"Agent: {summary}")

    # Save in-cycle memories (logged during trading) — tagged with current regime
    for m in in_cycle_memories:
        mem.add_entry(
            profile_memory, m["content"], m["category"], cycle, m["importance"],
            regime=current_regime_label, fear_greed=fg_val, btc_dominance=btcd,
        )
    if in_cycle_memories:
        print(f"  [{profile['name']}] {len(in_cycle_memories)} in-cycle memory/memories saved")

    # Post-cycle reflection
    print(f"  [{profile['name']}] Running post-cycle reflection...")
    try:
        reflection_memories, reflection_thesis = agent.run_reflection(
            profile_name=profile["name"],
            system_prompt=profile["system_prompt"],
            cycle=cycle,
            trade_log=trade_log,
            summary=summary,
            value_before=value_before,
            value_after=value_after,
            memory_prompt=memory_prompt,
            llm_client=llm_client,
            llm_model=llm_model,
        )
        delta_pct = ((value_after - value_before) / value_before * 100) if value_before else 0
        for m in reflection_memories:
            mem.add_entry(
                profile_memory, m["content"], m["category"], cycle,
                m["importance"], pnl_pct=delta_pct,
                regime=current_regime_label, fear_greed=fg_val, btc_dominance=btcd,
            )
        if reflection_thesis:
            mem.update_thesis(profile_memory, reflection_thesis)
            print(f"  [{profile['name']}] Thesis updated: {reflection_thesis[:80]}")
        if reflection_memories:
            print(f"  [{profile['name']}] {len(reflection_memories)} reflection memory/memories saved")
    except Exception as e:
        print(f"  [{profile['name']}] Reflection error: {e}")

    profile_memory["cycles_reflected"] = profile_memory.get("cycles_reflected", 0) + 1

    # Summarization when raw entries exceed threshold
    if mem.needs_summarization(profile_memory):
        print(f"  [{profile['name']}] Memory full — running summarization...")
        try:
            raw_text = mem.format_raw_for_summarization(profile_memory)
            summaries = agent.run_summarization(
                profile_name=profile["name"],
                system_prompt=profile["system_prompt"],
                raw_entries_text=raw_text,
                llm_client=llm_client,
                llm_model=llm_model,
            )
            mem.prune_after_summarization(profile_memory)
            for s in summaries:
                mem.add_summary(profile_memory, s["content"], cycle)
            print(f"  [{profile['name']}] Summarized into {len(summaries)} core lessons")
        except Exception as e:
            print(f"  [{profile['name']}] Summarization error: {e}")

    mem.save(profile_key, profile_memory, profile_name=profile["name"])

    try:
        generate_report.generate(prices=prices)
    except Exception as e:
        print(f"  [report] Error: {e}")

    try:
        _maybe_send_alert(
            profile_key=profile_key,
            profile_name=profile["name"],
            cycle=cycle,
            fear_greed=fear_greed,
            value_before=value_before,
            value_after=value_after,
            trade_log=trade_log,
            activity_log=activity_log,
            pnl_pct=pnl_pct,
            coins=coins,
        )
    except Exception as e:
        print(f"  [alert] Error: {e}")

    try:
        import bluesky_bot
        bluesky_bot.maybe_post_cycle(
            profile_key=profile_key,
            activity_log=activity_log,
            total_eur=value_after,
            pnl_pct=pnl_pct,
            summary=summary,
        )
    except Exception as e:
        print(f"  [bluesky] Error: {e}")

    print("Done.")


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "all"
    if key == "all":
        for k in PROFILES:
            main(k)
    else:
        main(key)
