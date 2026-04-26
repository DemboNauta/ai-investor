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
    }
]


def run_cycle(portfolio: dict, market_text: str, prices: dict[str, float], system_prompt: str = None) -> tuple[dict, list[str], str]:
    """Run one trading cycle. Returns updated portfolio, trade log, agent summary."""
    portfolio_text = pf.format_portfolio_for_llm(portfolio, prices)
    user_msg = f"{portfolio_text}\n\n{market_text}\n\nAnalyze the market and execute trades. Call done() when finished."

    active_prompt = system_prompt or SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": active_prompt},
        {"role": "user", "content": user_msg},
    ]

    trade_log = []
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

            elif fn == "buy":
                coin_id = args["coin_id"]
                amount_eur = float(args["amount_eur"])
                reasoning = args.get("reasoning", "")
                price = prices.get(coin_id)

                if price is None:
                    result = f"ERROR: unknown coin '{coin_id}' — not in market data"
                elif amount_eur < MIN_TRADE_EUR:
                    result = f"ERROR: minimum trade is €{MIN_TRADE_EUR}"
                else:
                    ok, msg_str = pf.buy(portfolio, coin_id, amount_eur, price)
                    result = msg_str
                    if ok:
                        trade_log.append(f"BUY  {coin_id:<15} €{amount_eur:.2f} — {reasoning}")

            elif fn == "sell":
                coin_id = args["coin_id"]
                amount_eur = float(args["amount_eur"])
                reasoning = args.get("reasoning", "")
                price = prices.get(coin_id)

                if price is None:
                    result = f"ERROR: unknown coin '{coin_id}'"
                else:
                    ok, msg_str = pf.sell(portfolio, coin_id, amount_eur, price)
                    result = msg_str
                    if ok:
                        trade_log.append(f"SELL {coin_id:<15} €{amount_eur:.2f} — {reasoning}")

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

    return portfolio, trade_log, summary
