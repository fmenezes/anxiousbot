import asyncio
import json

import ccxt.pro as ccxt
from dotenv import load_dotenv


async def _exponential_backoff(fn, *args, **kwargs):
    backoff = [1, 2, 4, 8]
    last_exception = None
    for delay in backoff:
        try:
            return await fn(*args, **kwargs)
        except asyncio.CancelledError as e:
            raise e
        except Exception as e:
            await asyncio.sleep(delay)
            last_exception = e
    raise last_exception


async def _process_exchange(exchange, symbols):
    client = getattr(ccxt, exchange)()
    desc = client.describe()
    if desc.get("alias", False) == True:
        return None
    try:
        markets = await _exponential_backoff(client.load_markets)
        count = len([symbol for symbol in markets.keys() if symbol in symbols])
        if count == 0:
            return None
        all_methods = [
            "fetchOrderBooks",
            "fetch_order_books",
            "watchOrderBooks",
            "watch_order_books",
        ]
        batch_methods = [
            "fetchOrderBookForSymbols",
            "fetch_order_book_for_symbols",
            "watchOrderBookForSymbols",
            "watch_order_book_for_symbols",
        ]
        single_methods = [
            "fetchOrderBook",
            "fetch_order_book",
            "watchOrderBook",
            "watch_order_book",
        ]
        data = {
            "exchange": client.id,
            "mode": "none",
            "method": "fetch_order_book",
            "symbols": [symbol for symbol in markets.keys() if symbol in symbols],
            "limit": None,
        }

        for m in all_methods + batch_methods + single_methods:
            if desc["has"].get(m, False):
                try:
                    param = data["symbols"]
                    if m in single_methods:
                        param = param[0]
                    await getattr(client, m)(param)
                    data["method"] = m
                    break
                except:
                    continue
        if data["method"] in all_methods:
            data["mode"] = "all"
        if data["method"] in batch_methods:
            data["mode"] = "batch"
        if data["method"] in single_methods:
            data["mode"] = "single"
        return data
    except:
        return None
    finally:
        await client.close()


async def _run():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "GALA/USDT"]

    exchanges = [
        exchange
        for exchange in ccxt.exchanges
        if exchange
        not in [
            "bitfinex",
            "kucoinfutures",
            "poloniexfutures",
            "krakenfutures",
            "binancecoinm",
            "binanceus",
            "binanceusdm",
            "coinbaseinternational",
            "coinbaseexchange",
        ]
    ]

    tasks = [_process_exchange(exchange, symbols) for exchange in exchanges]
    results = await asyncio.gather(*tasks)
    results = [entry for entry in results if entry is not None]

    symbols_exchanges = {}
    for entry in results:
        for symbol in entry["symbols"]:
            if symbol not in symbols_exchanges:
                symbols_exchanges[symbol] = []
            symbols_exchanges[symbol] += [entry["exchange"]]
    config = {"dealer": {"symbols": symbols_exchanges}, "updater": results}
    with open(f"./config/local.json", "w") as f:
        json.dump(config, fp=f, indent=2)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
