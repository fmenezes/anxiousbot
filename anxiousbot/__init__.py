import asyncio
import logging
import os
from contextlib import asynccontextmanager

import ccxt.pro as ccxt
from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient
from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def __init__(self, extra=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._extra = extra

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["levelname"] = record.levelname
        if self._extra is not None:
            for key, value in self._extra.items():
                log_record[key] = value


def get_logger(name=None, extra=None):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    if extra is None:
        extra = {}
    formatter = CustomJsonFormatter(
        timestamp=True, extra={"pid": os.getpid(), "app": name, **extra}
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def split_coin(symbol):
    return symbol.split("/")


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

    async def setup_exchange(self, exchange_id, required_markets=False):
        api_key = os.getenv(f"{exchange_id.upper()}_API_KEY")
        secret = os.getenv(f"{exchange_id.upper()}_SECRET")
        passphrase = os.getenv(f"{exchange_id.upper()}_PASSPHRASE")
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
