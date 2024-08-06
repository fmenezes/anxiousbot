import asyncio
import sys
import threading
from contextlib import aclosing

from dotenv import load_dotenv

from anxiousbot.app import App
from anxiousbot.log import get_logger

async def _run():
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

    async with aclosing(App()) as app:
        return await app.run()


def _main():
    return asyncio.run(_run())

if __name__ == "__main__":
    exit(_main())
