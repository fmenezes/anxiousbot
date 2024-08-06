import asyncio

from anxiousbot.bot_handler import BotHandler
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.deal_handler import DealHandler
from anxiousbot.exchange_handler import ExchangeHandler
from anxiousbot.log import get_logger
from anxiousbot.order_book_handler import OrderBookHandler
from anxiousbot.redis_handler import RedisHandler
from anxiousbot.trade_handler import TradeHandler


class App:
    def __init__(
        self,
    ):
        self._config_handler = ConfigHandler()
        self._exchange_handler = ExchangeHandler(self._config_handler)
        self._redis_handler = RedisHandler(self._config_handler)
        self._order_book_handler = OrderBookHandler(
            self._config_handler, self._exchange_handler, self._redis_handler
        )

        trader_handler = TradeHandler(self._exchange_handler)
        self._bot_handler = BotHandler(
            self._config_handler, self._redis_handler, trader_handler
        )
        self._deal_handler = DealHandler(
            self._config_handler,
            self._exchange_handler,
            self._redis_handler,
            self._bot_handler,
        )

        self._logger = get_logger(__name__)

    async def _watch_balance(self):
        await self._redis_handler.set_balance("USDT", 100000)

    async def run(self):
        self._logger.info(f"Dealer started")
        try:
            await self._bot_handler.initialize()

            tasks = [
                asyncio.create_task(self._watch_balance(), name="_watch_balance"),
                asyncio.create_task(
                    self._order_book_handler.watch(), name=f"order_book_handler_watch"
                ),
                asyncio.create_task(
                    self._exchange_handler.setup_all_exchanges(),
                    name=f"setup_all_exchanges",
                ),
                asyncio.create_task(
                    self._deal_handler.watch(), name=f"deal_handler_watch"
                ),
                asyncio.create_task(
                    self._bot_handler.watch(), name="bot_handler_watch"
                ),
            ]
            await asyncio.gather(*tasks)
            self._logger.info(f"Dealer exited")
            return 0
        except Exception as e:
            self._logger.info(f"Dealer exited with error")
            self._logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1

    async def aclose(self):
        tasks = [
            self._exchange_handler.aclose(),
            self._bot_handler.aclose(),
            self._order_book_handler.aclose(),
            self._deal_handler.aclose(),
        ]
        await asyncio.gather(*tasks)
        await self._redis_handler.aclose()
