import asyncio
import json

from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient


from anxiousbot import get_logger, closing
from anxiousbot.dealer import Dealer
from anxiousbot.notifier import Notifier
from anxiousbot.updater import Updater


class Runner():
    def __init__(self, config_path, cache_endpoint, bot_token, bot_chat_id):
        self.config_path = config_path
        self.cache_endpoint = cache_endpoint
        self.bot_token = bot_token
        self.bot_chat_id = bot_chat_id
        self.bot_queue = asyncio.Queue()
        self.logger = get_logger(name="runner", extra={"config": self.config_path})
        self.memcache_client = MemcacheClient(self.cache_endpoint, serde=serde.pickle_serde)


    async def dealer_run(self, config):
        logger = get_logger(name="dealer", extra={"config": self.config_path})
        async with closing(
            Dealer(
                memcache_client=self.memcache_client,
                logger=logger,
            )
        ) as service:
            return await service.run(config, self.bot_queue)

    async def notifier_run(self, config):
        logger = get_logger(name="notifier", extra={"config": self.config_path})
        async with closing(
            Notifier(
                memcache_client=self.memcache_client,
                logger=logger,
                bot_token=self.bot_token,
                bot_chat_id=self.bot_chat_id
            )
        ) as service:
            return await service.run(self.bot_queue)

    async def updater_run(self, config):
        logger = get_logger(name="updater", extra={"config": self.config_path})
        async with closing(
            Updater(
                memcache_client=self.memcache_client,
                logger=logger,
            )
        ) as service:
            return await service.run(config)

    async def run(self):
        with open(self.config_path, "r") as f:
            config = json.load(f)

        self.memcache_client.set("/balance/USDT", 100000)

        tasks = []
        if config['dealer'] is not None:
            tasks += [self.dealer_run(config), self.notifier_run(config)]
        if config['updater'] is not None:
            tasks += [self.updater_run(config)]

        return await asyncio.gather(*tasks)

