import asyncio
import csv
import json
import os
from collections import Counter
from glob import glob

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
        "method": "fetch_order_book",
        "symbols": [],
        "limit": _limit(client.id),
    }
    try:
        await _exponential_backoff(client.load_markets)
        data["symbols"] = list(client.markets.keys())
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


def _filter_symbols(data):
    marketcap = _convert(list(_read_csv("./data/marketcap.csv")), "Symbol")

    symbols = list(set([symbol for entry in data for symbol in entry["symbols"]]))
    print(f"all symbols: {len(symbols)}")
    symbols = [
        {
            "symbol": symbol,
            "basecoin": symbol.split("/")[0],
            "quotecoin": symbol.split("/")[1],
        }
        for symbol in symbols
        if symbol.endswith("/USDT")
    ]
    print(f"symbols ending with /USDT: {len(symbols)}")
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
    symbols = [entry for entry in symbols if len(entry["exchanges"]) > 1]
    print(f"symbols with more than one exchange: {len(symbols)}")
    symbols = [
        {"marketcap": marketcap.get(entry["basecoin"], {}).get("#"), **entry}
        for entry in symbols
    ]
    for entry in symbols:
        try:
            entry["marketcap"] = int(entry["marketcap"])
        except:
            entry["marketcap"] = None
    symbols = [entry for entry in symbols if entry["marketcap"] is not None]
    print(f"symbols with a marketcap ranking: {len(symbols)}")
    symbols.sort(key=lambda x: x["marketcap"])
    symbols = [entry for entry in symbols][:1000]
    return symbols


def _split_batches(data):
    for entry in data:
        if entry["mode"] == "single":
            for symbol in entry["symbols"]:
                yield {**entry, "symbols": [symbol]}
        elif entry["mode"] == "all":
            yield entry
        elif entry["mode"] == "batch":
            if entry["limit"] is None:
                yield entry
            else:
                symbol_list = entry["symbols"]
                while len(symbol_list) > 0:
                    yield {**entry, "symbols": symbol_list[: entry["limit"]]}
                    symbol_list = symbol_list[entry["limit"] + 1 :]


def _min_machines(data):
    entries = [entry["exchange"] for entry in data if entry["mode"] == "batch"]
    counter = Counter(entries)
    return max(counter.values())


def _filter_symbols_in_exchanges(data, filtered_symbols):
    for entry in data:
        entry["symbols"] = [
            symbol for symbol in entry["symbols"] if symbol in filtered_symbols
        ]
        yield entry


def _filter_exchanges(data):
    print(f"total exchanges: {len(data)}")
    data = [entry for entry in data if len(entry["symbols"]) >= 5]
    print(f"exchanges with at least 5 symbols: {len(data)}")
    return data


def _split_machines(data, count=None):
    if count is None:
        count = _min_machines(data)
    result = []
    machine_id = 0
    data.sort(
        key=lambda x: (
            f'{x["mode"]}_{x["symbols"][0]}_{x["exchange"]}'
            if x["mode"] == "single"
            else f'{x["mode"]}_{x["exchange"]}'
        )
    )
    for entry in data:
        if len(result) <= machine_id:
            result.append([entry])
        else:
            result[machine_id].append(entry)
        machine_id += 1
        if machine_id == count:
            machine_id = 0
    return result


def _split_dict(data, count):
    result = []
    index = 0
    for key, value in data.items():
        if index >= count:
            index = 0
        if len(result) <= index:
            result += [{}]
        result[index][key] = value
        index += 1
    return result


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
    data = [entry for entry in data if entry is not None]
    filtered_symbol_list = _filter_symbols(data)
    filtered_symbols = [entry["symbol"] for entry in filtered_symbol_list]
    data = list(_filter_symbols_in_exchanges(data, filtered_symbols))
    data = _filter_exchanges(data)
    data = list(_split_batches(data))
    machine_count = 45
    data = _split_machines(data, machine_count)
    symbols_exchanges = dict(
        [(entry["symbol"], entry["exchanges"]) for entry in filtered_symbol_list]
    )
    symbols_exchanges = _split_dict(symbols_exchanges, machine_count)
    data = [{"dealer": {"symbols": {}}, "updater": entry} for entry in data]
    for i in range(len(symbols_exchanges)):
        data[i]["dealer"]["symbols"] = symbols_exchanges[i]

    for filename in glob("./config/config-*.json"):
        os.remove(filename)

    for i in range(len(data)):
        with open(f"./config/config-{i}.json", "w") as f:
            json.dump(data[i], fp=f, indent=2)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
