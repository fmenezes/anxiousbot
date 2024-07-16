import asyncio
import os
from contextlib import asynccontextmanager

import ccxt.pro as ccxt
from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient

from anxiousbot.log import get_logger


@asynccontextmanager
async def closing(thing):
    try:
        yield thing
    finally:
        await thing.close()


class App:
    def __init__(self, logger=None, memcache_client=None):
        if logger is not None:
            self.logger = logger
        else:
            self.logger = get_logger()
        if memcache_client is not None:
            self.memcache_client = memcache_client
        else:
            self.memcache_client = MemcacheClient("localhost", serde=serde.pickle_serde)
        self.clients = []

    async def exponential_backoff(self, fn, *args, **kwargs):
        backoff = [1, 2, 4, 8]
        last_exception = None
        for delay in backoff:
            try:
                return await fn(*args, **kwargs)
            except asyncio.CancelledError as e:
                raise e
            except Exception as e:
                await asyncio.sleep(delay)
                last_exception = e
        raise last_exception

    def _convert_exchange_id_for_auth(self, id):
        data = {
            "coinbaseexchange": "coinbase",
            "coinbaseinternational": "coinbase",
            "binanceusdm": "binance",
            "binancecoinm": "binance",
        }

        if id in data:
            return data[id]

        if id.endswith("futures"):
            return id.removesuffix("futures")

        return id

    async def setup_exchange(self, exchange_id, required_markets=False):
        env_exchange_id = self._convert_exchange_id_for_auth(exchange_id).upper()
        api_key = os.getenv(f"{env_exchange_id}_API_KEY")
        secret = os.getenv(f"{env_exchange_id}_SECRET")
        passphrase = os.getenv(f"{env_exchange_id}_PASSPHRASE")
        auth = None
        if api_key is not None or secret is not None or passphrase is not None:
            auth = {
                "apiKey": api_key,
                "secret": secret,
                "passphrase": passphrase,
            }
        client_cls = getattr(ccxt, exchange_id)
        if auth is not None:
            client = client_cls(auth)
            self.logger.debug(
                f"{exchange_id} logged in",
                extra={"exchange": exchange_id},
            )
        else:
            client = client_cls()

        try:
            await self.exponential_backoff(client.load_markets)
            self.logger.info(
                f"{exchange_id} loaded markets",
                extra={"exchange": exchange_id},
            )
        except Exception as e:
            self.logger.exception(e, extra={"exchange": exchange_id})
            if required_markets:
                await client.close()
                raise e

        self.clients.append(client)
        return client

    async def close(self):
        for client in self.clients:
            await client.close()
