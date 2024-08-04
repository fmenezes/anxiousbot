import asyncio
from datetime import datetime
from typing import Dict, Iterator, List

from anxiousbot import exponential_backoff
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.exchange_handler import ExchangeHandler
from anxiousbot.log import get_logger
from anxiousbot.redis_handler import RedisHandler


class OrderBookHandler:
    def __init__(
        self,
        config_handler: ConfigHandler,
        exchange_handler: ExchangeHandler,
        redis_handler: RedisHandler,
    ):
        self._exchange_handler = exchange_handler
        self._config_handler = config_handler
        self._redis_handler = redis_handler
        self._logger = get_logger(__name__)
        self._loop = True

    def _update_settings(self) -> Iterator[Dict]:
        ids = self._exchange_handler.available_ids()
        settings = [
            {
                **self._config_handler.exchanges_param[id],
                "symbols": [
                    symbol
                    for symbol in self._config_handler.exchanges_param[id]["symbols"]
                    if symbol in self._config_handler.symbols
                ],
            }
            for id in ids
        ]
        settings = [entry for entry in settings if len(entry["symbols"]) > 0]
        for setting in settings:
            match setting["mode"]:
                case "all":
                    yield setting
                case "batch":
                    yield setting
                case "single":
                    for symbol in setting["symbols"]:
                        yield {**setting, "symbols": [symbol]}

    async def _watch_order_book(self, setting: Dict) -> None:
        while self._loop:
            client = self._exchange_handler.exchange(setting["exchange"])
            if client is None:
                await asyncio.sleep(0.5)
                continue
            break
        while self._loop:
            try:
                start = datetime.now()
                param = setting["symbols"]
                match setting["mode"]:
                    case "single":
                        await asyncio.sleep(0.5)
                        order_book = await exponential_backoff(
                            client.fetch_order_book, param[0]
                        )
                    case "all":
                        order_book = await exponential_backoff(client.fetch_order_books)
                    case "batch":
                        order_book = await exponential_backoff(
                            client.watch_order_book_for_symbols, param
                        )

                async def update_order_book(order_book, symbol):
                    await self._redis_handler.set_order_book(
                        symbol, setting["exchange"], order_book
                    )
                    duration = str(datetime.now() - start)
                    self._logger.debug(
                        f"Updated {setting['exchange']} in {duration}",
                        extra={
                            "exchange": setting["exchange"],
                            "duration": duration,
                            "symbol": symbol,
                        },
                    )

                if setting["mode"] == "all" or setting["mode"] == "batch":
                    for symbol, order in order_book.items():
                        if symbol in self._config_handler.symbols:
                            await update_order_book(order, symbol)
                else:
                    await update_order_book(order_book, order_book["symbol"])
            except Exception as e:
                self._logger.exception(e, extra={"exchange": setting["exchange"]})
            await asyncio.sleep(1)

    async def close(self) -> None:
        self._loop = False

    async def watch(self) -> None:
        tasks = []
        for setting in self._update_settings():
            task_name = f"_watch_order_book_{setting['exchange']}"
            if setting["mode"] == "single":
                task_name += f"_{setting['symbols'][0]}"
            tasks += [
                asyncio.create_task(self._watch_order_book(setting), name=task_name)
            ]

        return await asyncio.gather(*tasks)
