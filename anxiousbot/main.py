from telegram import Bot
import asyncio
import logging
import csv
import os
from datetime import datetime

import ccxt.pro as ccxt
from ccxt.base.errors import PermissionDenied
from ccxt.base.exchange import ExchangeError, ExchangeNotAvailable
from dotenv import load_dotenv
from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        # Add numeric log level
        log_record["level"] = record.levelname


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = CustomJsonFormatter(timestamp=True)
handler.setFormatter(formatter)
logger.addHandler(handler)

data = {"/balance/USDT": 100000.0}

common_to_exchange = {
    "kucoin": {
        "GALA/USDT": "GALAX/USDT",
    }
}


def _common_symbol_to_exchange(symbol, exchange_id):
    if (
        common_to_exchange.get(exchange_id) is not None
        and common_to_exchange.get(exchange_id).get(symbol) is not None
    ):
        return common_to_exchange[exchange_id][symbol]
    return symbol


async def _watch_book_order(client_id, symbol):
    client = getattr(ccxt, client_id)()
    esymbol = _common_symbol_to_exchange(symbol, client_id)
    try:
        logger.debug(f"loading markets for {client_id}")
        attempts = [1, 2, 4, 8]
        while True:
            try:
                await client.load_markets()
                break
            except PermissionDenied as e:
                logger.info(
                    f"skipping {client_id}, permission denied",
                    extra={"exchange": client_id, "symbol": symbol},
                )
                return
            except ExchangeNotAvailable as e:
                logger.info(
                    f"skipping {client_id}, exchange not available",
                    extra={"exchange": client_id, "symbol": symbol},
                )
                return
            except Exception as e:
                logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')
                if len(attempts) == 0:
                    return
                logger.debug("retrying...")
                await asyncio.sleep(attempts[0])
                attempts = attempts[1:]
        if client.markets.get(esymbol) is None:
            logger.info(
                f"skipping {client_id}, does not support {symbol}",
                extra={"exchange": client_id, "symbol": symbol},
            )
            return
        logger.debug(
            f"loaded markets for {client_id}",
            extra={"exchange": client_id, "symbol": symbol},
        )
        attempts = [1, 2, 4, 8]
        while True:
            try:
                start = datetime.now()
                logger.debug(
                    f"loading book orders for {client_id}",
                    extra={"exchange": client_id, "symbol": symbol},
                )
                book_order = await client.watch_order_book(esymbol)
                end = datetime.now()
                logger.debug(
                    f"loaded book orders for {client_id} in {(end - start)}",
                    extra={"exchange": client_id, "symbol": symbol},
                )
                attempts = [1, 2, 4, 8]
            except ExchangeError as e:
                logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')
                break
            except Exception as e:
                logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')
                if len(attempts) == 0:
                    break
                logger.debug("retrying...")
                await asyncio.sleep(attempts[0])
                attempts = attempts[1:]
                continue
            data[f"/asks/{symbol}/{client_id}"] = book_order["asks"]
            data[f"/bids/{symbol}/{client_id}"] = book_order["bids"]
            await asyncio.sleep(1)
    except Exception as e:
        logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')
    finally:
        await client.close()


def _match_asks_bids(balance, symbol, buy_exchange, buy_asks, sell_exchange, sell_bids):
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


async def _watch_deals(symbol, clients, bot, chat_id):
    try:
        while True:
            logger.debug(f"checking deals {symbol}...", extra={"symbol": symbol})
            base_coin, quote_coin = symbol.split("/")
            balance = {
                base_coin: data.get(f"/balance/{base_coin}", 0.0),
                quote_coin: data.get(f"/balance/{quote_coin}", 0.0),
            }

            deals = []
            for buy_cilent_id, sell_client_id in [
                (a, b) for a in clients for b in clients if a != b
            ]:
                asks = data.get(f"/asks/{symbol}/{buy_cilent_id}")
                bids = data.get(f"/bids/{symbol}/{sell_client_id}")
                if asks is None:
                    continue
                if bids is None:
                    continue
                deals += [
                    _match_asks_bids(
                        balance, symbol, buy_cilent_id, asks, sell_client_id, bids
                    )
                ]
            deals = [deal for deal in deals if deal["profit"] > 0]
            logger.debug(f"found {len(deals)} deals", extra={"symbol": symbol})
            if len(deals) > 0:
                file_name = os.path.abspath(
                    f"data/deals_{symbol.replace('/', '-')}_{datetime.now().strftime('%Y-%m-%d')}.csv"
                )
                print_header = not os.path.exists(file_name)
                with open(file_name, "a") as f:
                    w = csv.writer(f)
                    if print_header:
                        w.writerow(
                           ["ts","symbol","profit","buy_exchange","buy_total_base","buy_total_quote","sell_exchange","sell_total_base","sell_total_quote"]
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
                        logger.info(
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
                            bot.send_message(chat_id=chat_id, text=deal_msg)
                        except Exception as e:
                            logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')

            await asyncio.sleep(0.5)

    except Exception as e:
        logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')


async def _run(symbols, exchanges, bot_token, bot_chat_id):
    async with Bot(bot_token) as bot:
        tasks = []
        for symbol in symbols:
            tasks += [_watch_deals(symbol, exchanges, bot, bot_chat_id)]
            for client_id in exchanges:
                tasks += [_watch_book_order(client_id, symbol)]
        await asyncio.gather(*tasks)


def _main():
    load_dotenv(override=True)
    symbols = os.getenv("SYMBOLS", "BTC/USDT")
    symbols = symbols.split(",")
    exchanges = os.getenv("EXCHANGES", ",".join(ccxt.exchanges))
    exchanges = exchanges.split(",")
    bot_token = os.getenv("BOT_TOKEN")
    bot_chat_id = os.getenv("BOT_CHAT_ID")
    logger.info(f"App initialized with {symbols} and {exchanges} exchanges")
    try:
        asyncio.run(_run(symbols, exchanges, bot_token, bot_chat_id))
        logger.info(f"App exited")
    except Exception as e:
        logger.info(f"App exited with error")
        logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')
        raise e


if __name__ == "__main__":
    _main()
