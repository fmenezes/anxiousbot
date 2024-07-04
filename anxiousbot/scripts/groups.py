import asyncio
import csv
import json
import os
import sys

import ccxt.pro as ccxt
from dotenv import load_dotenv


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


def _group(symbols_file_path, marketcap_file_path, out, json_out):
    marketcap = _convert(list(_read_csv(marketcap_file_path)), 'Symbol')
    
    symbols = list(_read_csv(symbols_file_path))

    rows = []
    for symbol in symbols:
        if ':' in symbol['symbol']:
            print(f"{symbol['symbol']} does not contain format BASECOINT/QUOTECOIN", file=sys.stderr)
            continue
        coins = symbol['symbol'].split('/')
        if len(coins) != 2:
            print(f"{symbol['symbol']} does not contain format BASECOINT/QUOTECOIN", file=sys.stderr)
            continue
        base_coin = coins[0]
        quote_coin = coins[1]
        if quote_coin != 'USDT':
            print(f"{symbol['symbol']} does not pair with USDT", file=sys.stderr)
            continue
        symbol['exchanges'] = []
        for key in list(symbol.keys())[2:]:
            if symbol[key] == 'y':
                symbol['exchanges'] += [key]
        if len(symbol['exchanges']) < 2:
            print(f"{symbol['symbol']} supports only one exchange: {symbol['exchanges'][0]}", file=sys.stderr)
            continue
        if marketcap.get(base_coin) is None:
            print(f"{symbol['symbol']} does not have marketcap", file=sys.stderr)
            continue
        if marketcap[base_coin].get('#', '')  == '':
            print(f"{symbol['symbol']} does not have marketcap ranking", file=sys.stderr)
            continue
        rows.append([0, symbol['symbol'], int(marketcap[base_coin]['#']), int(symbol['count']), ','.join(symbol['exchanges'])])
    rows.sort(key=lambda x: x[2], reverse=True)
    rows = rows[:1000]
    
    rows.sort(key=lambda x: x[3], reverse=True)
    group = 0
    max_cnn = 75
    total_cnn = 0
    low_row = 0
    high_row = len(rows) - 1
    while low_row <= high_row and low_row < len(rows):
        group += 1
        rows[low_row][0] = group
        cur_cnn = rows[low_row][3]
        low_row += 1
        while cur_cnn < max_cnn and high_row > low_row:
            rows[high_row][0] = group
            cur_cnn += rows[high_row][3]
            high_row -= 1
        total_cnn += cur_cnn
    rows.sort(key=lambda x: x[0])

    grouped_symbols = []
    current_group = None
    for row in rows:
        if row[0] != current_group:
            current_group = row[0]
            grouped_symbols.append([])
        grouped_symbols[-1].append(row[1])
    grouped_symbols = [','.join(group) for group in grouped_symbols]

    # Print the grouped rows
    with open(json_out, 'w') as f:
        json.dump(grouped_symbols, indent=2, fp=f)

    print(f'{group} groups, {total_cnn} connections, {len(rows)} symbols')

    with open(out, 'w') as f:
        w = csv.writer(f)
        w.writerow(['group', 'symbol', 'ranking', 'count_exchanges', 'exchanges'])
        w.writerows(rows)


async def _run():
    groups_file_path = "./data/groups.csv"
    groups_json_file_path = "./data/groups.json"
    if os.path.exists(groups_file_path) or os.path.exists(groups_json_file_path):
        return
    symbols_file_path = "./data/symbols.csv"
    if not os.path.exists(symbols_file_path):
        raise RuntimeError(f'file "{symbols_file_path}" not found, run "poetry run symbols"')
    marketcap_file_path = "./data/marketcap.csv"
    if not os.path.exists(marketcap_file_path):
        raise RuntimeError(f'file "{marketcap_file_path}" not found, run "poetry run marketcap"')
    _group(symbols_file_path, marketcap_file_path, groups_file_path, groups_json_file_path)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
