import logging
import multiprocessing
import os
import sys
import threading

from dotenv import load_dotenv

from anxiousbot.bot_app import App as BotApp
from anxiousbot.dealer_app import App as DealerApp
from anxiousbot.log import get_logger


def _run_bot_app(logger: logging.Logger) -> None:
    while True:
        try:
            BotApp.run()
        except:
            logger.exception("error while running bot app")


def _run_dealer_app(logger: logging.Logger) -> None:
    while True:
        try:
            DealerApp.run()
        except:
            logger.exception("error while running dealer app")


def _main() -> None:
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

    if os.getenv("ROLE", "primary") != "primary":
        return _run_dealer_app(logger)

    processes = [
        multiprocessing.Process(target=_run_dealer_app, args=[logger]),
        multiprocessing.Process(target=_run_bot_app, args=[logger]),
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()


if __name__ == "__main__":
    _main()
