import asyncio
import logging
import os
import traceback
from contextlib import asynccontextmanager
from types import CoroutineType

import boto3
import ccxt.pro as ccxt
from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient
from watchtower import CloudWatchLogFormatter, CloudWatchLogHandler


class CustomFormatter(CloudWatchLogFormatter):
    def format(self, message):
        for attr in self.add_log_record_attrs:
            if not hasattr(message, attr):
                setattr(message, attr, None)
        return super().format(message)


def _get_log_handler(extra=None):
    attrs = [
        "name",
        "levelname",
        "taskName",
        "exchange",
        "duration",
        "symbol",
        "pathname",
        "lineno",
        "exc_formatted",
    ]
    if extra is not None:
        attrs += extra.keys()
    formatter = CustomFormatter(add_log_record_attrs=attrs)
    if os.getenv("LOG_HANDLER", "STDOUT") == "CLOUD_WATCH":
        handler = CloudWatchLogHandler(
            boto3_client=boto3.client("logs", region_name=os.getenv("AWS_REGION")),
            send_interval=5,
            log_group=os.getenv("LOG_GROUP_NAME"),
            stream_name=os.getenv("LOG_STREAM_NAME"),
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    return handler


def _log_record_factory(log_factory=None, extra=None):
    if log_factory is None:
        log_factory = logging.getLogRecordFactory()

    def _factory(*args, **kwargs):
        record = log_factory(*args, **kwargs)

        if isinstance(record.exc_info, BaseException):
            try:
                record.exc_formatted = "".join(
                    traceback.format_exception(record.exc_info)
                )
            except:
                pass
        if isinstance(record.exc_info, tuple):
            try:
                record.exc_formatted = "".join(
                    traceback.format_exception(record.exc_info[1])
                )
            except:
                pass

        try:
            record.taskName = asyncio.current_task().get_name()
        except Exception:
            record.taskName = None
        if extra is not None:
            for key, value in extra.items():
                setattr(record, key, value)
        return record

    return _factory


def get_logger(name=None, extra=None):
    logging.setLogRecordFactory(_log_record_factory(extra=extra))
    logger = logging.getLogger(name)
    try:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO"))
    except:
        level = logging.INFO
    logger.setLevel(level)
    handler = _get_log_handler(extra)
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
                if isinstance(e, CoroutineType):
                    last_exception = await e
                else:
                    last_exception = e
                self.logger.exception(e)
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

    async def close_exchange(self, client):
        return await client.close()

    async def close(self):
        for client in self.clients:
            self.close_exchange(client)
