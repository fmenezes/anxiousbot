import multiprocessing
import os
import sys
import traceback

from telegram import Bot

from anxiousbot import App, closing
from anxiousbot.log import get_logger
from anxiousbot.util import run_uv_loop


class Notifier(App):
    def __init__(self, bot_token, bot_chat_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_token = bot_token
        self.bot_chat_id = bot_chat_id

    async def run(self, bot_queue):
        async with Bot(self.bot_token) as bot:
            while True:
                try:
                    msg = bot_queue.get()
                    await bot.send_message(chat_id=self.bot_chat_id, text=msg)
                except Exception as e:
                    self.logger.exception(
                        f"An error occurred: [{type(e).__name__}] {str(e)}"
                    )


async def run(bot_queue):
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_CHAT_ID = os.getenv("BOT_CHAT_ID")

    logger = get_logger(extra={"app": "notifier"})

    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.exception(traceback.format_exception(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    async with closing(
        Notifier(
            logger=logger,
            bot_chat_id=BOT_CHAT_ID,
            bot_token=BOT_TOKEN,
        )
    ) as notifier:
        try:
            logger.info(f"Notifier started")
            await notifier.run(bot_queue)
            logger.info(f"Notifier exited")
            return 0
        except Exception as e:
            logger.info(f"Notifier exited with error")
            logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1


class NotifierProcess(multiprocessing.Process):
    def __init__(self, bot_queue):
        super().__init__()
        self.bot_queue = bot_queue

    def run(self):
        return run_uv_loop(run, self.bot_queue)
