import asyncio
import csv
import json
import os
from datetime import datetime
from types import CoroutineType

import ccxt.pro as ccxt
from ccxt.base.errors import RateLimitExceeded
from redis.asyncio import Redis
from telegram import Bot, Update
from telegram.error import RetryAfter

from anxiousbot import get_logger, split_coin
from anxiousbot.config import ConfigHandler
from anxiousbot.deal import Deal


class Dealer:
    def __init__(
        self,
        config_handler: ConfigHandler,
    ):
        self._config_handler = config_handler

        self._auth_exchanges = []
        self._bot_events = []
        self._bot_event_lock = asyncio.Lock()
        self._bot = Bot(self._config_handler.bot_token)
        self._initialized = False
        self._exchanges = {}
        self._logger = get_logger(__name__)
        self._redis_client = Redis.from_url(self._config_handler.cache_endpoint)

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
        current_event = json.loads(
            await self._redis_client.get(
                f"/deal/{deal.symbol}/{deal.buy_exchange.id}/{deal.sell_exchange.id}"
            )
            or f'{{"ts_open": "{datetime.now()}", "type": "noop", "threshold": false}}'
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

        await self._redis_client.set(
            f"/deal/{deal.symbol}/{deal.buy_exchange.id}/{deal.sell_exchange.id}",
            json.dumps(new_event),
            ex=self._config_handler.expire_deal_events,
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
                await self._exponential_backoff(
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
                    base_coin: json.loads(
                        await self._redis_client.get(f"/balance/{base_coin}") or "0.0"
                    ),
                    quote_coin: json.loads(
                        await self._redis_client.get(f"/balance/{quote_coin}") or "0.0"
                    ),
                }

                tasks = []
                for buy_client_id, sell_client_id in [
                    (a, b)
                    for a in self._exchanges.keys()
                    for b in self._exchanges.keys()
                    if a != b
                ]:
                    buy_order_book = await self._redis_client.get(
                        f"/order_book/{symbol}/{buy_client_id}"
                    )
                    if buy_order_book is None:
                        continue
                    buy_order_book = json.loads(buy_order_book)
                    asks = buy_order_book.get("asks")
                    if asks is None or len(asks) == 0:
                        continue
                    sell_order_book = await self._redis_client.get(
                        f"/order_book/{symbol}/{sell_client_id}"
                    )
                    if sell_order_book is None:
                        continue
                    sell_order_book = json.loads(sell_order_book)
                    bids = sell_order_book.get("bids")
                    if bids is None or len(bids) == 0:
                        continue
                    deal = Deal(
                        symbol,
                        self._exchanges[buy_client_id],
                        asks,
                        self._exchanges[sell_client_id],
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

    async def _close_exchange(self, client):
        del self._exchanges[client.id]
        return await client.close()

    async def _watch_order_book(self, setting):
        while True:
            client = self._exchanges.get(setting["exchange"])
            if client is None:
                await asyncio.sleep(0.5)
                continue
            break
        while True:
            try:
                start = datetime.now()
                param = setting["symbols"]
                match setting["mode"]:
                    case "single":
                        await asyncio.sleep(0.5)
                        order_book = await self._exponential_backoff(
                            client.fetch_order_book, param[0]
                        )
                    case "all":
                        order_book = await self._exponential_backoff(
                            client.fetch_order_books
                        )
                    case "batch":
                        order_book = await self._exponential_backoff(
                            client.watch_order_book_for_symbols, param
                        )

                async def update_order_book(order_book, symbol):
                    await self._redis_client.set(
                        f"/order_book/{symbol}/{setting['exchange']}",
                        json.dumps(order_book),
                        ex=self._config_handler.expire_book_orders,
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

    async def _watch_balance(self):
        await self._redis_client.set("/balance/USDT", "100000")

    async def _initialize(self):
        if self._initialized == True:
            return
        await self._bot.initialize()
        await self._bot.set_my_commands([("balance", "fetch balance")])
        await self._bot.set_my_short_description("anxiousbot trading without patience")
        await self._bot.set_my_description("anxiousbot trading without patience")

        with open("./config/exchanges.json", "r") as f:
            self.exchanges_param = json.load(f)

        with open("./config/symbols.json", "r") as f:
            self.symbols_param = json.load(f)

        self._initialized = True

    def _exchange_ids(self, symbols):
        return list(
            set(
                [
                    exchange
                    for symbol in symbols
                    for exchange in self.symbols_param[symbol]["exchanges"]
                ]
            )
        )

    def _update_settings(self, symbols):
        ids = self._exchange_ids(symbols)
        settings = [
            {
                **self.exchanges_param[id],
                "symbols": [
                    symbol
                    for symbol in self.exchanges_param[id]["symbols"]
                    if symbol in symbols
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

    async def fetch_balance(self, update):
        msg = ""
        for exchange_id in self._auth_exchanges:
            if exchange_id not in self._exchanges:
                msg += f"{exchange_id}: Not initialized\n"
                continue
            try:
                balance = await self._exchanges[exchange_id].fetch_balance()
                msg += f"{exchange_id}: OK\n"
                for symbol, value in balance.get("free").items():
                    if value > 0:
                        msg += f"  {symbol} {value:.8f}\n"
            except Exception as e:
                msg += f"{exchange_id}: error {e}\n"

        await self._exponential_backoff(
            self._bot.send_message,
            chat_id=update.effective_message.chat_id,
            text=msg,
            read_timeout=35,
            write_timeout=35,
            connect_timeout=35,
            pool_timeout=35,
        )

    async def _listen_bot_updates(self):
        _last_update_id = await self._redis_client.get("/bot/last_update_id")
        if _last_update_id is not None:
            try:
                _last_update_id = int(_last_update_id)
            except:
                pass

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
                    await self._redis_client.set(
                        "/bot/last_update_id", str(_last_update_id)
                    )
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
            ]
            if self._config_handler.run_bot_updates:
                tasks += [
                    asyncio.create_task(
                        self._listen_bot_updates(), name="_listen_bot_updates"
                    )
                ]
            tasks += [
                asyncio.create_task(
                    self._setup_exchange(id), name=f"_setup_exchange_{id}"
                )
                for id in self._exchange_ids(self._config_handler.symbols)
            ]
            tasks += [
                asyncio.create_task(
                    self._watch_deals(symbol), name=f"_watch_deals_{symbol}"
                )
                for symbol in self._config_handler.symbols
            ]
            for setting in self._update_settings(self._config_handler.symbols):
                task_name = f"_watch_order_book_{setting['exchange']}"
                if setting["mode"] == "single":
                    task_name += f"_{setting['symbols'][0]}"
                tasks += [
                    asyncio.create_task(self._watch_order_book(setting), name=task_name)
                ]

            await asyncio.gather(*tasks)
            self._logger.info(f"Dealer exited")
            return 0
        except Exception as e:
            self._logger.info(f"Dealer exited with error")
            self._logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1

    async def close(self):
        tasks = [client.close() for client in self._exchanges.values()] + [
            self._bot.shutdown()
        ]
        await asyncio.gather(*tasks)

    async def _exponential_backoff(self, fn, *args, **kwargs):
        backoff = [1, 2, 4, 8]
        last_exception = None
        for delay in backoff:
            try:
                return await fn(*args, **kwargs)
            except asyncio.CancelledError as e:
                raise e
            except RateLimitExceeded as e:
                await asyncio.sleep(60)
                last_exception = e
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                last_exception = e
            except Exception as e:
                await asyncio.sleep(delay)
                if isinstance(e, CoroutineType):
                    last_exception = await e
                else:
                    last_exception = e
        raise last_exception

    def _credentials(self, exchange_id):
        auth_keys = [
            "apiKey",
            "secret",
            "uid",
            "accountId",
            "login",
            "password",
            "twofa",
            "privateKey",
            "walletAddress",
            "token",
        ]
        auth = dict(
            [
                (key, os.getenv(f"{exchange_id.upper()}_{key.upper()}"))
                for key in auth_keys
            ]
        )
        auth = dict(
            [
                (key, value.replace("\\n", "\n"))
                for key, value in auth.items()
                if value is not None
            ]
        )

        if len(auth.keys()) == 0:
            return None

        return auth

    async def _setup_exchange(self, exchange_id):
        if exchange_id in self._exchanges:
            return self._exchanges[exchange_id]

        auth = self._credentials(exchange_id)
        client_cls = getattr(ccxt, exchange_id)
        if auth is not None:
            client = client_cls(auth)
            self._auth_exchanges += [client.id]
            self._logger.debug(
                f"{exchange_id} logged in",
                extra={"exchange": exchange_id},
            )
        else:
            client = client_cls()

        while True:
            try:
                await self._exponential_backoff(client.load_markets)
                self._logger.info(
                    f"{exchange_id} loaded markets",
                    extra={"exchange": exchange_id},
                )
                break
            except Exception as e:
                self._logger.exception(e, extra={"exchange": exchange_id})
                await client.close()
                await asyncio.sleep(1)

        self._exchanges[client.id] = client
        return client
