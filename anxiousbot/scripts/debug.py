import asyncio
import json
import os
from pprint import pprint

from anxiousbot.calculation_handler import CalculationHandler
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.exchange_handler import ExchangeHandler


async def _run():
    try:
        config_handler = ConfigHandler()
        exchange_handler = ExchangeHandler(config_handler)
        calc_handler = CalculationHandler(exchange_handler)

        client = await exchange_handler.setup_exchange("bitget")
        if not os.path.exists("./data/debug.json"):
            balance = await client.fetch_balance()
            trios = config_handler.parameters["exchanges"][client.id]["symbol_trios"]
            trios = [
                trio
                for trio in trios
                if (trio[0]["side"] == "buy" and trio[0]["symbol"].endswith("/USDT"))
                or (trio[0]["side"] == "sell" and trio[0]["symbol"].startswith("USDT/"))
            ]
            operations = trios[0]
            operations = [
                (client.id, operation["side"], operation["symbol"])
                for operation in operations
            ]
            operations = [
                (exchange, side, await client.fetch_order_book(symbol))
                for exchange, side, symbol in operations
            ]
            params = {
                "balance": {client.id: balance["free"]},
                "operations": [
                    {"exchange": exchange, "side": side, "order_book": order_book}
                    for exchange, side, order_book in operations
                ],
            }
            with open("./data/debug.json", "w") as f:
                json.dump(params, f, indent=2)
        with open("./data/debug.json", "r") as f:
            params = json.load(f)
        balance = params["balance"]
        operations = [
            (operation["exchange"], operation["side"], operation["order_book"])
            for operation in params["operations"]
        ]
        response = calc_handler.calculate(balance, operations)
        pprint(response)
    finally:
        await exchange_handler.aclose()


def _main():
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
