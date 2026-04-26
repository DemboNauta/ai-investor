import json
from openai import OpenAI
from config import XAI_API_KEY, XAI_BASE_URL, MODEL, MIN_TRADE_EUR
import portfolio as pf

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
""".format(min_trade=MIN_TRADE_EUR)

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
]

REFLECTION_TOOLS = [_REMEMBER_TOOL, _DONE_REFLECTING_TOOL]


def run_cycle(
    portfolio: dict,
    market_text: str,
    prices: dict[str, float],
    system_prompt: str = None,
) -> tuple[dict, list[str], str, list[dict], list[dict]]:
    """Run one trading cycle. Returns updated portfolio, trade log, agent summary, activity log, in-cycle memories."""
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
        response = client.chat.completions.create(
            model=MODEL,
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

            elif fn == "remember":
                in_cycle_memories.append({
                    "content": args["content"],
                    "category": args["category"],
                    "importance": args.get("importance", 2),
                })
                result = "Memory saved."
                activity_log.append({"tool": "remember", "args": args, "result": result, "status": "ok"})

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
) -> list[dict]:
    """Post-cycle reflection. LLM sees results and writes memories. Returns new memory entries."""
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
Call done_reflecting() when finished."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    new_memories = []
    max_iterations = 10

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=MODEL,
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

    return new_memories


def run_summarization(profile_name: str, system_prompt: str, raw_entries_text: str) -> list[dict]:
    """Distill many raw memories into summary entries. Returns new summary memory entries."""
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
        response = client.chat.completions.create(
            model=MODEL,
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
