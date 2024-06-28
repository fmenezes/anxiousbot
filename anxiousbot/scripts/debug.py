import asyncio
import os

import ccxt.pro as ccxt
import tabulate
from dotenv import load_dotenv


def _match_book_orders(book_orders):
    deals = []
    for a in book_orders:
        for b in book_orders:
            if b['name'] == a['name']:
                continue
            deal = _match_asks_bids(a["asks"], b["bids"])
            deal["symbol"] = a["symbol"]
            deal["buy"]["name"] = a["name"]
            deal["sell"]["name"] = b["name"]
            deals += [deal]

            deal = _match_asks_bids(b["asks"], a["bids"])
            deal["symbol"] = a["symbol"]
            deal["buy"]["name"] = b["name"]
            deal["sell"]["name"] = a["name"]
            deals += [deal]
    return [deal for deal in deals if deal['potential_profit'] > 0]


def _match_asks_bids(buy_asks, sell_bids):
    buy_index = 0
    sell_index = 0
    total_amount = 0
    potential_profit = 0.0

    sell_bids = sorted(sell_bids, key=lambda x: x[0], reverse=True)

    buy_price_max = buy_price_min = buy_asks[buy_index][0]
    sell_price_max = sell_price_min = sell_bids[sell_index][0]

    buy_orders = []
    sell_orders = []

    while buy_index < len(buy_asks) and sell_index < len(sell_bids):
        buy_price = buy_asks[buy_index][0]
        buy_amount = buy_asks[buy_index][1]
        sell_price = sell_bids[sell_index][0]
        sell_amount = sell_bids[sell_index][1]

        # Ensure buy price is less than or equal to sell price for a match
        if buy_price <= sell_price:
            buy_price_min = min(buy_price_min, buy_price)
            buy_price_max = max(buy_price_max, buy_price)

            sell_price_min = min(sell_price_min, sell_price)
            sell_price_max = max(sell_price_max, sell_price)

            matched_amount = min(buy_amount, sell_amount)
            total_amount += matched_amount
            potential_profit += matched_amount * (sell_price - buy_price)

            buy_orders += [buy_price, matched_amount]
            sell_orders += [sell_price, matched_amount]

            # Update the amounts
            buy_asks[buy_index][1] -= matched_amount
            sell_bids[sell_index][1] -= matched_amount

            # Remove orders that are fully matched
            if buy_asks[buy_index][1] == 0:
                buy_index += 1
            if sell_bids[sell_index][1] == 0:
                sell_index += 1
        else:
            # If the prices don't match, exit the loop
            break

    return {
        "total_amount": total_amount,
        "potential_profit": potential_profit,
        "buy": {
            "orders": buy_orders,
            "price": {"min": buy_price_min, "max": buy_price_max},
        },
        "sell": {
            "orders": sell_orders,
            "price": {"min": sell_price_min, "max": sell_price_max},
        },
    }


def _print_book_orders(book_orders):
    no_lines = 20

    red_color = "\033[91m"
    green_color = "\033[92m"
    no_color = "\033[0m"

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
                    f"{red_color}{b}{no_color}    {green_color}{a}{no_color}"
                    for b, a in zip(table_bids, table_asks)
                ]
            )
        )

        tabs += [table_combined.split("\n")]

    os.system("cls" if os.name == "nt" else "clear")

    print(book_orders[0]["symbol"])
    print()
    lines = "\n".join(["    ".join(columns) for columns in zip(*tabs)])
    print(lines)


def _print_deals(deals):
    print(tabulate.tabulate(
        [[deal['total_amount'], deal['potential_profit'], deal['buy']
            ['name'], deal['sell']['name']] for deal in deals],
            headers=("Total Amount", "Potential Profit", "Buy Exchange", "Sell Exchange")
    ))

async def _run():
    clients = [ccxt.binance(), ccxt.kucoin(), ccxt.bitget()]

    symbol = "BTC/USDT"
    try:
        while True:
            book_orders = []
            for client in clients:
                book_order = await client.watch_order_book(symbol)
                book_orders += [
                    {
                        "name": client.name,
                        "symbol": symbol,
                        "asks": book_order["asks"],
                        "bids": book_order["bids"],
                    }
                ]

            _print_book_orders(book_orders)

            print()
            deals = _match_book_orders(book_orders)
            _print_deals(deals)

            await asyncio.sleep(0.5)
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
