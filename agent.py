import json
from openai import OpenAI
from config import XAI_API_KEY, XAI_BASE_URL, MODEL, MIN_TRADE_EUR
import portfolio as pf
import data as market_data

client = OpenAI(api_key=XAI_API_KEY, base_url=XAI_BASE_URL)

SYSTEM_PROMPT = """You are an autonomous crypto trading agent managing a paper trading portfolio.

OBJECTIVE: Maximize total EUR returns. No restrictions — trade any coin you see fit.

RULES:
- You receive live market data every hour and decide what trades to execute.
- Call buy/sell tools to execute trades. Call done() when finished for this cycle.
- You can make multiple trades per cycle.
- Minimum trade size: €{min_trade} EUR.
- Think about: momentum, trend reversals, diversification, position sizing, risk/reward.
- Consider macro context: is market bullish/bearish? Adjust accordingly.
- You may hold all cash if no good opportunity exists.
- No leverage, no shorts — long positions only in this paper simulation.

STRATEGY TIPS:
- Don't FOMO — check 1h, 24h, 7d, 30d trends together.
- Volume confirms moves. Low-vol pumps often fake.
- Diversify: don't put everything in one coin.
- Cut losers early, let winners run.
- Alt coins = higher risk/reward than BTC/ETH.

USING ENRICHED CONTEXT:
- MACRO: DXY rising = headwind for crypto. SPY falling = risk-off, reduce exposure.
- GLOBAL MARKET: Market cap falling >1% (RISK-OFF) = reduce exposure. Rising >1% (RISK-ON) = more aggressive.
- BTC DOMINANCE: >55% = prefer BTC/ETH over alts. <45% = alt season, alts can outperform.
- TRENDING: Trending coins often see volume spikes in 12-24h. Check if tradeable, assess entry carefully.
- FUNDING RATES (FR): >+0.1%/8h = longs overextended, dump likely. <-0.05% = shorts overextended, squeeze likely. Near 0 = healthy.
- BB%B: <0.2 = price near lower band (potential buy). >0.8 = near upper band (potential sell/avoid).
- MACDh%: Positive and rising = momentum building. Negative and falling = momentum dying. Zero cross = trend change signal.

TOOLS AVAILABLE:
- fetch_news([keyword]): Get latest crypto headlines. Call before big trades or when uncertain about macro.
- get_coin_details(coin_id): Deep due diligence — dev activity, community, exchange listings. Use before large positions.
""".format(min_trade=MIN_TRADE_EUR)

_UPDATE_THESIS_TOOL = {
    "type": "function",
    "function": {
        "name": "update_thesis",
        "description": (
            "Update your persistent market thesis — your current macro view that carries over to the next cycle. "
            "Call this when your market outlook changes meaningfully. Be concise and specific: "
            "include regime (bull/bear/sideways), key levels, and what you expect next."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thesis": {
                    "type": "string",
                    "description": "Your updated market thesis (1-3 sentences max)."
                }
            },
            "required": ["thesis"]
        }
    }
}

_FETCH_NEWS_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_news",
        "description": (
            "Fetch recent crypto news headlines from Coindesk and Cointelegraph. "
            "Call this when you want to check sentiment, find catalysts, or assess risk before trading. "
            "Optionally filter by keyword (e.g. 'bitcoin', 'ethereum', 'regulation', 'ETF')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filter_keyword": {
                    "type": "string",
                    "description": "Optional keyword to filter headlines (case-insensitive). Leave empty for all news."
                }
            },
            "required": []
        }
    }
}

_GET_COIN_DETAILS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_coin_details",
        "description": (
            "Get detailed on-chain and market data for a specific coin: developer activity, "
            "community stats, exchange listings, description, categories, and more. "
            "Use before a large trade when you want deeper due diligence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "coin_id": {
                    "type": "string",
                    "description": "CoinGecko coin ID (e.g. 'bitcoin', 'ethereum', 'solana')."
                }
            },
            "required": ["coin_id"]
        }
    }
}

