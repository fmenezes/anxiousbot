import asyncio
import csv
import json

import ccxt.pro as ccxt
from dotenv import load_dotenv
from coinmarketcapapi import CoinMarketCapAPI


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
        "symbol_trios": [],
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
        data["symbols"].sort()
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
        if len(data["symbols"]) > 0:
            for lside, lsymbol, mside, msymbol, rside, rsymbol in find_trios(
                data["symbols"]
            ):
                data["symbol_trios"] += [
                    [
                        {"side": lside, "symbol": lsymbol},
                        {"side": mside, "symbol": msymbol},
                        {"side": rside, "symbol": rsymbol},
                    ]
                ]
    except Exception as e:
        return None
    finally:
        await client.close()
    return data


def _all_symbols(marketcap, data):
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
        {"marketcap": marketcap.get(entry["basecoin"]), **entry}
        for entry in symbols
    ]
    for entry in symbols:
        try:
            entry["marketcap"] = int(entry["marketcap"])
        except:
            entry["marketcap"] = None

    return symbols


def matcher_coin(symbol, side, inverse=False):
    base, quote = symbol.split("/")
    if side == "buy":
        if inverse:
            return quote
        else:
            return base
    else:
        if inverse:
            return base
        else:
            return quote


def find_lsymbols(symbols):
    sides = ["buy", "sell"]
    for lsymbol in symbols:
        for lside in sides:
            yield lside, lsymbol


def find_msymbols(symbols, data):
    for lside, lsymbol in data:
        lcoin = matcher_coin(lsymbol, lside)
        for msymbol in [symbol for symbol in symbols if symbol.startswith(lcoin + "/")]:
            yield lside, lsymbol, "sell", msymbol
        for msymbol in [symbol for symbol in symbols if symbol.endswith("/" + lcoin)]:
            yield lside, lsymbol, "buy", msymbol


def find_rsymbols(symbols, data):
    for lside, lsymbol, mside, msymbol in data:
        startcoin = matcher_coin(lsymbol, lside, True)
        mcoin = matcher_coin(msymbol, mside)
        rsymbol = f"{startcoin}/{mcoin}"
        if rsymbol in symbols:
            yield lside, lsymbol, mside, msymbol, "buy", rsymbol
        rsymbol = f"{mcoin}/{startcoin}"
        if rsymbol in symbols:
            yield lside, lsymbol, mside, msymbol, "sell", rsymbol


def find_trios(symbols):
    return find_rsymbols(symbols, find_msymbols(symbols, find_lsymbols(symbols)))


async def _run():
    cmc = CoinMarketCapAPI(api_key=os.getenv("COIN_MARKETCAP_API_KEY"))
    marketcap_data = cmc.cryptocurrency_map()
    marketcap = dict([(entry["symbol"], entry["rank"]) for entry in marketcap_data.data])

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
    exchange_list = _convert(data, "exchange")
    parameters = {"exchanges": exchange_list}
    symbol_list = _all_symbols(marketcap,
        [
            {
                "exchange": entry["exchange"],
                "symbols": entry["symbols"],
            }
            for entry in data
        ]
    )
    symbol_list = _convert(symbol_list, "symbol")
    parameters["symbols"] = symbol_list
    with open(f"./config/parameters.json", "w") as f:
        json.dump(parameters, fp=f, indent=2, sort_keys=True)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
