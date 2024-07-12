import asyncio
import logging
import json
import os
import sys
import traceback

import ccxt.pro as ccxt
from dotenv import load_dotenv
from pymemcache.client.base import Client as MemcacheClient

from anxiousbot.log import get_logger

class Updater:
    def __init__(self, memcache_client = None, logger = None) -> None:
        if logger is None:
            self.logger = get_logger()
        else:
            self.logger = logger
        if memcache_client is not None:
            self.memcache_client = memcache_client
        else:
            self.memcache_client = MemcacheClient('localhost')

    async def _exponential_backoff(self, fn, *args, **kwargs):
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

    def _convert_exchange_id_for_auth(self, id):
        data = {
            'coinbaseexchange': 'coinbase',
            'coinbaseinternational': 'coinbase',
            'binanceusdm': 'binance',
            'binancecoinm': 'binance',
        }

        if id in data:
            return data[id]
        
        if id.endswith('futures'):
            return id.removesuffix('futures')

        return id


    async def _watch_order_book(self, setting):
        while True:
            exchange_id = self._convert_exchange_id_for_auth(setting['exchange']).upper()
            api_key = os.getenv(f'{exchange_id}_API_KEY')
            secret = os.getenv(f'{exchange_id}_SECRET')
            passphrase = os.getenv(f'{exchange_id}_PASSPHRASE')
            auth = None
            if api_key is not None or secret is not None or passphrase is not None:
                auth = {
                    'apiKey': api_key,
                    'secret': secret,
                    'passphrase': passphrase,
                }
            client_cls = getattr(ccxt, setting['exchange'])
            if auth is not None:
                client = client_cls(auth)
                self.logger.debug(f'{setting['exchange']} logged in', extra={'exchange': setting['exchange']})
            else:
                client = client_cls()

            try:
                await self._exponential_backoff(client.load_markets)
                self.logger.info(f'{setting['exchange']} loaded markets', extra={'exchange': setting['exchange']})
                
                while True:
                    param = setting['symbols']
                    match setting['mode']:
                        case 'single':
                            await asyncio.sleep(0.5)
                            order_book = await self._exponential_backoff(client.fetch_order_book, param[0])
                        case 'all':
                            order_book = await self._exponential_backoff(client.fetch_order_books)
                        case 'batch':
                            order_book = await self._exponential_backoff(client.watch_order_book_for_symbols, param)
                    if 'asks' in order_book:
                        self.memcache_client.set(f'/asks/{order_book['symbol']}/{setting['exchange']}', order_book['asks'])
                    if 'bids' in order_book:
                        self.memcache_client.set(f'/bids/{order_book['symbol']}/{setting['exchange']}', order_book['bids'])
            except Exception as e:
                self.logger.exception(e, extra={'exchange': setting['exchange']})
            finally:
                await client.close()
            self.logger.debug(f'Exiting {setting['exchange']} / {setting['mode']}', extra={'exchange': setting['exchange']})
        
    async def run(self, settings):
        try:
            tasks = []
            i = 0
            for setting in settings:
                tasks += [asyncio.create_task(self._watch_order_book(setting), name=f'setting-{i}')]
                i += 1

            await asyncio.gather(*tasks)
        except Exception as e:
            raise e


    def handle_exception(self, exc_type, exc_value, exc_traceback):
        self.logger.exception(traceback.format_exception(exc_type,
                                                        exc_value,
                                                        exc_traceback))


def _main():
    load_dotenv(override=True)
    UPDATER_INDEX = os.getenv('UPDATER_INDEX', '0')
    CACHE_ENDPOINT = os.getenv('CACHE_ENDPOINT', 'localhost')

    with open('./config/config.json', 'r') as f:
        config = json.load(f)
    logger = get_logger({'app': 'updater', 'config': UPDATER_INDEX})
    memcache_client = MemcacheClient(CACHE_ENDPOINT)
    updater = Updater(logger=logger, memcache_client=memcache_client)
    try:
        logger.info(f"Updater started")
        sys.excepthook = updater.handle_exception
        asyncio.run(updater.run(config['updater'][int(UPDATER_INDEX)]))
        logger.info(f"Updater exited successfully")
        exit_code = 0
    except Exception as e:
        logger.info(f"Updater exited with error")
        logger.exception(f'An error occurred: [{type(e).__name__}] {str(e)}')
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    exit(_main())
