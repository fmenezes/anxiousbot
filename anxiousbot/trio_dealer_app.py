import asyncio
from contextlib import aclosing
from datetime import datetime

from anxiousbot.bot_handler import BotHandler
from anxiousbot.calculation_handler import CalculationHandler
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.exchange_handler import ExchangeHandler
from anxiousbot.log import get_logger
from anxiousbot.order_book_handler import OrderBookHandler
from anxiousbot.redis_handler import RedisHandler


class App:
    def __init__(self):
        self._config_handler = ConfigHandler()
        self._exchange_handler = ExchangeHandler(self._config_handler)
        self._redis_handler = RedisHandler(self._config_handler)
        self._order_book_handler = OrderBookHandler(
            self._config_handler, self._exchange_handler, self._redis_handler
        )
        self._bot_handler = BotHandler(self._config_handler)
        self._calculate_handler = CalculationHandler(self._exchange_handler)
        self._loop = True
        self._logger = get_logger(__name__)

    async def _match(self, all_balances, operations):
        results = self._calculate_handler.calculate(all_balances, operations)
        profit = results["profit"]
        profit_coin = results["profit_coin"]
        profit_percentage = results["profit_percentage"]
        threshold = profit > 10 and profit_percentage >= 1
        event = {
            "event_type": "trio_deal",
            "type": "noop",
            "ts": str(datetime.now()),
            "ts_open": str(datetime.now()),
            "profit": f"{profit:8f}",
            "profit_percentage": f"{profit_percentage:8f}",
            "threshold": threshold,
            "operations": [
                {
                    "exchange": operation[0],
                    "side": operation[1],
                    "symbol": operation[2]["symbol"],
                }
                for operation in operations
            ],
        }
        past_event = await self._redis_handler.get_trio_deal_event(event)
        event["ts_open"] = past_event["ts_open"]
        if past_event["threshold"] == event["threshold"]:
            event["type"] = "update" if event["threshold"] == True else "noop"
        else:
            if event["threshold"] == True:
                event["type"] = "open"
                event["ts_open"] = event["ts"]
            else:
                event = {
                    **past_event,
                    "ts_close": past_event["ts"],
                    "type": "close",
                }
        event["duration"] = str(
            datetime.fromisoformat(event["ts"])
            - datetime.fromisoformat(event["ts_open"])
        )

        if event["type"] != "noop":
            match event["type"]:
                case "open":
                    event_type = "opened"
                case "close":
                    event_type = "closed"
                case "update":
                    event_type = "updated"
            gain_type = "profit" if profit >= 0 else "loss"

            event["message"] = (
                f"Trio deal {event_type}, making a {gain_type} of {profit:8f} {profit_coin} ({profit_percentage:2f}%) at {operations[0][0]} "
                + ", ".join(
                    [
                        f"{operation[1]} {operation[2]['symbol']}"
                        for operation in operations
                    ]
                )
            )
            if event["type"] != "open":
                event["message"] += f", took {event['duration']}"

        await self._redis_handler.set_trio_deal_event(event)

        if event["type"] != "noop":
            icon = None
            match event["type"]:
                case "open":
                    icon = "\U0001F7E2"
                case "close":
                    icon = "\U0001F534"
            if icon is not None:
                self._logger.debug(event["message"])
                await self._bot_handler.enqueue_message(f"{icon} {event["message"]}")

    async def _watch_trio(self, exchange, operations):
        lside = operations[0]["side"]
        lsymbol = operations[0]["symbol"]
        mside = operations[1]["side"]
        msymbol = operations[1]["symbol"]
        rside = operations[2]["side"]
        rsymbol = operations[2]["symbol"]

        while self._loop:
            lorderbook, morderbook, rorderbook = await asyncio.gather(
                self._redis_handler.get_order_book(lsymbol, exchange),
                self._redis_handler.get_order_book(msymbol, exchange),
                self._redis_handler.get_order_book(rsymbol, exchange),
            )
            if None in [lorderbook, morderbook, rorderbook]:
                continue
            await self._match(
                {exchange: {"USDT": 100000}},
                [
                    (exchange, lside, lorderbook),
                    (exchange, mside, morderbook),
                    (exchange, rside, rorderbook),
                ],
            )

    async def execute(self):
        exchange = "bitget"
        trios = self._config_handler.parameters["exchanges"][exchange]["symbol_trios"]
        trios = [
            operations
            for operations in trios
            if (
                operations[0]["side"] == "buy"
                and operations[0]["symbol"].endswith("/USDT")
            )
            or (
                operations[0]["side"] == "sell"
                and operations[0]["symbol"].startswith("USDT/")
            )
        ]
        symbols = list(
            set(
                [
                    operation["symbol"]
                    for operations in trios
                    for operation in operations
                ]
            )
        )
        client = await self._exchange_handler.setup_exchange(exchange)
        missing = [symbol for symbol in symbols if symbol not in client.markets.keys()]
        symbols = [symbol for symbol in symbols if symbol not in missing]
        trios = [
            operations
            for operations in trios
            if operations[0]["symbol"] not in missing
            and operations[1]["symbol"] not in missing
            and operations[2]["symbol"] not in missing
        ]
        tasks = [self._bot_handler.watch()] + [
            self._order_book_handler._watch_order_book(client.id, [symbol], "single")
            for symbol in symbols
        ]
        tasks += [self._watch_trio(exchange, operations) for operations in trios]
        await asyncio.gather(*tasks)

    async def aclose(self):
        self._loop = False
        await self._bot_handler.aclose()
        await self._order_book_handler.aclose()
        await self._redis_handler.aclose()
        await self._exchange_handler.aclose()

    @staticmethod
    async def arun() -> int:
        async with aclosing(App()) as app:
            return await app.execute()

    @staticmethod
    def run() -> int:
        return asyncio.run(App.arun())
