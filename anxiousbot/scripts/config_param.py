import asyncio
import csv
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


def _read_csv(file_path):
    first_row = None
    with open(file_path, "r") as f:
        for row in csv.reader(f):
            if first_row is None:
                first_row = row
                continue
            record = {}
            for i in range(0, len(row)):
                record[first_row[i]] = row[i]
            yield record


def _convert(rows, key):
    data = {}
    for row in rows:
        data[row[key]] = row
    return data


def _limit(exchange):
    match exchange:
        case "binance":
            return 200
        case "kucoin":
            return 100
        case "bitmart":
            return 20
        case "bybit":
            return 10
        case "coinbase":
            return 10
    return None


async def _process_exchange(exchange):
    client = getattr(ccxt, exchange)()
    desc = client.describe()
    if desc.get("alias", False) == True:
        return None
    data = {
        "exchange": client.id,
        "mode": "none",
        "describe": {
            "has": desc.get("has"),
            "options": desc.get("options"),
            "fees": desc.get("fees"),
            "commonCurrencies": desc.get("commonCurrencies"),
        },
        "method": "fetch_order_book",
        "symbols": [],
        "limit": _limit(client.id),
    }
    try:
        await _exponential_backoff(client.load_markets)
        data["symbols"] = list(
            [
                key
                for key, value in client.markets.items()
                if value["spot"] == True and value["active"] == True
            ]
        )
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
        for m in all_methods + batch_methods + single_methods:
            if desc["has"].get(m, False):
                try:
                    param = data["symbols"]
                    if m in single_methods:
                        param = param[0]
                        await getattr(client, m)(param)
                    elif m in batch_methods:
                        param = param[0:5]  # testing batching
                        await getattr(client, m)(param)
                    else:
                        await getattr(client, m)()
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
    except Exception as e:
        return None
    finally:
        await client.close()
    return data


def _all_symbols(data):
    marketcap = _convert(list(_read_csv("./data/marketcap.csv")), "Symbol")

    symbols = list(set([symbol for entry in data for symbol in entry["symbols"]]))
    print(f"all symbols: {len(symbols)}")
    symbols = [
        {
            "symbol": symbol,
            "basecoin": symbol.split("/")[0] if "/" in symbol else None,
            "quotecoin": symbol.split("/")[1] if "/" in symbol else None,
        }
        for symbol in symbols
    ]
    symbols = [
        {
            "exchanges": [
                data_entry["exchange"]
                for data_entry in data
                if entry["symbol"] in data_entry["symbols"]
            ],
            **entry,
        }
        for entry in symbols
    ]
    symbols = [
        {"marketcap": marketcap.get(entry["basecoin"], {}).get("#"), **entry}
        for entry in symbols
    ]
    for entry in symbols:
        try:
            entry["marketcap"] = int(entry["marketcap"])
        except:
            entry["marketcap"] = None

    return symbols


async def _run():
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
    tasks = []
    for exchange in exchanges:
        tasks += [_process_exchange(exchange)]

    data = await asyncio.gather(*tasks)
    data = [entry for entry in data if entry is not None and len(entry["symbols"]) > 0]
    with open(f"./config/exchanges.json", "w") as f:
        json.dump(_convert(data, "exchange"), fp=f, indent=2)
    for entry in data:
        del entry["describe"]
    symbol_list = _all_symbols(data)
    with open(f"./config/symbols.json", "w") as f:
        json.dump(_convert(symbol_list, "symbol"), fp=f, indent=2)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
