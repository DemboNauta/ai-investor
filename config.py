import os
from dotenv import load_dotenv

load_dotenv()

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_BASE_URL = "https://api.x.ai/v1"
MODEL = os.getenv("GROK_MODEL", "grok-3")

INITIAL_CAPITAL_EUR = 1000.0
CYCLE_INTERVAL_HOURS = float(os.getenv("CYCLE_INTERVAL_HOURS", "1"))
TOP_COINS_LIMIT = 50
MIN_TRADE_EUR = 5.0
