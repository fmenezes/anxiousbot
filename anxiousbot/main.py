import asyncio
import os
import sys
import threading

from dotenv import load_dotenv

from anxiousbot import closing
from anxiousbot.dealer import Dealer
from anxiousbot.log import get_logger


async def _main():
    load_dotenv(override=True)
    logger = get_logger(name=__name__)

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

    async with closing(Dealer()) as service:
        return await service.run()


if __name__ == "__main__":
    exit(asyncio.run(_main()))
