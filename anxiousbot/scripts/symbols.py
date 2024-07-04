import asyncio
import os
import csv
import sys

import ccxt.pro as ccxt

async def _generate_csv(file_path):
    symbols = {}
    i = 1
    for exchange in ccxt.exchanges:
        print(f"{i} / {len(ccxt.exchanges)}", file=sys.stderr)
        i += 1
        client_cls = getattr(ccxt, exchange)
        client = client_cls()
        try:
            markets = await client.load_markets()
            for symbol in list(markets.keys()):
                if symbol not in symbols:
                    symbols[symbol] = []
                symbols[symbol] += [exchange]
        except Exception as e:
            print(e, file=sys.stderr)
        finally:
            await client.close()
    with open(file_path, "w") as f:
        w = csv.writer(f)
        w.writerow(["symbol","count"] + ccxt.exchanges)
        for symbol, exchanges in symbols.items():
            row = [symbol,len(exchanges)]
            for exchange in ccxt.exchanges:
                if exchange in exchanges:
                    row += ["y"]
                else:
                    row += ["n"]
            w.writerow(row)


async def _run():
    file_path = "./data/symbols.csv"
    if os.path.exists(file_path):
        return
    await _generate_csv(file_path)


def _main():
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
