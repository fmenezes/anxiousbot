import asyncio
import traceback
import sys
import os
from datetime import datetime

import ccxt.pro as ccxt
from ccxt.base.exchange import ExchangeError
import tabulate
from dotenv import load_dotenv
import logging

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

data = {
    "/balance/USDT": 100000.0
}

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
        logger.info(f"loading markets for {client_id}")
        await client.load_markets()
        if client.markets.get(esymbol) is None:
            logger.info(f"skipping {client_id}, does not support {symbol}")
            return
        logger.info(f"loaded markets for {client_id}")
        while True:
            try:
                logger.info(f"loading book orders for {client_id}")
                book_order = await client.watch_order_book(esymbol)
                logger.info(f"loaded book orders for {client_id}")
            except ExchangeError as e:
                logger.error(f"error: [{type(e).__name__}] {str(e)}")
                logger.error(traceback.format_exc())
                break
            except Exception as e:
                logger.error(f"error: [{type(e).__name__}] {str(e)}")
                e.with_traceback()
                logger.info('retrying...')
                await asyncio.sleep(1)
                continue
            data[f'/asks/{symbol}/{client_id}'] = book_order['asks']
            data[f'/bids/{symbol}/{client_id}'] = book_order['bids']
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"error: [{type(e).__name__}] {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        await client.close()

def _calculate_buy(symbol, exchange_id):
    base_coin, quote_coin = symbol.split("/")

    balance = {
        quote_coin: data.get(f'/balance/{quote_coin}', 0.0),
        base_coin: data.get(f'/balance/{base_coin}', 0.0),
    }
    buy_asks = data.get(f'/asks/{symbol}/{exchange_id}', [])
    buy_index = 0
    buy_orders = []
    buy_total = 0

    while (
        balance[quote_coin] > 0
        and buy_index < len(buy_asks)
    ):
        buy_price = buy_asks[buy_index][0]
        buy_amount_base = buy_asks[buy_index][1]
        buy_amount_quote = buy_price * buy_amount_base
        current_balance_quote = balance[quote_coin]

        matched_amount_quote = min(
            buy_amount_quote, current_balance_quote
        )

        if matched_amount_quote > 0:
            matched_amount_base = matched_amount_quote / buy_price
            buy_orders += [buy_price, matched_amount_base]

            buy_total += matched_amount_quote

            # Update the amounts
            buy_asks[buy_index][1] -= matched_amount_base
            balance[quote_coin] -= matched_amount_quote
            balance[base_coin] += matched_amount_base

        # Remove orders that are fully matched
        if buy_asks[buy_index][1] <= 0:
            buy_index += 1

    return {
        "symbol": symbol,
        "exchange": exchange_id,
        "orders": buy_orders,
        "total": buy_total,
        "balance": balance,
    }

def _calculate_sell(symbol, exchange_id, balance):
    base_coin, quote_coin = symbol.split("/")

    sell_bids = data.get(f'/bids/{symbol}/{exchange_id}', [])
    sell_index = 0
    sell_orders = []
    sell_total = 0

    while (
        balance[base_coin] > 0
        and sell_index < len(sell_bids)
    ):
        sell_price = sell_bids[sell_index][0]
        sell_amount_base = sell_bids[sell_index][1]
        current_balance_base = balance[base_coin]

        matched_amount_base = min(
            sell_amount_base, current_balance_base
        )

        if matched_amount_base > 0:
            matched_amount_quote = matched_amount_base * sell_price
            sell_orders += [sell_price, matched_amount_base]

            sell_total += matched_amount_quote

            # Update the amounts
            sell_bids[sell_index][1] -= matched_amount_base
            balance[quote_coin] += matched_amount_quote
            balance[base_coin] -= matched_amount_base

        # Remove orders that are fully matched
        if sell_bids[sell_index][1] <= 0:
            sell_index += 1

    return {
        "symbol": symbol,
        "exchange": exchange_id,
        "orders": sell_orders,
        "total": sell_total,
        "balance": balance,
    }

async def _watch_deals(symbol, clients):
    try:
        file_name = os.path.abspath(f'data/deals_{symbol.replace('/', '-')}_{datetime.now().strftime("%Y-%m-%d")}.csv')
        if not os.path.exists(file_name):
            with open(file_name, 'w') as f:
                f.write('ts,symbol,profit,buy_exchange,buy_total,sell_exchange,sell_total\n')
        while True:
            logger.info(f'checking deals {symbol}...')
            best_buy = None
            best_sell = None
            for client_id in clients:
                buy = _calculate_buy(symbol, client_id)
                if best_buy is None or best_buy['total'] < buy['total']:
                    best_buy = buy
            for client_id in clients:
                if best_buy['exchange'] == client_id:
                    continue
                sell = _calculate_sell(symbol, client_id, best_buy['balance'])
                if best_sell is None or best_sell['total'] < sell['total']:
                    best_sell = sell
            deal = {
                "profit": (best_sell['total'] - best_buy['total']),
                "symbol": symbol,
                "buy": best_buy,
                "sell": best_sell,
            }
            if deal['profit'] > 0:
                with open(file_name, 'a') as f:
                    row = [datetime.now(),deal['symbol'],deal['profit'],deal['buy']['exchange'],deal['buy']['total'],deal['sell']['exchange'],deal['sell']['total']]
                    row = [str(c) for c in row]
                    f.write(','.join(row) + '\n')
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"error: [{type(e).__name__}] {str(e)}")
        logger.error(traceback.format_exc())


async def _run():
    clients = ccxt.exchanges

    symbols = ["ETH/USDT","BTC/USDT"]
    tasks = []
    for symbol in symbols:
        tasks += [_watch_deals(symbol, clients)]
        for client_id in clients:
            tasks += [_watch_book_order(client_id, symbol)]
    await asyncio.gather(*tasks)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
