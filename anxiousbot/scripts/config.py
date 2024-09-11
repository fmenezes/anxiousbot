import asyncio
import json
import os

import ccxt.pro as ccxt
from coinmarketcapapi import CoinMarketCapAPI
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
            for lside, lsymbol, mside, msymbol, rside, rsymbol in _find_trios(
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
        {"marketcap": marketcap.get(entry["basecoin"]), **entry} for entry in symbols
    ]
    for entry in symbols:
        try:
            entry["marketcap"] = int(entry["marketcap"])
        except:
            entry["marketcap"] = None

    return symbols


def _matcher_coin(symbol, side, inverse=False):
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


def _find_lsymbols(symbols):
    sides = ["buy", "sell"]
    for lsymbol in symbols:
        for lside in sides:
            yield lside, lsymbol


def _find_msymbols(symbols, data):
    for lside, lsymbol in data:
        lcoin = _matcher_coin(lsymbol, lside)
        for msymbol in [symbol for symbol in symbols if symbol.startswith(lcoin + "/")]:
            yield lside, lsymbol, "sell", msymbol
        for msymbol in [symbol for symbol in symbols if symbol.endswith("/" + lcoin)]:
            yield lside, lsymbol, "buy", msymbol


def _find_rsymbols(symbols, data):
    for lside, lsymbol, mside, msymbol in data:
        startcoin = _matcher_coin(lsymbol, lside, True)
        mcoin = _matcher_coin(msymbol, mside)
        rsymbol = f"{startcoin}/{mcoin}"
        if rsymbol in symbols:
            yield lside, lsymbol, mside, msymbol, "buy", rsymbol
        rsymbol = f"{mcoin}/{startcoin}"
        if rsymbol in symbols:
            yield lside, lsymbol, mside, msymbol, "sell", rsymbol


def _find_trios(symbols):
    return _find_rsymbols(symbols, _find_msymbols(symbols, _find_lsymbols(symbols)))


def _marketcap():
    cmc = CoinMarketCapAPI(api_key=os.getenv("COIN_MARKETCAP_API_KEY"))
    marketcap_data = cmc.cryptocurrency_map()
    return dict([(entry["symbol"], entry["rank"]) for entry in marketcap_data.data])


async def _fetch_parameters():
    marketcap = _marketcap()

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
    symbol_list = _all_symbols(
        marketcap,
        [
            {
                "exchange": entry["exchange"],
                "symbols": entry["symbols"],
            }
            for entry in data
        ],
    )
    symbol_list = _convert(symbol_list, "symbol")
    parameters["symbols"] = symbol_list
    return parameters


def _filter_symbols(symbols):
    print(f"all symbols: {len(symbols)}")
    symbols = [
        entry for key, entry in symbols.items() if entry.get("quotecoin") == "USDT"
    ]
    print(f"symbols ending with /USDT: {len(symbols)}")
    symbols = [entry for entry in symbols if len(entry["exchanges"]) > 1]
    print(f"symbols with more than one exchange: {len(symbols)}")
    symbols = [entry for entry in symbols if entry["marketcap"] is not None]
    print(f"symbols with a marketcap ranking: {len(symbols)}")
    symbols.sort(key=lambda x: x["marketcap"])
    symbols = [entry for entry in symbols][:200]
    return symbols


def _split_machines(d, count=None):
    result = []
    machine_id = 0
    data = copy.deepcopy(d)
    data.sort(key=lambda x: len(x["exchanges"]), reverse=True)
    first = True
    while len(data) > 0:
        if first:
            new_item = data[0]
            data = data[1:]
        else:
            new_item = data[len(data) - 1]
            data = data[: len(data) - 1]
        new_item = new_item["symbol"]
        if len(result) <= machine_id:
            result.append([new_item])
        else:
            result[machine_id].append(new_item)
        machine_id += 1
        if machine_id == count:
            machine_id = 0
            first = not first
    return result


async def _process_instances(parameters):
    filtered_symbol_list = _filter_symbols(parameters.get("symbols"))
    data = _split_machines(filtered_symbol_list, 50)
    data = [",".join(symbols) for symbols in data]
    return data


async def _processs_trios(parameters):
    marketcap = _marketcap()
    data = dict(
        [(key, value["symbol_trios"]) for key, value in parameters["exchanges"].items()]
    )
    data = dict(
        [
            (
                exchange,
                [
                    {"trio": operations}
                    for operations in trios
                    if (
                        (
                            operations[0]["side"] == "buy"
                            and operations[0]["symbol"].endswith("/USDT")
                        )
                        or (
                            operations[0]["side"] == "sell"
                            and operations[0]["symbol"].startswith("USDT/")
                        )
                    )
                ],
            )
            for exchange, trios in data.items()
        ]
    )
    for exchange, entries in data.items():
        for entry in entries:
            entry["coins"] = list(
                set(
                    [
                        coin
                        for trio in entry["trio"]
                        for coin in trio["symbol"].split("/")
                    ]
                )
            )
            entry["score"] = sum(
                [marketcap.get(coin, 10000) for coin in entry["coins"]]
            )
        entries.sort(key=lambda x: x["score"])
        entries = entries[:50]
        data[exchange] = [entry["trio"] for entry in entries]
    return data


async def _run():
    if os.path.exists("./config/parameters.json"):
        with open("./config/parameters.json", "r") as f:
            parameters = json.load(f)
    else:
        parameters = await _fetch_parameters()
        with open(f"./config/parameters.json", "w") as f:
            json.dump(parameters, fp=f, indent=2, sort_keys=True)
    if not os.path.exists("./config/instances.json"):
        instances = await _process_instances(parameters)
        with open(f"./config/instances.json", "w") as f:
            json.dump(instances, fp=f, indent=2, sort_keys=True)
    if not os.path.exists("./config/trios.json"):
        trios = await _processs_trios(parameters)
        with open(f"./config/trios.json", "w") as f:
            json.dump(trios, fp=f, indent=2, sort_keys=True)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
