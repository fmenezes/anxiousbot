import asyncio
import os
from typing import Dict, List

import ccxt.pro as ccxt
from ccxt.async_support.base.exchange import Exchange

from anxiousbot import exponential_backoff
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.log import get_logger


class ExchangeHandler:
    def __init__(self, config_handler: ConfigHandler):
        self._exchanges = {}
        self._auth_exchanges = []
        self._logger = get_logger(__name__)
        self._loop = True
        self._config_handler = config_handler

    def _credentials(self, exchange_id: str) -> Dict[str, str] | None:
        auth_keys = [
            "apiKey",
            "secret",
            "uid",
            "accountId",
            "login",
            "password",
            "twofa",
            "privateKey",
            "walletAddress",
            "token",
        ]
        auth = dict(
            [
                (key, os.getenv(f"{exchange_id.upper()}_{key.upper()}"))
                for key in auth_keys
            ]
        )
        auth = dict(
            [
                (key, value.replace("\\n", "\n"))
                for key, value in auth.items()
                if value is not None
            ]
        )

        if len(auth.keys()) == 0:
            return None

        return auth

    async def setup_available_exchanges(self) -> List[Exchange]:
        tasks = [
            asyncio.create_task(
                self.setup_exchange(id),
                name=f"setup_exchange_{id}",
            )
            for id in self.available_ids()
        ]
        return await asyncio.gather(*tasks)

    async def setup_loggedin_exchanges(self) -> List[Exchange]:
        tasks = [
            asyncio.create_task(
                self.setup_exchange(id),
                name=f"setup_exchange_{id}",
            )
            for id in self.authenticated_ids()
        ]
        return await asyncio.gather(*tasks)

    async def setup_exchange(self, exchange_id: str) -> Exchange:
        if exchange_id in self._exchanges:
            return self._exchanges[exchange_id]

        if self._config_handler.is_primary():
            auth = self._credentials(exchange_id)
        else:
            auth = None
        client_cls = getattr(ccxt, exchange_id)
        if auth is not None:
            client = client_cls(auth)
            self._auth_exchanges += [client.id]
            self._logger.debug(
                f"{exchange_id} logged in",
                extra={"exchange": exchange_id},
            )
        else:
            client = client_cls()

        while self._loop:
            try:
                await exponential_backoff(client.load_markets)
                self._logger.info(
                    f"{exchange_id} loaded markets",
                    extra={"exchange": exchange_id},
                )
                break
            except Exception as e:
                self._logger.exception(e, extra={"exchange": exchange_id})
                await client.close()
                await asyncio.sleep(1)

        self._exchanges[client.id] = client
        return client

    def exchanges(self) -> List[Exchange]:
        return list(self._exchanges.values())

    def initialized_ids(self) -> List[str]:
        return list(self._exchanges.keys())

    def available_ids(self) -> List[str]:
        return list(
            set(
                [
                    exchange
                    for symbol in self._config_handler.symbols
                    for exchange in self._config_handler.symbols_param[symbol][
                        "exchanges"
                    ]
                ]
            )
        )

    def all_ids(self) -> List[str]:
        ids = [
            id
            for id in ccxt.exchanges
            if not getattr(ccxt, id)().describe().get("alias", False)
        ]
        return ids

    def authenticated_ids(self) -> List[str]:
        ids = [id for id in self.all_ids() if self._credentials(id) is not None]
        return ids

    def exchange(self, id: str) -> Exchange | None:
        return self._exchanges.get(id)

    def is_authenticated(self, id: str) -> bool:
        return id in self._auth_exchanges

    async def close_exchange(self, exchange_id: str) -> None:
        if exchange_id not in self._exchanges:
            return
        await self._exchanges.get(exchange_id).close()
        del self._exchanges[exchange_id]
        self._auth_exchanges = [id for id in self._auth_exchanges if id != exchange_id]

    async def aclose(self):
        self._loop = False
        ids = self.initialized_ids()
        await asyncio.gather(*[self.close_exchange(id) for id in ids])
