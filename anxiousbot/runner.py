import asyncio
import json
import sys
import threading

from pymemcache import serde
from pymemcache.client.base import Client as MemcacheClient

from anxiousbot import closing, get_logger
from anxiousbot.dealer import Dealer


class Runner:
    def __init__(self, config_path, cache_endpoint, bot_token, bot_chat_id):
        self.config_path = config_path
        self.cache_endpoint = cache_endpoint
        self.bot_token = bot_token
        self.bot_chat_id = bot_chat_id

    async def run(self):
        logger = get_logger(name=__name__, extra={"config": self.config_path})
        memcache_client = MemcacheClient(
            self.cache_endpoint, serde=serde.pickle_serde
        )
        def _sys_excepthook(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logger.exception(
                "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
            )

        def _thread_excepthook(exc_type, exc_value, exc_traceback, thread):
            logger.exception(
                f"Uncaught exception in thread {thread}",
                exc_info=(exc_type, exc_value, exc_traceback),
            )

        threading.excepthook = _thread_excepthook
        sys.excepthook = _sys_excepthook

        with open(self.config_path, "r") as f:
            config = json.load(f)

        async with closing(
            Dealer(
                memcache_client=memcache_client,
                logger=logger,
                bot_token=self.bot_token,
                bot_chat_id=self.bot_chat_id,
            )
        ) as service:
            return await service.run(config)