_REMEMBER_TOOL = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": (
            "Save an insight, lesson, error, or market pattern to your permanent memory. "
            "Use during trading when you notice something worth keeping for future cycles."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The insight, lesson, error, or pattern to remember."
                },
                "category": {
                    "type": "string",
                    "enum": ["insight", "error", "strategy", "market_pattern", "lesson"],
                    "description": (
                        "insight=market observation, error=mistake to avoid, "
                        "strategy=approach that works/fails, market_pattern=recurring pattern, "
                        "lesson=general learning."
                    )
                },
                "importance": {
                    "type": "integer",
                    "description": "1=minor, 2=useful, 3=critical",
                    "minimum": 1,
                    "maximum": 3
                }
            },
            "required": ["content", "category", "importance"]
        }
    }
}

_DONE_REFLECTING_TOOL = {
    "type": "function",
    "function": {
        "name": "done_reflecting",
        "description": "Signal that you are done reflecting for this cycle.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buy",
            "description": "Buy a cryptocurrency using EUR from cash balance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin_id": {
                        "type": "string",
                        "description": "CoinGecko coin ID (e.g. 'bitcoin', 'ethereum', 'solana'). Must match the ID in market data."
                    },
                    "amount_eur": {
                        "type": "number",
                        "description": "Amount in EUR to spend on this coin."
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief reason for this trade (logged for review)."
                    }
                },
                "required": ["coin_id", "amount_eur", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sell",
            "description": "Sell a cryptocurrency position for EUR. Use amount_eur=-1 to sell entire position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin_id": {
                        "type": "string",
                        "description": "CoinGecko coin ID to sell."
                    },
                    "amount_eur": {
                        "type": "number",
                        "description": "EUR value to sell. Use -1 to sell entire position."
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief reason for this trade (logged for review)."
                    }
                },
                "required": ["coin_id", "amount_eur", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal that you are done trading for this cycle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of decisions made this cycle and market outlook."
                    }
                },
                "required": ["summary"]
            }
        }
    },
    _REMEMBER_TOOL,
    _FETCH_NEWS_TOOL,
    _GET_COIN_DETAILS_TOOL,
    _UPDATE_THESIS_TOOL,
]

REFLECTION_TOOLS = [_REMEMBER_TOOL, _UPDATE_THESIS_TOOL, _DONE_REFLECTING_TOOL]


