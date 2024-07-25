import asyncio
from datetime import datetime

from anxiousbot import App, closing

DEFAULT_EXPIRE_BOOK_ORDERS = 60


class Updater(App):
    def __init__(self, expire_book_orders=DEFAULT_EXPIRE_BOOK_ORDERS, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.expire_book_orders = expire_book_orders

    async def _watch_order_book(self, setting):
        while True:
            try:
                async with closing(
                    await self.setup_exchange(
                        setting["exchange"], required_markets=True
                    )
                ) as client:
                    while True:
                        start = datetime.now()
                        param = setting["symbols"]
                        match setting["mode"]:
                            case "single":
                                await asyncio.sleep(0.5)
                                order_book = await self.exponential_backoff(
                                    client.fetch_order_book, param[0]
                                )
                            case "all":
                                order_book = await self.exponential_backoff(
                                    client.fetch_order_books
                                )
                            case "batch":
                                order_book = await self.exponential_backoff(
                                    client.watch_order_book_for_symbols, param
                                )
                        if "asks" in order_book:
                            self.memcache_client.set(
                                f"/asks/{order_book['symbol']}/{setting['exchange']}",
                                order_book["asks"],
                                expire=self.expire_book_orders,
                            )
                        if "bids" in order_book:
                            self.memcache_client.set(
                                f"/bids/{order_book['symbol']}/{setting['exchange']}",
                                order_book["bids"],
                                expire=self.expire_book_orders,
                            )
                        duration = str(datetime.now() - start)
                        self.logger.debug(
                            f"Updated {setting['exchange']} in {duration}",
                            extra={
                                "exchange": setting["exchange"],
                                "duration": duration,
                                "symbol": (
                                    setting["symbols"][0]
                                    if setting["mode"] == "single"
                                    else None
                                ),
                            },
                        )
            except Exception as e:
                self.logger.exception(e, extra={"exchange": setting["exchange"]})
            self.logger.debug(
                f"Closed {setting['exchange']}",
                extra={"exchange": setting["exchange"]},
            )
            await asyncio.sleep(1)

    async def run(self, config):
        try:
            self.logger.info(f"Updater started")

            tasks = []
            i = 0
            for setting in config["updater"]:
                tasks += [
                    asyncio.create_task(
                        self._watch_order_book(setting), name=f"setting-{i}"
                    )
                ]
                i += 1

            await asyncio.gather(*tasks)

            self.logger.info(f"Updater exited successfully")
            return 0
        except Exception as e:
            self.logger.info(f"Updater exited with error")
            self.logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1
