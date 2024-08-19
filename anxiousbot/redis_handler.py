import json
from datetime import datetime
from typing import Any, Dict

from redis.asyncio import Redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError
from redis.retry import Retry

from anxiousbot.config_handler import ConfigHandler


class RedisHandler:
    def __init__(self, config_handler: ConfigHandler):
        self._config_handler = config_handler
        self._redis_client = Redis.from_url(
            self._config_handler.cache_endpoint,
            retry=Retry(ExponentialBackoff(cap=10, base=1), 25),
            retry_on_error=[ConnectionError, TimeoutError, ConnectionResetError],
            health_check_interval=1,
        )

    async def _get(self, key: str, default: Any = None) -> Any:
        result = await self._redis_client.get(key)
        if result is None:
            return default
        return json.loads(result)

    async def _set(self, key: str, value: Any, *args, **kwargs) -> None:
        await self._redis_client.set(key, json.dumps(value), *args, **kwargs)

    async def get_deal(
        self, symbol: str, buy_exchange_id: str, sell_exchange_id: str
    ) -> Dict:
        return await self._get(
            f"/deal/{symbol}/{buy_exchange_id}/{sell_exchange_id}"
        ) or {"ts_open": str(datetime.now()), "type": "noop", "threshold": False}

    async def set_deal(
        self, symbol: str, buy_exchange_id: str, sell_exchange_id: str, value: Dict
    ) -> None:
        await self._set(
            f"/deal/{symbol}/{buy_exchange_id}/{sell_exchange_id}",
            value,
            ex=self._config_handler.expire_deal_events,
        )

    async def get_trio_deal_event(self, event: Dict) -> Dict:
        key = "/trio_deal/" + "/".join(
            [
                f"{operation["exchange"]}_{operation["side"]}_{operation["symbol"]}"
                for operation in event["operations"]
            ]
        )
        return await self._get(key) or {
            "ts_open": str(datetime.now()),
            "type": "noop",
            "threshold": False,
        }

    async def set_trio_deal_event(self, event: Dict) -> None:
        key = "/trio_deal/" + "/".join(
            [
                f"{operation["exchange"]}_{operation["side"]}_{operation["symbol"]}"
                for operation in event["operations"]
            ]
        )
        await self._set(
            key,
            event,
            ex=self._config_handler.expire_deal_events,
        )

    async def get_balance(self, coin: str) -> float:
        return await self._get(f"/balance/{coin}") or 0.0

    async def set_balance(self, coin: str, value: float) -> None:
        await self._set(f"/balance/{coin}", value)

    async def get_exchange_balance(self, exchange: str) -> Dict[str, float]:
        return await self._get(f"/ebalance/{exchange}") or 0.0

    async def set_exchange_balance(
        self, exchange: str, value: Dict[str, float]
    ) -> None:
        await self._set(f"/ebalance/{exchange}", value)

    async def get_order_book(self, symbol: str, exchange_id: str) -> Dict | None:
        return await self._get(f"/order_book/{symbol}/{exchange_id}")

    async def set_order_book(self, symbol: str, exchange_id: str, value: Dict) -> None:
        await self._set(
            f"/order_book/{symbol}/{exchange_id}",
            value,
            ex=self._config_handler.expire_book_orders,
        )

    async def get_ticker(self, symbol: str, exchange_id: str) -> Dict | None:
        return await self._get(f"/ticker/{symbol}/{exchange_id}")

    async def set_ticker(self, symbol: str, exchange_id: str, value: Dict) -> None:
        await self._set(
            f"/ticker/{symbol}/{exchange_id}",
            value,
            ex=self._config_handler.expire_book_orders,
        )

    async def get_last_update_id(self) -> int | None:
        return await self._get("/bot/last_update_id")

    async def set_last_update_id(self, value: int) -> None:
        await self._set("/bot/last_update_id", value)

    async def aclose(self) -> None:
        await self._redis_client.aclose()
