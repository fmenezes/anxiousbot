import asyncio
from contextlib import asynccontextmanager
from types import CoroutineType

from ccxt.base.errors import RateLimitExceeded
from telegram.error import RetryAfter


def split_coin(symbol):
    return symbol.split("/")


@asynccontextmanager
async def closing(thing):
    try:
        yield thing
    finally:
        await thing.close()


async def exponential_backoff(fn, *args, **kwargs):
    backoff = [1, 2, 4, 8]
    last_e = None
    for delay in backoff:
        try:
            return await fn(*args, **kwargs)
        except asyncio.CancelledError as e:
            raise e
        except RateLimitExceeded as e:
            await asyncio.sleep(60)
            last_e = e
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            last_e = e
        except Exception as e:
            await asyncio.sleep(delay)
            if isinstance(e, CoroutineType):
                return await e
            last_e = e
    raise last_e
