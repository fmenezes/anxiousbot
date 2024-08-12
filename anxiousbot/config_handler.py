import json
import os
from typing import Dict

ROLE_PRIMARY = "primary"
ROLE_SECONDARY = "SECONDARY"

DEFAULT_EXIPRE_DEAL_EVENTS = "60"
DEFAULT_EXPIRE_BOOK_ORDERS = "60"
DEFAULT_CACHE_ENDPOINT = "redis://localhost"
DEFAULT_SYMBOLS = "BTC/USDT"
DEFAULT_ROLE = ROLE_PRIMARY


class ConfigHandler:
    def __init__(self):
        self._bot_token = os.getenv("BOT_TOKEN")
        bot_chat_id = os.getenv("BOT_CHAT_ID")
        try:
            self._bot_chat_id = int(bot_chat_id)
        except:
            self._bot_chat_id = None
        self._role = os.getenv("ROLE", DEFAULT_ROLE)
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
        with open("./config/parameters.json", "r") as f:
            self._parameters = json.load(f)

    @property
    def role(self):
        return self._role

    def is_primary(self):
        return self._role.lower() == ROLE_PRIMARY

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
        return self.parameters["exchanges"]

    @property
    def symbols_param(self) -> Dict:
        return self.parameters["symbols"]

    @property
    def parameters(self) -> Dict:
        return self._parameters
