import json
import os
from typing import Dict

DEFAULT_EXIPRE_DEAL_EVENTS = "60"
DEFAULT_EXPIRE_BOOK_ORDERS = "60"
DEFAULT_CACHE_ENDPOINT = "redis://localhost"
DEFAULT_SYMBOLS = "BTC/USDT"


class ConfigHandler:
    def __init__(self):
        self._bot_token = os.getenv("BOT_TOKEN")
        self._bot_chat_id = os.getenv("BOT_CHAT_ID")
        self._symbols = os.getenv("SYMBOLS", DEFAULT_SYMBOLS).split(",")
        self._cache_endpoint = os.getenv("CACHE_ENDPOINT", DEFAULT_CACHE_ENDPOINT)
        expire_book_orders = os.getenv("EXPIRE_BOOK_ORDERS", DEFAULT_EXPIRE_BOOK_ORDERS)
        try:
            self._expire_book_orders = int(expire_book_orders)
        except:
            self._expire_book_orders = int(DEFAULT_EXPIRE_BOOK_ORDERS)
        expire_deal_events = os.getenv("EXPIRE_BOOK_ORDERS", DEFAULT_EXPIRE_BOOK_ORDERS)
        try:
            self._expire_deal_events = int(expire_deal_events)
        except:
            self._expire_deal_events = int(DEFAULT_EXPIRE_BOOK_ORDERS)
        run_bot_updates = os.getenv("RUN_BOT", "1")
        self._run_bot_updates = run_bot_updates.lower() in [
            "1",
            "yes",
            "y",
            "true",
            "t",
        ]
        with open("./config/exchanges.json", "r") as f:
            self._exchanges_param = json.load(f)
        with open("./config/symbols.json", "r") as f:
            self._symbols_param = json.load(f)

    @property
    def run_bot_updates(self):
        return self._run_bot_updates

    @property
    def bot_token(self):
        return self._bot_token

    @property
    def bot_chat_id(self):
        return self._bot_chat_id

    @property
    def symbols(self):
        return self._symbols

    @property
    def expire_book_orders(self):
        return self._expire_book_orders

    @property
    def expire_deal_events(self):
        return self._expire_deal_events

    @property
    def cache_endpoint(self):
        return self._cache_endpoint

    @property
    def exchanges_param(self) -> Dict:
        return self._exchanges_param

    @property
    def symbols_param(self) -> Dict:
        return self._symbols_param
