import asyncio
import os
from typing import Dict, List

import ccxt.pro as ccxt
from ccxt.base.exchange import Exchange

from anxiousbot import exponential_backoff, get_logger


class ExchangeHandler:
    def __init__(self):
        self._exchanges = {}
        self._auth_exchanges = []
        self._logger = get_logger(__name__)

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

    async def setup_exchange(self, exchange_id: str) -> Exchange:
        if exchange_id in self._exchanges:
            return self._exchanges[exchange_id]

        auth = self._credentials(exchange_id)
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

        while True:
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

    def ids(self) -> List[str]:
        return list(self._exchanges.keys())

    def exchange(self, id) -> Exchange | None:
        return self._exchanges.get(id)

    def is_authenticated(self, id) -> bool:
        return id in self._auth_exchanges

    async def close_exchange(self, exchange_id: str) -> None:
        if exchange_id not in self._exchanges:
            return
        await self._exchanges.get(exchange_id).close()
        del self._exchange[exchange_id]
        self._auth_exchanges = [id for id in self._auth_exchanges if id != exchange_id]

    async def close(self):
        ids = self.ids()
        await asyncio.gather(*[self.close_exchange(id) for id in ids])
