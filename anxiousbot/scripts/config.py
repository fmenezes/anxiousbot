import asyncio
import copy
import json
import os
from glob import glob

from dotenv import load_dotenv


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


async def _run():
    with open(f"./config/symbols.json", "r") as f:
        symbol_list = json.load(f)
    filtered_symbol_list = _filter_symbols(symbol_list)
    data = _split_machines(filtered_symbol_list, 50)
    data = [",".join(symbols) for symbols in data]

    with open(f"./config/instances.json", "w") as f:
        json.dump(data, fp=f, indent=2)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
