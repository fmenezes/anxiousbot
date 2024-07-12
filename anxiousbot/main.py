import asyncio
import csv
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from pymemcache.client.base import Client as MemcacheClient
from pymemcache import serde
from telegram import Bot

from anxiousbot.log import get_logger


class Dealer:
    def __init__(self, logger=None, memcache_client=None):
        if logger is not None:
            self.logger = logger
        else:
            self.logger = get_logger()
        if memcache_client is not None:
            self.memcache_client = memcache_client
        else:
            self.memcache_client = MemcacheClient("localhost")

    def _match_asks_bids(
        self, balance, symbol, buy_exchange, buy_asks, sell_exchange, sell_bids
    ):
        base_coin, quote_coin = symbol.split("/")

        if base_coin not in balance:
            balance[base_coin] = 0

        if quote_coin not in balance:
            balance[quote_coin] = 0

        buy_index = 0
        sell_index = 0

        buy_price_max = buy_price_min = buy_asks[buy_index][0]
        sell_price_max = sell_price_min = sell_bids[sell_index][0]

        buy_orders = []
        sell_orders = []

        buy_total_quote = 0
        buy_total_base = 0
        sell_total_quote = 0

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
                buy_price_min = min(buy_price_min, buy_price)
                buy_price_max = max(buy_price_max, buy_price)

                sell_price_min = min(sell_price_min, sell_price)
                sell_price_max = max(sell_price_max, sell_price)

                matched_amount_base = min(
                    max_buyable_base, buy_amount_base, sell_amount_base
                )

                if matched_amount_base > 0:
                    buy_orders += [buy_price, matched_amount_base]
                    sell_orders += [sell_price, matched_amount_base]

                    buy_total_base += matched_amount_base
                    buy_total_quote += matched_amount_base * buy_price
                    sell_total_quote += matched_amount_base * sell_price

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

        return {
            "ts": str(datetime.now()),
            "profit": (sell_total_quote - buy_total_quote),
            "symbol": symbol,
            "buy": {
                "exchange": buy_exchange,
                "orders": buy_orders,
                "price": {"min": buy_price_min, "max": buy_price_max},
                "total_quote": buy_total_quote,
                "total_base": buy_total_base,
            },
            "sell": {
                "exchange": sell_exchange,
                "orders": sell_orders,
                "price": {"min": sell_price_min, "max": sell_price_max},
                "total_quote": sell_total_quote,
                "total_base": buy_total_base,
            },
        }

    async def _watch_deals(self, symbol, clients, bot, chat_id):
        try:
            while True:
                self.logger.debug(
                    f"checking deals {symbol}...", extra={"symbol": symbol}
                )
                base_coin, quote_coin = symbol.split("/")
                balance = {
                    base_coin: self.memcache_client.get(f"/balance/{base_coin}", 0.0),
                    quote_coin: self.memcache_client.get(f"/balance/{quote_coin}", 0.0),
                }

                deals = []
                for buy_cilent_id, sell_client_id in [
                    (a, b) for a in clients for b in clients if a != b
                ]:
                    asks = self.memcache_client.get(f"/asks/{symbol}/{buy_cilent_id}")
                    bids = self.memcache_client.get(f"/bids/{symbol}/{sell_client_id}")
                    if asks is None or len(asks) == 0:
                        continue
                    if bids is None or len(bids) == 0:
                        continue
                    deals += [
                        self._match_asks_bids(
                            balance, symbol, buy_cilent_id, asks, sell_client_id, bids
                        )
                    ]
                deals = [deal for deal in deals if deal["profit"] > 0]
                self.logger.debug(f"found {len(deals)} deals", extra={"symbol": symbol})
                if len(deals) > 0:
                    file_name = os.path.abspath(
                        f"data/deals_{symbol.replace('/', '-')}_{datetime.now().strftime('%Y-%m-%d')}.csv"
                    )
                    print_header = not os.path.exists(file_name)
                    with open(file_name, "a") as f:
                        w = csv.writer(f)
                        if print_header:
                            w.writerow(
                                [
                                    "timestamp",
                                    "symbol",
                                    "profit",
                                    "buy_exchange",
                                    "buy_total_base",
                                    "buy_total_quote",
                                    "sell_exchange",
                                    "sell_total_base",
                                    "sell_total_quote",
                                ]
                            )
                        for deal in deals:
                            row = [
                                datetime.now(),
                                deal["symbol"],
                                deal["profit"],
                                deal["buy"]["exchange"],
                                deal["buy"]["total_base"],
                                deal["buy"]["total_quote"],
                                deal["sell"]["exchange"],
                                deal["sell"]["total_base"],
                                deal["sell"]["total_quote"],
                            ]
                            row = [str(col) for col in row]
                            w.writerow(row)
                            base_coin, quote_coin = deal["symbol"].split("/")
                            deal_msg = f'Deal found, at {deal["buy"]["exchange"]} convert {deal["buy"]["total_quote"]} {quote_coin} to {deal["buy"]["total_base"]} {base_coin}, transfer to {deal["sell"]["exchange"]} and finally sell back to {quote_coin} for {deal["sell"]["total_quote"]}, making a profit of {deal["profit"]} {quote_coin}'
                            self.logger.info(
                                deal_msg,
                                extra={
                                    "type": "deal",
                                    "symbol": deal["symbol"],
                                    "exchange": deal["buy"]["exchange"],
                                    "sell_exchange": deal["sell"]["exchange"],
                                    "buy_quote": deal["buy"]["total_quote"],
                                    "buy_base": deal["buy"]["total_base"],
                                    "sell_quote": deal["sell"]["total_quote"],
                                    "profit": deal["profit"],
                                },
                            )
                            try:
                                await bot.send_message(chat_id=chat_id, text=deal_msg)
                            except Exception as e:
                                self.logger.exception(
                                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                                )

                await asyncio.sleep(0.5)

        except Exception as e:
            self.logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")

    async def run(self, config, bot_token, bot_chat_id):
        async with Bot(bot_token) as bot:
            tasks = []
            for symbol, exchanges in config["symbols"].items():
                tasks += [self._watch_deals(symbol, exchanges, bot, bot_chat_id)]
            await asyncio.gather(*tasks)


def _main():
    load_dotenv(override=True)
    with open("./config/config.json", "r") as f:
        config = json.load(f)
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_CHAT_ID = os.getenv("BOT_CHAT_ID")
    CACHE_ENDPOINT = os.getenv("CACHE_ENDPOINT", "localhost")
    logger = get_logger(extra={"app": "dealer"})
    memcache_client = MemcacheClient(CACHE_ENDPOINT, serde=serde.pickle_serde)
    memcache_client.set("/balance/USDT", 100000)
    dealer = Dealer(memcache_client=memcache_client)
    try:
        asyncio.run(dealer.run(config["dealer"], BOT_TOKEN, BOT_CHAT_ID))
        logger.info(f"App exited")
        return 0
    except Exception as e:
        logger.info(f"App exited with error")
        logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
        return 1


if __name__ == "__main__":
    exit(_main())
