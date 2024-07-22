import asyncio
import os
import sys
import traceback

from telegram import Bot

from anxiousbot import App, closing, run_uv_loop
from anxiousbot.log import get_logger


class Notifier(App):
    def __init__(self, bot_token, bot_chat_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_token = bot_token
        self.bot_chat_id = bot_chat_id

    async def run(self, bot_queue):
        while True:
            try:
                async with Bot(self.bot_token) as bot:
                    while True:
                        try:
                            event = await bot_queue.get()
                            if event["type"] != "close":
                                continue
                            await bot.send_message(
                                chat_id=self.bot_chat_id, text=event["message"]
                            )
                        except Exception as e:
                            self.logger.exception(
                                f"An error occurred: [{type(e).__name__}] {str(e)}"
                            )
            except Exception as e:
                self.logger.exception(
                    f"An error occurred: [{type(e).__name__}] {str(e)}"
                )
                await asyncio.sleep(1)


async def run(bot_queue):
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_CHAT_ID = os.getenv("BOT_CHAT_ID")

    logger = get_logger(name="notifier")

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
