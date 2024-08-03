import asyncio
import csv
import os
from datetime import datetime

from telegram import Bot, Update

from anxiousbot import exponential_backoff, split_coin
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.deal import Deal
from anxiousbot.exchange_handler import ExchangeHandler
from anxiousbot.log import get_logger
from anxiousbot.order_book_handler import OrderBookHandler
from anxiousbot.redis_handler import RedisHandler
from anxiousbot.trader_handler import TraderHandler


class Dealer:
    def __init__(
        self,
    ):
        self._config_handler = ConfigHandler()
        self._exchange_handler = ExchangeHandler()
        self._redis_handler = RedisHandler(self._config_handler)
        self._trader_handler = TraderHandler(self._exchange_handler)
        self._order_book_handler = OrderBookHandler(
            self._config_handler, self._exchange_handler, self._redis_handler
        )

        self._bot_events = []
        self._bot_event_lock = asyncio.Lock()
        self._bot = Bot(self._config_handler.bot_token)
        self._initialized = False
        self._logger = get_logger(__name__)

    def _write_deal_xml(self, deal_event):
        if deal_event["type"] != "close":
            return
        file_name = os.path.abspath(
            f"data/{os.getenv('DEALS_FILE_PREFIX')}deals_{deal_event['symbol'].replace('/', '-')}_{datetime.fromisoformat(deal_event['ts']).strftime('%Y-%m-%d')}.csv"
        )
        print_header = not os.path.exists(file_name)
        with open(file_name, "a") as f:
            w = csv.writer(f)
            if print_header:
                w.writerow(
                    [
                        "ts",
                        "symbol",
                        "ts_open",
                        "ts_close",
                        "duration",
                        "profit",
                        "profit_percentage",
                        "buy_exchange",
                        "buy_total_quote",
                        "buy_total_base",
                        "sell_exchange",
                        "sell_total_quote",
                    ]
                )

            row = [
                deal_event.get("ts"),
                deal_event.get("symbol"),
                deal_event.get("ts_open"),
                deal_event.get("ts_close"),
                deal_event.get("duration"),
                deal_event.get("profit"),
                deal_event.get("profit_percentage"),
                deal_event.get("buy_exchange"),
                deal_event.get("buy_total_quote"),
                deal_event.get("buy_total_base"),
                deal_event.get("sell_exchange"),
                deal_event.get("sell_total_quote"),
            ]
            w.writerow(row)

    async def _process_deal(self, deal):
        current_event = await self._redis_handler.get_deal(
            deal.symbol, deal.buy_exchange.id, deal.sell_exchange.id
        )
        new_event = deal.to_dict()

        new_event["ts_open"] = current_event["ts_open"]
        if current_event["threshold"] == new_event["threshold"]:
            new_event["type"] = "update" if new_event["threshold"] == True else "noop"
        else:
            if new_event["threshold"] == True:
                new_event["type"] = "open"
                new_event["ts_open"] = new_event["ts"]
            else:
                new_event = {
                    **current_event,
                    "ts_close": current_event["ts"],
                    "type": "close",
                }
        new_event["duration"] = str(
            datetime.fromisoformat(new_event["ts"])
            - datetime.fromisoformat(new_event["ts_open"])
        )

        base_coin, quote_coin = split_coin(deal.symbol)
        if new_event["type"] != "noop":
            match new_event["type"]:
                case "open":
                    event_type = "opened"
                case "close":
                    event_type = "closed"
                case "update":
                    event_type = "updated"
            gain_type = "profit" if deal.profit >= 0 else "loss"

            new_event["message"] = (
                f"Deal {event_type}, making a {gain_type} of {new_event['profit']} {quote_coin} ({new_event['profit_percentage']}%), at {new_event['buy_exchange']} convert {new_event['buy_total_quote']} {quote_coin} to {new_event['buy_total_base']} {base_coin}, transfer to {new_event['sell_exchange']} and finally sell back to {quote_coin} for {new_event['sell_total_quote']}, took {new_event['duration']}"
            )

        await self._redis_handler.set_deal(
            deal.symbol, deal.buy_exchange.id, deal.sell_exchange.id, new_event
        )

        if new_event["type"] != "noop":
            self._logger.info(
                {"type": "deal", **new_event},
            )
            self._write_deal_xml(new_event)
            async with self._bot_event_lock:
                self._bot_events += [new_event]

    async def _process_bot_events(self):
        while True:
            try:
                async with self._bot_event_lock:
                    if len(self._bot_events) == 0:
                        event = None
                    else:
                        event = self._bot_events[0]
                        self._bot_events = self._bot_events[1:]
                if event is None:
                    await asyncio.sleep(1)
                    continue
                if event["type"] not in ["close"]:
                    continue
                icon = "\U0001F7E2" if event["type"] == "open" else "\U0001F534"
                msg = f"{icon} {event['message']}"
                await exponential_backoff(
                    self._bot.send_message,
                    chat_id=self._config_handler.bot_chat_id,
                    text=msg,
                    read_timeout=35,
                    write_timeout=35,
                    connect_timeout=35,
                    pool_timeout=35,
                )
            except Exception as e:
                self._logger.exception(
                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                )
                await asyncio.sleep(0.5)

    async def _watch_deals(self, symbol):
        while True:
            try:
                start = datetime.now()
                self._logger.debug(
                    f"checking deals {symbol}...", extra={"symbol": symbol}
                )
                base_coin, quote_coin = symbol.split("/")
                balance = {
                    base_coin: await self._redis_handler.get_balance(base_coin),
                    quote_coin: await self._redis_handler.get_balance(quote_coin),
                }

                tasks = []
                for buy_client_id, sell_client_id in [
                    (a, b)
                    for a in self._exchange_handler.ids()
                    for b in self._exchange_handler.ids()
                    if a != b
                ]:
                    buy_order_book = await self._redis_handler.get_order_book(
                        symbol, buy_client_id
                    )
                    if buy_order_book is None:
                        continue
                    asks = buy_order_book.get("asks")
                    if asks is None or len(asks) == 0:
                        continue
                    sell_order_book = await self._redis_handler.get_order_book(
                        symbol, sell_client_id
                    )
                    if sell_order_book is None:
                        continue
                    bids = sell_order_book.get("bids")
                    if bids is None or len(bids) == 0:
                        continue
                    deal = Deal(
                        symbol,
                        self._exchange_handler.exchange(buy_client_id),
                        asks,
                        self._exchange_handler.exchange(sell_client_id),
                        bids,
                    )
                    deal.calculate(balance)
                    tasks += [self._process_deal(deal)]

                await asyncio.gather(*tasks)
                duration = datetime.now() - start
                self._logger.debug(
                    f"checked deals {symbol}, took {duration}",
                    extra={"symbol": symbol, "duration": str(duration)},
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                self._logger.exception(
                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                )

    async def _watch_balance(self):
        await self._redis_handler.set_balance("USDT", 100000)

    async def _initialize(self):
        if self._initialized == True:
            return
        await self._bot.initialize()
        await self._bot.set_my_commands([("balance", "fetch balance")])
        await self._bot.set_my_short_description("anxiousbot trading without patience")
        await self._bot.set_my_description("anxiousbot trading without patience")

        self._initialized = True

    async def fetch_balance(self, update):
        result = await self._trader_handler.fetch_balance()
        msg = ""
        for exchange_id, data in result.items():
            match data["status"]:
                case "NOT_AUTH":
                    continue
                case "NOT_INIT":
                    msg += f"{exchange_id}: Not initialized\n"
                case "ERROR":
                    msg += f"{exchange_id}: Error: {data["exception"]}\n"
                case "OK":
                    msg += f"{exchange_id}: OK\n"
                    for symbol, value in data["balance"].get("free").items():
                        if value > 0:
                            msg += f"  {symbol} {value:.8f}\n"

        await exponential_backoff(
            self._bot.send_message,
            chat_id=update.effective_message.chat_id,
            text=msg,
            read_timeout=35,
            write_timeout=35,
            connect_timeout=35,
            pool_timeout=35,
        )

    async def _listen_bot_updates(self):
        _last_update_id = await self._redis_handler.get_last_update_id()

        while True:
            try:
                updates = await self._bot.get_updates(
                    offset=_last_update_id, timeout=10, allowed_updates=Update.MESSAGE
                )
                for update in updates:
                    if (
                        _last_update_id is not None
                        and update.update_id <= _last_update_id
                    ):
                        continue
                    if update.message and update.message.text:
                        match update.message.text:
                            case "/balance":
                                await self.fetch_balance(update)
                    _last_update_id = update.update_id
                    await self._redis_handler.set_last_update_id(_last_update_id)
            except Exception as e:
                self._logger.exception(
                    f"An error occurred while processing bot updates: [{type(e).__name__}] {str(e)}"
                )

    async def run(self):
        self._logger.info(f"Dealer started")
        try:
            await self._initialize()
            self._logger.debug(f"Bot initialized")

            tasks = [
                asyncio.create_task(
                    self._process_bot_events(), name="_process_bot_events"
                ),
                asyncio.create_task(self._watch_balance(), name="_watch_balance"),
                asyncio.create_task(
                    self._order_book_handler.watch(), name=f"order_book_handler_watch"
                ),
            ]
            if self._config_handler.run_bot_updates:
                tasks += [
                    asyncio.create_task(
                        self._listen_bot_updates(), name="_listen_bot_updates"
                    )
                ]
            tasks += [
                asyncio.create_task(
                    self._exchange_handler.setup_exchange(id),
                    name=f"setup_exchange_{id}",
                )
                for id in self._order_book_handler.exchange_ids()
            ]
            tasks += [
                asyncio.create_task(
                    self._watch_deals(symbol), name=f"_watch_deals_{symbol}"
                )
                for symbol in self._config_handler.symbols
            ]

            await asyncio.gather(*tasks)
            self._logger.info(f"Dealer exited")
            return 0
        except Exception as e:
            self._logger.info(f"Dealer exited with error")
            self._logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1

    async def close(self):
        tasks = [
            self._exchange_handler.close(),
            self._bot.shutdown(),
            self._order_book_handler.close(),
        ]
        await asyncio.gather(*tasks)
