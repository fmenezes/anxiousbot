import ccxt.pro as ccxt
import sys
import asyncio
from dotenv import load_dotenv

async def _run():
    symbols = {}
    i = 1
    for exchange in ccxt.exchanges:
        print(f'{i} / {len(ccxt.exchanges)}', file=sys.stderr)
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
    with open('./data/symbols.csv', 'w') as f:
        print('symbol,count,' + ','.join(ccxt.exchanges), file=f)
        for symbol, exchanges in symbols.items():
            row = f'{symbol},{len(exchanges)}'
            for exchange in ccxt.exchanges:
                if exchange in exchanges:
                    row += ',y'
                else:
                    row += ',n'
            print(row, file=f)


def _main():
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
