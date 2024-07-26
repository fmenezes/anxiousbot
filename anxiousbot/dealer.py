import asyncio
import copy
import csv
import os
from datetime import datetime
from types import CoroutineType

import ccxt.pro as ccxt
from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient
from telegram import Bot

from anxiousbot import get_logger, split_coin

DEFAULT_EXIPRE_DEAL_EVENTS = 60
DEFAULT_EXPIRE_BOOK_ORDERS = 60


class Deal:
    def __init__(self, symbol, buy_exchange, buy_asks, sell_exchange, sell_bids):
        self.symbol = symbol
        self.buy_exchange = buy_exchange
        self.sell_exchange = sell_exchange
        self.buy_asks = buy_asks
        self.sell_bids = sell_bids
        self.ts = datetime.now()

        # known after calculating
        self.buy_price_min = 0
        self.buy_price_max = 0
        self.sell_price_min = 0
        self.sell_price_max = 0
        self.sell_orders = []
        self.buy_orders = []
        self.buy_total_quote = 0
        self.buy_total_base = 0
        self.sell_total_quote = 0

    def calculate(self, balance):
        base_coin, quote_coin = split_coin(self.symbol)

        if base_coin not in balance:
            balance[base_coin] = 0

        if quote_coin not in balance:
            balance[quote_coin] = 0

        buy_index = 0
        sell_index = 0

        buy_asks = copy.deepcopy(self.buy_asks)
        sell_bids = copy.deepcopy(self.sell_bids)

        self.buy_price_max = self.buy_price_min = buy_asks[buy_index][0]
        self.sell_price_max = self.sell_price_min = sell_bids[sell_index][0]

        while (
            balance[quote_coin] > 0
            and buy_index < len(buy_asks)
            and sell_index < len(sell_bids)
        ):
            buy_price = buy_asks[buy_index][0]
            buy_amount_base = buy_asks[buy_index][1]
            sell_price = sell_bids[sell_index][0]
            sell_amount_base = sell_bids[sell_index][1]
            current_balance_quote = balance[quote_coin]
            max_buyable_base = current_balance_quote / buy_price

            # Ensure buy price is less than or equal to sell price for a match
            if buy_price < sell_price:
                self.buy_price_min = min(self.buy_price_min, buy_price)
                self.buy_price_max = max(self.buy_price_max, buy_price)

                self.sell_price_min = min(self.sell_price_min, sell_price)
                self.sell_price_max = max(self.sell_price_max, sell_price)

                matched_amount_base = min(
                    max_buyable_base, buy_amount_base, sell_amount_base
                )

                if matched_amount_base > 0:
                    self.buy_orders += [buy_price, matched_amount_base]
                    self.sell_orders += [sell_price, matched_amount_base]

                    self.buy_total_base += matched_amount_base
                    self.buy_total_quote += matched_amount_base * buy_price
                    self.sell_total_quote += matched_amount_base * sell_price

                    # Update the amounts
                    buy_asks[buy_index][1] -= matched_amount_base
                    sell_bids[sell_index][1] -= matched_amount_base
                    balance[quote_coin] -= matched_amount_base * buy_price
                    balance[base_coin] += matched_amount_base

                # Remove orders that are fully matched
                if buy_asks[buy_index][1] <= 0:
                    buy_index += 1
                if sell_bids[sell_index][1] <= 0:
                    sell_index += 1
            else:
                # If the prices don't match, exit the loop
                break

    @property
    def profit(self):
        return self.sell_total_quote - self.buy_total_quote

    @property
    def profit_percentage(self):
        if self.buy_total_quote == 0:
            return 0
        return self.profit / self.buy_total_quote * 100

    @property
    def threshold(self):
        return self.profit > 0
        # return self.profit_percentage >= 1

    def to_dict(self):
        return {
            "ts": self.format_ts(),
            "symbol": self.symbol,
            "profit": self.format_profit(),
            "profit_percentage": self.format_profit_percentage(),
            "buy_exchange": self.buy_exchange.id,
            "buy_total_base": self.format_buy_total_base(),
            "buy_total_quote": self.format_buy_total_quote(),
            "sell_exchange": self.sell_exchange.id,
            "sell_total_quote": self.format_sell_total_quote(),
            "threshold": self.threshold,
        }

    def format_profit(self):
        try:
            return self.sell_exchange.price_to_precision(self.symbol, self.profit)
        except:
            return f"{self.profit:2f}"

    def format_profit_percentage(self):
        try:
            return self.sell_exchange.decimal_to_precision(
                self.profit_percentage, precision=2
            )
        except:
            return f"{self.profit_percentage:2f}"

    def format_buy_price_min(self):
        try:
            return self.buy_exchange.price_to_precision(self.buy_price_min)
        except:
            return f"{self.buy_price_min:2f}"

    def format_buy_price_max(self):
        try:
            return self.buy_exchange.price_to_precision(self.buy_price_max)
        except:
            return f"{self.buy_price_max:2f}"

    def format_buy_total_quote(self):
        try:
            return self.buy_exchange.amount_to_precision(self.buy_total_quote)
        except:
            return f"{self.buy_total_quote:2f}"

    def format_buy_total_base(self):
        try:
            return self.buy_exchange.amount_to_precision(self.buy_total_base)
        except:
            return f"{self.buy_total_base:2f}"

    def format_sell_price_min(self):
        try:
            return self.sell_exchange.price_to_precision(self.sell_price_min)
        except:
            return f"{self.sell_price_min:2f}"

    def format_sell_price_max(self):
        try:
            return self.sell_exchange.price_to_precision(self.sell_price_max)
        except:
            return f"{self.sell_price_max:2f}"

    def format_sell_total_quote(self):
        try:
            return self.sell_exchange.amount_to_precision(self.sell_total_quote)
        except:
            return f"{self.sell_total_quote:2f}"

    def format_ts(self):
        return str(self.ts)


