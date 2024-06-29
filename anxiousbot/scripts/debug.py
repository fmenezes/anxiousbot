import asyncio
import os
from datetime import datetime

import ccxt.pro as ccxt
import tabulate
from dotenv import load_dotenv


def _match_book_orders(book_orders):
    deals = []
    balance = {
        'USDT': 1000.0,
    }
    for buy_exchange in book_orders:
        for sell_exchange in book_orders:
            if sell_exchange["id"] == buy_exchange["id"]:
                continue
            deal = _match_asks_bids(
                balance=balance, symbol=buy_exchange["symbol"], buy_name=buy_exchange["name"], buy_asks=buy_exchange["asks"], sell_name=sell_exchange["name"], sell_bids=sell_exchange["bids"])
            deals += [deal]

    return [deal for deal in deals if deal["potential_profit"] > 3]


def _match_asks_bids(balance, symbol, buy_name, buy_asks, sell_name, sell_bids):
    base_coin, quote_coin = symbol.split('/')

    buy_index = 0
    sell_index = 0

    buy_price_max = buy_price_min = buy_asks[buy_index][0]
    sell_price_max = sell_price_min = sell_bids[sell_index][0]

    buy_orders = []
    sell_orders = []

    buy_total = 0
    sell_total = 0

    while balance[quote_coin] > 0 and buy_index < len(buy_asks) and sell_index < len(sell_bids):
        buy_price = buy_asks[buy_index][0]
        buy_amount_base = buy_asks[buy_index][1]
        buy_amount_quote = buy_price * buy_amount_base
        sell_price = sell_bids[sell_index][0]
        sell_amount_base = sell_bids[sell_index][1]
        sell_amount_quote = sell_price * sell_amount_base
        current_balance_quote = balance[quote_coin]

        # Ensure buy price is less than or equal to sell price for a match
        if buy_price < sell_price:
            buy_price_min = min(buy_price_min, buy_price)
            buy_price_max = max(buy_price_max, buy_price)

            sell_price_min = min(sell_price_min, sell_price)
            sell_price_max = max(sell_price_max, sell_price)

            matched_amount_quote = min(
                buy_amount_quote, sell_amount_quote, current_balance_quote)

            if matched_amount_quote > 0:
                matched_amount_base = matched_amount_quote / buy_price
                buy_orders += [buy_price, matched_amount_base]
                sell_orders += [sell_price, matched_amount_base]

                buy_total += matched_amount_quote
                sell_total += (matched_amount_base * sell_price)

                # Update the amounts
                buy_asks[buy_index][1] -= matched_amount_base
                sell_bids[sell_index][1] -= matched_amount_base
                balance[quote_coin] -= matched_amount_quote
                if base_coin not in balance:
                    balance[base_coin] = 0
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
        "potential_profit": (sell_total - buy_total),
        "symbol": symbol,
        "buy": {
            "name": buy_name,
            "orders": buy_orders,
            "price": {"min": buy_price_min, "max": buy_price_max},
            "total": buy_total,
        },
        "sell": {
            "name": sell_name,
            "orders": sell_orders,
            "price": {"min": sell_price_min, "max": sell_price_max},
            "total": sell_total,
        },
    }


def _print_book_orders(book_orders):
    no_lines = 5

    red_color = "\033[91m"
    green_color = "\033[92m"
    no_color = "\033[0m"

    if len(book_orders) <= 0:
        return

    tabs = []
    for book_order in book_orders:
        table_bids = tabulate.tabulate(
            [[order[0], order[1]] for order in book_order["bids"][0:no_lines]],
            headers=["Price", "Quantity"],
            tablefmt="pipe",
            floatfmt=".8f",
        )
        table_asks = tabulate.tabulate(
            [[order[0], order[1]] for order in book_order["asks"][0:no_lines]],
            headers=["Price", "Quantity"],
            tablefmt="pipe",
            floatfmt=".8f",
        )
        table_bids = table_bids.split("\n")
        table_asks = table_asks.split("\n")

        table_combined = (
            f"{book_order['name']}{' ' * (4 + len(table_asks[0]) + len(table_bids[0]) - len(book_order['name']))}\n{red_color}ASKS{no_color}{' ' * len(table_asks[0])}{green_color}BIDS{no_color}{' ' * (len(table_bids[0])-4)}\n"
            + "\n".join(
                [
                    f"{red_color}{asks}{no_color}    {green_color}{bids}{no_color}"
                    for bids, asks in zip(table_bids, table_asks)
                ]
            )
        )

        tabs += [table_combined.split("\n")]

    print()
    print(book_orders[0]["symbol"])
    lines = "\n".join(["    ".join(columns) for columns in zip(*tabs)])
    print(lines)


def _print_deals(deals):
    print("Deals")
    print(
        tabulate.tabulate(
            [
                [
                    deal["ts"],
                    deal["symbol"],
                    deal["buy"]["name"],
                    deal["buy"]["total"],
                    deal["sell"]["name"],
                    deal["sell"]["total"],
                    deal["potential_profit"],
                ]
                for deal in deals
            ],
            headers=(
                "Timestamp",
                "Symbol",
                "Buy Exchange",
                "Total Buy",
                "Sell Exchange",
                "Total Sell",
                "Potential Profit",
            ),
            floatfmt=".8f",
        )
    )


common_to_exchange = {
    "kucoin": {
        "GALA/USDT": "GALAX/USDT",
    }
}

exchange_to_common = {
    "kucoin": {
        "GALAX/USDT": "GALA/USDT",
    }
}

def _common_symbol_to_exchange(symbol, exchange_id):
    if common_to_exchange.get(exchange_id) is not None and common_to_exchange.get(exchange_id).get(symbol) is not None:
        return common_to_exchange[exchange_id][symbol]
    return symbol


def _exchange_symbol_to_common(symbol, exchange_id):
    if exchange_to_common.get(exchange_id) is not None and exchange_to_common.get(exchange_id).get(symbol) is not None:
        return exchange_to_common[exchange_id][symbol]
    return symbol

book_orders_per_symbol = {}
deals = []

async def _watch_book_order(client, symbol):
    global book_orders_per_symbol
    while True:
        try:
            book_order = await client.watch_order_book(symbol)
        except Exception:
            await asyncio.sleep(1)
            continue
        book_order["id"] = client.id
        book_order["name"] = client.name
        if symbol not in book_orders_per_symbol:
            book_orders_per_symbol[symbol] = {}
        book_orders_per_symbol[symbol][client.id] = book_order
        _process_book_orders()
        await asyncio.sleep(1)


def _process_book_orders():
    global deals
    os.system("cls" if os.name == "nt" else "clear")
    for data in book_orders_per_symbol.values():
        book_orders = list(data.values())
        _print_book_orders(book_orders)
        if len(book_orders) > 1:
            deals += _match_book_orders(book_orders)
    while len(deals) > 30:
        deals = deals[1:]

    print()
    _print_deals(deals)

async def _run():
    clients = [
        ccxt.binance(),
        ccxt.bitget(),
        ccxt.kucoin(),
        ccxt.gateio(),
        ccxt.mexc(),
    ]

    for client in clients:
        await client.load_markets()

    symbols = ["BTC/USDT"]
    try:
        tasks = []
        for symbol in symbols:
            for client in clients:
                tasks += [_watch_book_order(
                    client, _common_symbol_to_exchange(symbol, client.id)
                )]
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    finally:
        for client in clients:
            await client.close()


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
