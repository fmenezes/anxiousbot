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
    except:
        return None
    finally:
        await client.close()

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
        "symbols": [symbol for symbol in markets.keys() if symbol in symbols],
        "limit": None,
    }

    for m in all_methods + batch_methods + single_methods:
        if desc["has"].get(m, False):
            data["method"] = m
            break
    if data["method"] in all_methods:
        data["mode"] = "all"
    if data["method"] in batch_methods:
        data["mode"] = "batch"
    if data["method"] in single_methods:
        data["mode"] = "single"
    return data

async def _run():
    symbols = ['BTC/USDT', 'ETH/USDT', 'ETH/USDT', 'SOL/USDT', 'GALA/USDT']

    tasks = [_process_exchange(exchange, symbols) for exchange in ccxt.exchanges]
    results = await asyncio.gather(*tasks)
    results = [entry for entry in results if entry is not None]
    
    symbols_exchanges = {}
    for entry in results:
        for symbol in entry['symbols']:
            if symbol not in symbols_exchanges:
                symbols_exchanges[symbol] = []
            symbols_exchanges[symbol] += [entry['exchange']]
    config = {'dealer': symbols_exchanges, 'updater': results}
    with open(f"./config/local.json", "w") as f:
        json.dump(config, fp=f, indent=2)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
