import asyncio
from types import CoroutineType
from typing import Any, Callable, Dict, List, Tuple, TypeVar

from ccxt.base.errors import RateLimitExceeded
from telegram.error import RetryAfter


def split_coin(symbol: str) -> List[str]:
    return symbol.split("/")


R = TypeVar("R")


async def exponential_backoff(
    fn: Callable[..., R], *args: Tuple, **kwargs: Dict[str, Any]
) -> R:
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
