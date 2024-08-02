import asyncio
import os
import sys
import threading

from dotenv import load_dotenv

from anxiousbot import closing, get_logger
from anxiousbot.dealer import Dealer


async def _main():
    load_dotenv(override=True)
    SYMBOLS = os.getenv("SYMBOLS", "BTC/USDT")
    RUN_BOT = os.getenv("RUN_BOT")
    CACHE_ENDPOINT = os.getenv("CACHE_ENDPOINT")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_CHAT_ID = os.getenv("BOT_CHAT_ID")
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

    run_bot_updates = (RUN_BOT or "1").lower() in ["1", "true", "yes", "t", "y"]
    symbol_list = SYMBOLS.split(",")
    async with closing(
        Dealer(
            cache_endpoint=CACHE_ENDPOINT,
            bot_token=BOT_TOKEN,
            bot_chat_id=BOT_CHAT_ID,
            symbols=symbol_list,
            run_bot_updates=run_bot_updates,
        )
    ) as service:
        return await service.run()


if __name__ == "__main__":
    exit(asyncio.run(_main()))
