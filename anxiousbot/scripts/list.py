import asyncio
import csv
import json
import os
import sys

import ccxt.pro as ccxt
from dotenv import load_dotenv


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
            print(e.with_traceback(None), file=sys.stderr)
        finally:
            await client.close()
    with open(file_path, "w") as f:
        print("symbol,count," + ",".join(ccxt.exchanges), file=f)
        for symbol, exchanges in symbols.items():
            row = f"{symbol},{len(exchanges)}"
            for exchange in ccxt.exchanges:
                if exchange in exchanges:
                    row += ",y"
                else:
                    row += ",n"
            print(row, file=f)


def _group(csv_file_path, json_file_path):
    with open(csv_file_path, "r") as f:
        reader = csv.reader(f)
        first_row = None
        data = []
        for row in reader:
            if first_row is None:
                first_row = row
                continue
            record = {"exchanges": []}
            for i in range(0, len(first_row)):
                if first_row[i] == "count":
                    row[i] = int(row[i])
                if row[i] == "y":
                    row[i] = True
                    record["exchanges"] += [first_row[i]]
                elif row[i] == "n":
                    row[i] = False
                record[first_row[i]] = row[i]
            record["exchanges"] = list(set(record["exchanges"]))
            data += [record]
        data.sort(key=lambda x: x["count"], reverse=True)
        data = [row for row in data if row["count"] > 1]
        data = [row for row in data if ":" not in row["symbol"]]
        groups = []
        max_items = data[0]["count"]
        while len(data) > 0:
            group = {
                "count": data[0]["count"],
                "symbols": [data[0]["symbol"]],
                "exchanges": data[0]["exchanges"],
            }
            data = data[1:]
            while group["count"] < max_items and len(data) > 0:
                last_row = data[len(data) - 1]
                if group["count"] + last_row["count"] > max_items:
                    break
                data = data[: len(data) - 1]
                group["symbols"] += [last_row["symbol"]]
                group["count"] += last_row["count"]
                group["exchanges"] += last_row["exchanges"]
                group["exchanges"] = list(set(group["exchanges"]))
            group["env"] = {
                "SYMBOLS": ",".join(group["symbols"]),
                "EXCHANGES": ",".join(group["exchanges"]),
            }
            groups += [group]
        with open(json_file_path, "w") as f:
            print(
                json.dumps({"count": len(groups), "groups": groups}, indent=2), file=f
            )


async def _run():
    csv_file_path = "./data/symbols.csv"
    if not os.path.exists(csv_file_path):
        await _generate_csv(csv_file_path)
    json_file_path = "./data/groups.json"
    if not os.path.exists(json_file_path):
        _group(csv_file_path, json_file_path)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
