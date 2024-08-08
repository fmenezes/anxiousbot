from typing import Dict, Literal

from anxiousbot import exponential_backoff
from anxiousbot.exchange_handler import ExchangeHandler


class TradeHandler:
    def __init__(self, exchange_handler: ExchangeHandler):
        self._exchange_handler = exchange_handler

    async def fetch_balance(self) -> Dict:
        balances = {}
        for exchange_id in self._exchange_handler.initialized_ids():
            if not self._exchange_handler.is_authenticated(exchange_id):
                balances[exchange_id] = {"status": "NOT_AUTH"}
                continue
            try:
                balance = await exponential_backoff(
                    self._exchange_handler.exchange(exchange_id).fetch_balance
                )
                balances[exchange_id] = {"status": "OK", "balance": balance}
            except Exception as e:
                balances[exchange_id] = {"status": "ERROR", "exception": e}

        return balances

    async def trade(
        self, exchange_id: str, symbol: str, side: Literal["buy", "sell"], volume: float
    ) -> None:
        client = self._exchange_handler.exchange(exchange_id)
        if client is None:
            raise RuntimeError(f"exchange {exchange_id} not available")
        await client.create_order(symbol, "market", side, volume)

    async def transfer(
        self,
        coin: str,
        volume: float,
        from_exchange_id: str,
        to_exchange_id: str,
        network: str,
    ) -> None:
        from_client = self._exchange_handler.exchange(from_exchange_id)
        if from_client is None:
            raise RuntimeError(f"exchange {from_exchange_id} not available")
        to_client = self._exchange_handler.exchange(to_exchange_id)
        if to_client is None:
            raise RuntimeError(f"exchange {to_exchange_id} not available")
        address = await to_client.fetch_deposit_address(coin, {"network": network})
        await from_client.withdraw(
            coin, volume, address["address"], params={"network": network}
        )
