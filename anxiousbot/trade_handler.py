import random
from typing import Any, Dict, List, Literal

from anxiousbot import exponential_backoff
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.exchange_handler import ExchangeHandler


class TradeException(Exception):
    pass


class TradeHandler:
    def __init__(
        self, config_handler: ConfigHandler, exchange_handler: ExchangeHandler
    ):
        self._config_handler = config_handler
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

    def valid_exchange_ids(self) -> List[str]:
        return self._exchange_handler.authenticated_ids()

    def valid_sides(self) -> List[str]:
        return ["buy", "sell"]

    def valid_coins(self) -> List[str]:
        return list(
            set(
                [
                    param["basecoin"]
                    for symbol, param in self._config_handler.symbols_param.items()
                ]
                + [
                    param["quotecoin"]
                    for symbol, param in self._config_handler.symbols_param.items()
                ]
            )
        )

    def valid_symbols(self) -> List[str]:
        return self._config_handler.symbols_param.keys()

    async def trade(
        self, exchange_id: str, symbol: str, side: Literal["buy", "sell"], volume: float
    ) -> None:
        if exchange_id not in self.valid_exchange_ids():
            raise TradeException(f"exchange {exchange_id} is not valid")
        if side not in self.valid_sides():
            raise TradeException(f"side {side} is not valid")
        if symbol not in self.valid_symbols():
            raise TradeException(f"symbol {symbol} is not valid")
        client = self._exchange_handler.exchange(exchange_id)
        if client is None:
            raise TradeException(f"exchange {exchange_id} is not available")
        await client.create_order(symbol, "market", side, volume)

    def valid_network_ids(self, coin: str, exchange_ids: List[str]) -> List[str]:
        clients = [self._exchange_handler.exchange(id) for id in exchange_ids]
        clients = [client for client in clients if client is not None]
        networks = {}
        for client in clients:
            currency = client.currencies.get(coin)
            if currency is None:
                return []
            currency_networks = list(currency.get("networks", {}).keys())
            for network in currency_networks:
                if network not in networks:
                    networks[network] = 1
                else:
                    networks[network] += 1
        return [key for key, value in networks.items() if value > 1]

    async def transfer(
        self,
        coin: str,
        volume: float,
        from_exchange_id: str,
        to_exchange_id: str,
        network: str,
    ) -> None:
        if coin not in self.valid_coins():
            raise TradeException(f"coin {coin} is not valid")
        if from_exchange_id not in self.valid_exchange_ids():
            raise TradeException(f"exchange {from_exchange_id} is not valid")
        if to_exchange_id not in self.valid_exchange_ids():
            raise TradeException(f"exchange {to_exchange_id} is not valid")
        if network not in self.valid_network_ids(
            coin, [to_exchange_id, from_exchange_id]
        ):
            raise TradeException(f"network {network} is not valid")
        from_client = self._exchange_handler.exchange(from_exchange_id)
        if from_client is None:
            raise TradeException(f"exchange {from_exchange_id} not available")
        to_client = self._exchange_handler.exchange(to_exchange_id)
        if to_client is None:
            raise TradeException(f"exchange {to_exchange_id} not available")
        try:
            address = await to_client.fetch_deposit_address(coin, {"network": network})
        except:
            address = None
        if address is None:
            address = await to_client.create_deposit_address(coin, {"network": network})
        await from_client.withdraw(
            coin,
            volume,
            address["address"],
            address["tag"],
            params={"network": network},
        )
