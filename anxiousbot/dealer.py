import asyncio
import copy
import csv
import json
import os
import sys
import traceback
from datetime import datetime

from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient

from anxiousbot import App, closing
from anxiousbot.log import get_logger


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

    @staticmethod
    def to_csv_header():
        return [
            "timestamp",
            "symbol",
            "profit",
            "profit_percentage",
            "buy_exchange",
            "buy_total_base",
            "buy_total_quote",
            "sell_exchange",
            "sell_total_base",
            "sell_total_quote",
        ]

    def _split_coin(self):
        return self.symbol.split("/")

    def calculate(self, balance):
        base_coin, quote_coin = self._split_coin()

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
    def message(self):
        base_coin, quote_coin = self._split_coin()
        type = "profit" if self.profit >= 0 else "loss"
        return f"Deal found, making a {type} of {self.format_profit()} {quote_coin}, at {self.buy_exchange.id} convert {self.format_buy_total_quote()} {quote_coin} to {self.format_buy_total_base()} {base_coin}, transfer to {self.sell_exchange.id} and finally sell back to {quote_coin} for {self.format_sell_total_quote()}"

    def to_csv(self):
        return [
            self.format_ts(),
            self.symbol,
            self.format_profit(),
            self.format_profit_percentage(),
            self.buy_exchange.id,
            self.format_buy_total_base(),
            self.format_buy_total_quote(),
            self.sell_exchange.id,
            self.format_buy_total_base(),
            self.format_sell_total_quote(),
        ]

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "profit": self.format_profit(),
            "profit_percentage": self.format_profit_percentage(),
            "buy_exchange": self.buy_exchange.id,
            "buy_total_base": self.format_buy_total_base(),
            "buy_total_quote": self.format_buy_total_quote(),
            "sell_exchange": self.sell_exchange.id,
            "sell_total_quote": self.format_sell_total_quote(),
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


class Dealer(App):
    async def _watch_deals(self, symbol, clients, bot_queue):
        while True:
            try:
                self.logger.debug(
                    f"checking deals {symbol}...", extra={"symbol": symbol}
                )
                base_coin, quote_coin = symbol.split("/")
                balance = {
                    base_coin: self.memcache_client.get(f"/balance/{base_coin}", 0.0),
                    quote_coin: self.memcache_client.get(f"/balance/{quote_coin}", 0.0),
                }

                deals = []
                for buy_client_id, sell_client_id in [
                    (a, b) for a in clients for b in clients if a != b
                ]:
                    asks = self.memcache_client.get(f"/asks/{symbol}/{buy_client_id}")
                    bids = self.memcache_client.get(f"/bids/{symbol}/{sell_client_id}")
                    if asks is None or len(asks) == 0:
                        continue
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
                    deals += [deal]
                deals = [deal for deal in deals if deal.profit_percentage >= 1]
                self.logger.debug(f"found {len(deals)} deals", extra={"symbol": symbol})
                if len(deals) > 0:
                    file_name = os.path.abspath(
                        f"data/deals_{symbol.replace('/', '-')}_{datetime.now().strftime('%Y-%m-%d')}.csv"
                    )
                    print_header = not os.path.exists(file_name)
                    with open(file_name, "a") as f:
                        w = csv.writer(f)
                        if print_header:
                            w.writerow(Deal.to_csv_header())
                        for deal in deals:
                            row = deal.to_csv()
                            w.writerow(row)
                            self.logger.info(
                                deal.message,
                                extra={"type": "deal", **deal.to_dict()},
                            )
                            bot_queue.put(deal.message)

                await asyncio.sleep(0.5)
            except Exception as e:
                self.logger.exception(
                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                )

    async def _init_exchanges(self, config):
        self.exchanges = {}
        all_exchanges = []
        for symbol, exchanges in config["symbols"].items():
            all_exchanges += exchanges
        all_exchanges = list(set(all_exchanges))
        for exchange_id in all_exchanges:
            try:
                self.exchanges[exchange_id] = await self.setup_exchange(
                    exchange_id, True
                )
            except Exception as e:
                self.logger.exception(
                    e,
                    extra={
                        "exchange": exchange_id,
                    },
                )

    async def run(self, config, bot_queue):
        await self._init_exchanges(config)

        tasks = []
        for symbol, exchanges in config["symbols"].items():
            tasks += [self._watch_deals(symbol, exchanges, bot_queue)]

        await asyncio.gather(*tasks)


async def run(bot_queue):
    CONFIG_PATH = os.getenv("CONFIG_PATH", "./config/config.json")
    CACHE_ENDPOINT = os.getenv("CACHE_ENDPOINT", "localhost")

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    logger = get_logger(extra={"app": "dealer"})

    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.exception(traceback.format_exception(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    memcache_client = MemcacheClient(CACHE_ENDPOINT, serde=serde.pickle_serde)
    memcache_client.set("/balance/USDT", 100000)
    async with closing(
        Dealer(
            memcache_client=memcache_client,
            logger=logger,
        )
    ) as dealer:
        try:
            logger.info(f"Dealer started")
            await dealer.run(config["dealer"], bot_queue)
            logger.info(f"Dealer exited")
            return 0
        except Exception as e:
            logger.info(f"Dealer exited with error")
            logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1
