from typing import Dict

from anxiousbot import exponential_backoff
from anxiousbot.exchange_handler import ExchangeHandler


class TraderHandler:
    def __init__(self, exchange_handler: ExchangeHandler):
        self._exchange_handler = exchange_handler

    async def fetch_balance(self) -> Dict:
        balances = {}
        for exchange_id in self._exchange_handler.ids():
            if not self._exchange_handler.is_authenticated(exchange_id):
                balances[exchange_id] = {"status": "NOT_AUTH"}
                continue
            if exchange_id not in self._exchange_handler.ids():
                balances[exchange_id] = {"status": "NOT_INIT"}
                continue
            try:
                balance = await exponential_backoff(
                    self._exchange_handler.exchange(exchange_id).fetch_balance
                )
                balances[exchange_id] = {"status": "OK", "balance": balance}
            except Exception as e:
                balances[exchange_id] = {"status": "ERROR", "exception": e}

        return balances