class Dealer:
    def __init__(
        self,
        bot_token,
        bot_chat_id,
        expire_book_orders=DEFAULT_EXPIRE_BOOK_ORDERS,
        expire_deal_events=DEFAULT_EXIPRE_DEAL_EVENTS,
        memcache_client=None,
        logger=None,
    ):
        self._bot_token = bot_token
        self._bot_chat_id = bot_chat_id
        self._bot_events = []
        self._bot_event_lock = asyncio.Lock()
        self._bot = Bot(self._bot_token)
        self.expire_book_orders = expire_book_orders
        self.expire_deal_events = expire_deal_events
        self.exchanges = {}
        if logger is None:
            logger = get_logger()
        self.logger = logger
        if memcache_client is None:
            memcache_client = MemcacheClient("localhost", serde=serde.pickle_serde)
        self.memcache_client = memcache_client

    def _write_deal_xml(self, deal_event):
        if deal_event["type"] != "close":
            return
        file_name = os.path.abspath(
            f"data/deals_{deal_event['symbol'].replace('/', '-')}_{datetime.fromisoformat(deal_event['ts']).strftime('%Y-%m-%d')}.csv"
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

    def _log_deal_event(self, deal_event):
        self.logger.info(
            {"type": "deal", **deal_event},
        )

    async def _process_deal(self, deal):
        current_event = self.memcache_client.get(
            f"/deal/{deal.symbol}/{deal.buy_exchange.id}/{deal.sell_exchange.id}",
            {"ts_open": str(datetime.now()), "type": "noop", "threshold": False},
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

        self.memcache_client.set(
            f"/deal/{deal.symbol}/{deal.buy_exchange.id}/{deal.sell_exchange.id}",
            new_event,
            expire=self.expire_deal_events,
        )

        if new_event["type"] != "noop":
            async with self._bot_event_lock:
                self._bot_events += [new_event]
            self._log_deal_event(new_event)

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
                self._write_deal_xml(event)
                if event["type"] not in ["open", "close"]:
                    continue
                icon = "\U0001F7E2" if event["type"] == "open" else "\U0001F534"
                msg = f"{icon} {event['message']}"
                await self._exponential_backoff(
                    self._bot.send_message, chat_id=self._bot_chat_id, text=msg
                )
            except Exception as e:
                self.logger.exception(
                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                )
                await asyncio.sleep(0.5)

    async def _watch_deals(self, symbol):
        while True:
            try:
                start = datetime.now()
                self.logger.debug(
                    f"checking deals {symbol}...", extra={"symbol": symbol}
                )
                base_coin, quote_coin = symbol.split("/")
                balance = {
                    base_coin: self.memcache_client.get(f"/balance/{base_coin}", 0.0),
                    quote_coin: self.memcache_client.get(f"/balance/{quote_coin}", 0.0),
                }

                tasks = []
                for buy_client_id, sell_client_id in [
                    (a, b)
                    for a in self.exchanges.keys()
                    for b in self.exchanges.keys()
                    if a != b
                ]:
                    asks = self.memcache_client.get(f"/asks/{symbol}/{buy_client_id}")
                    if asks is None or len(asks) == 0:
                        continue
                    bids = self.memcache_client.get(f"/bids/{symbol}/{sell_client_id}")
                    if bids is None or len(bids) == 0:
                        continue
                    deal = Deal(
                        symbol,
                        self.exchanges[buy_client_id],
                        asks,
                        self.exchanges[sell_client_id],
                        bids,
                    )
                    deal.calculate(balance)
                    tasks += [self._process_deal(deal)]

                await asyncio.gather(*tasks)
                duration = datetime.now() - start
                self.logger.debug(
                    f"checked deals {symbol}, took {duration}",
                    extra={"symbol": symbol, "duration": str(duration)},
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                self.logger.exception(
                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                )

    async def _close_exchange(self, client):
        del self.exchanges[client.id]
        return await client.close()

    async def _watch_order_book(self, setting):
        while True:
            client = self.exchanges.get(setting["exchange"])
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

    async def _watch_balance(self):
        self.memcache_client.set("/balance/USDT", 100000)

    async def run(self, config):
        self.logger.info(f"Dealer started")
        try:
            await self._bot.initialize()
            self.logger.debug(f"Bot initialized")

            tasks = [
                asyncio.create_task(
                    self._process_bot_events(), name="_process_bot_events"
                ),
                asyncio.create_task(self._watch_balance(), name="_watch_balance"),
            ]
            exchange_ids = list(
                set(
                    [
                        id
                        for id_list in list(config["dealer"]["symbols"].values())
                        for id in id_list
                    ]
                )
            )
            tasks += [
                asyncio.create_task(
                    self._setup_exchange(id), name=f"_setup_exchange_{id}"
                )
                for id in exchange_ids
            ]
            tasks += [
                asyncio.create_task(
                    self._watch_deals(symbol), name=f"_watch_deals_{symbol}"
                )
                for symbol in config["dealer"]["symbols"].keys()
            ]
            i = 0
            for setting in config["updater"]:
                tasks += [
                    asyncio.create_task(
                        self._watch_order_book(setting), name=f"_watch_order_book_{i}"
                    )
                ]
                i += 1

            await asyncio.gather(*tasks)
            self.logger.info(f"Dealer exited")
            return 0
        except Exception as e:
            self.logger.info(f"Dealer exited with error")
            self.logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1

    async def close(self):
        tasks = [client.close() for client in self.exchanges.values()] + [
            self._bot.close()
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
            except Exception as e:
                await asyncio.sleep(delay)
                if isinstance(e, CoroutineType):
                    last_exception = await e
                else:
                    last_exception = e
                self.logger.exception(e)
        raise last_exception

    async def _setup_exchange(self, exchange_id):
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

        while True:
            try:
                await self._exponential_backoff(client.load_markets)
                self.logger.info(
                    f"{exchange_id} loaded markets",
                    extra={"exchange": exchange_id},
                )
                break
            except Exception as e:
                self.logger.exception(e, extra={"exchange": exchange_id})
                await client.close()
                await asyncio.sleep(1)

        self.exchanges[client.id] = client
        return client