def run_cycle(
    portfolio: dict,
    market_text: str,
    prices: dict[str, float],
    system_prompt: str = None,
    mem: dict = None,
    llm_client=None,
    llm_model: str = None,
) -> tuple[dict, list[str], str, list[dict], list[dict]]:
    """Run one trading cycle. Returns updated portfolio, trade log, agent summary, activity log, in-cycle memories."""
    _client = llm_client or client
    _model = llm_model or MODEL

    portfolio_text = pf.format_portfolio_for_llm(portfolio, prices)
    user_msg = f"{portfolio_text}\n\n{market_text}\n\nAnalyze the market and execute trades. Call done() when finished."

    active_prompt = system_prompt or SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": active_prompt},
        {"role": "user", "content": user_msg},
    ]

    trade_log = []
    activity_log = []
    in_cycle_memories = []
    summary = ""
    max_iterations = 20

    for _ in range(max_iterations):
        response = _client.chat.completions.create(
            model=_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            break

        tool_results = []
        finished = False

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            fn = tc.function.name

            if fn == "done":
                summary = args.get("summary", "")
                finished = True
                result = "Cycle complete."
                activity_log.append({"tool": "done", "args": args, "result": result, "status": "ok"})

            elif fn == "buy":
                coin_id = args["coin_id"]
                amount_eur = float(args["amount_eur"])
                reasoning = args.get("reasoning", "")
                price = prices.get(coin_id)

                if price is None:
                    result = f"ERROR: unknown coin '{coin_id}' — not in market data"
                    status = "error"
                elif amount_eur < MIN_TRADE_EUR:
                    result = f"ERROR: minimum trade is €{MIN_TRADE_EUR}"
                    status = "error"
                else:
                    ok, result = pf.buy(portfolio, coin_id, amount_eur, price)
                    status = "ok" if ok else "error"
                    if ok:
                        trade_log.append(f"BUY  {coin_id:<15} €{amount_eur:.2f} — {reasoning}")

                activity_log.append({
                    "tool": "buy",
                    "coin_id": coin_id,
                    "amount_eur": amount_eur,
                    "price": price,
                    "reasoning": reasoning,
                    "result": result,
                    "status": status,
                })

            elif fn == "sell":
                coin_id = args["coin_id"]
                amount_eur = float(args["amount_eur"])
                reasoning = args.get("reasoning", "")
                price = prices.get(coin_id)

                if price is None:
                    result = f"ERROR: unknown coin '{coin_id}'"
                    status = "error"
                else:
                    ok, result = pf.sell(portfolio, coin_id, amount_eur, price)
                    status = "ok" if ok else "error"
                    if ok:
                        trade_log.append(f"SELL {coin_id:<15} €{amount_eur:.2f} — {reasoning}")

                activity_log.append({
                    "tool": "sell",
                    "coin_id": coin_id,
                    "amount_eur": amount_eur,
                    "price": price,
                    "reasoning": reasoning,
                    "result": result,
                    "status": status,
                })

            elif fn == "update_thesis":
                thesis = args.get("thesis", "").strip()
                if mem is not None:
                    import memory as _mem
                    _mem.update_thesis(mem, thesis)
                result = f"Thesis updated: {thesis}"
                activity_log.append({"tool": "update_thesis", "args": args, "result": result, "status": "ok"})

            elif fn == "remember":
                in_cycle_memories.append({
                    "content": args["content"],
                    "category": args["category"],
                    "importance": args.get("importance", 2),
                })
                result = "Memory saved."
                activity_log.append({"tool": "remember", "args": args, "result": result, "status": "ok"})

            elif fn == "fetch_news":
                keyword = args.get("filter_keyword", "").strip().lower()
                headlines = market_data.get_crypto_news(max_items=15)
                if keyword:
                    headlines = [h for h in headlines if keyword in h.lower()]
                if headlines:
                    result = "RECENT NEWS:\n" + "\n".join(f"• {h}" for h in headlines)
                else:
                    result = f"No news found{' for keyword: ' + keyword if keyword else ''}."
                activity_log.append({"tool": "fetch_news", "args": args, "result": f"{len(headlines)} headlines", "status": "ok"})

            elif fn == "get_coin_details":
                coin_id = args["coin_id"]
                try:
                    import requests as _req
                    resp = _req.get(
                        f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                        params={"localization": "false", "tickers": "false", "community_data": "true", "developer_data": "true"},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    d = resp.json()
                    desc = (d.get("description", {}).get("en") or "")[:400].replace("\r\n", " ")
                    cats = ", ".join((d.get("categories") or [])[:5])
                    dev = d.get("developer_data", {})
                    comm = d.get("community_data", {})
                    result = (
                        f"COIN: {d.get('name')} ({d.get('symbol', '').upper()})\n"
                        f"Description: {desc}...\n"
                        f"Categories: {cats}\n"
                        f"GitHub stars: {dev.get('stars', 'n/a')} | Forks: {dev.get('forks', 'n/a')} | "
                        f"Commits 4w: {dev.get('commit_count_4_weeks', 'n/a')}\n"
                        f"Twitter followers: {comm.get('twitter_followers', 'n/a')} | "
                        f"Reddit subscribers: {comm.get('reddit_subscribers', 'n/a')}\n"
                        f"Exchange listings: {len(d.get('tickers') or [])}"
                    )
                    activity_log.append({"tool": "get_coin_details", "coin_id": coin_id, "result": "ok", "status": "ok"})
                except Exception as e:
                    result = f"ERROR fetching details for '{coin_id}': {e}"
                    activity_log.append({"tool": "get_coin_details", "coin_id": coin_id, "result": result, "status": "error"})

            else:
                result = f"unknown tool: {fn}"
                activity_log.append({"tool": fn, "args": args, "result": result, "status": "error"})

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        messages.extend(tool_results)

        if finished:
            break

    return portfolio, trade_log, summary, activity_log, in_cycle_memories


def run_reflection(
    profile_name: str,
    system_prompt: str,
    cycle: int,
    trade_log: list[str],
    summary: str,
    value_before: float,
    value_after: float,
    memory_prompt: str,
    llm_client=None,
    llm_model: str = None,
) -> tuple[list[dict], str]:
    """Post-cycle reflection. LLM sees results and writes memories. Returns (new memory entries, updated thesis)."""
    _client = llm_client or client
    _model = llm_model or MODEL

    delta = value_after - value_before
    delta_pct = (delta / value_before * 100) if value_before else 0
    trades_str = "\n".join(trade_log) if trade_log else "No trades this cycle."

    user_msg = f"""You just completed trading cycle #{cycle} as the {profile_name} agent.

CYCLE RESULTS:
Trades executed:
{trades_str}

Your summary: {summary or "(none)"}
Portfolio value: €{value_before:.2f} → €{value_after:.2f} ({delta:+.2f} EUR, {delta_pct:+.1f}%)

YOUR EXISTING KNOWLEDGE:
{memory_prompt or "(no prior memories yet)"}

Reflect on this cycle. Call remember() for insights worth keeping:
- Patterns you noticed in the market
- Mistakes made or narrowly avoided
- Strategy refinements based on what happened
- Whether your prior knowledge held up

Be selective — 1-4 memories per cycle is enough. Only save genuinely useful insights.
Also call update_thesis() every cycle to record your current macro view (bull/bear/sideways, key levels, what you expect next).
Call done_reflecting() when finished."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    new_memories = []
    new_thesis = ""
    max_iterations = 10

    for _ in range(max_iterations):
        response = _client.chat.completions.create(
            model=_model,
            messages=messages,
            tools=REFLECTION_TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            break

        tool_results = []
        finished = False

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            fn = tc.function.name

            if fn == "remember":
                new_memories.append({
                    "content": args["content"],
                    "category": args["category"],
                    "importance": args.get("importance", 2),
                })
                result = "Memory saved."

            elif fn == "update_thesis":
                new_thesis = args.get("thesis", "").strip()
                result = "Thesis updated."

            elif fn == "done_reflecting":
                finished = True
                result = "Reflection complete."

            else:
                result = f"unknown tool: {fn}"

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        messages.extend(tool_results)

        if finished:
            break

    return new_memories, new_thesis


def run_summarization(profile_name: str, system_prompt: str, raw_entries_text: str, llm_client=None, llm_model: str = None) -> list[dict]:
    """Distill many raw memories into summary entries. Returns new summary memory entries."""
    _client = llm_client or client
    _model = llm_model or MODEL

    user_msg = f"""You are the {profile_name} agent. Your memory log has grown large and needs compressing.

Below are your raw trading memories. Distill the most important patterns, lessons, and errors into 5-8 high-value summaries.
Use remember(category="summary", importance=3) for each summary. Make each one dense and actionable.
Skip redundant or low-value entries. Prioritize: recurring patterns, critical errors, strategy principles that held up.

RAW MEMORIES:
{raw_entries_text}

Call done_reflecting() when done writing summaries."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    summaries = []
    max_iterations = 15

    for _ in range(max_iterations):
        response = _client.chat.completions.create(
            model=_model,
            messages=messages,
            tools=REFLECTION_TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            break

        tool_results = []
        finished = False

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            fn = tc.function.name

            if fn == "remember":
                summaries.append({
                    "content": args["content"],
                    "category": "summary",
                    "importance": 3,
                })
                result = "Summary saved."

            elif fn == "done_reflecting":
                finished = True
                result = "Summarization complete."

            else:
                result = f"unknown tool: {fn}"

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        messages.extend(tool_results)

        if finished:
            break

    return summaries
