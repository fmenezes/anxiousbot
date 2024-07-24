import asyncio

from telegram import Bot

from anxiousbot import App


class Notifier(App):
    def __init__(self, bot_token, bot_chat_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_token = bot_token
        self.bot_chat_id = bot_chat_id

    async def run(self, bot_queue):
        try:
            self.logger.info(f"Notifier started")
            while True:
                try:
                    async with Bot(self.bot_token) as bot:
                        while True:
                            try:
                                event = await bot_queue.get()
                                if event["type"] in ["open", "close"]:
                                    continue
                                icon = "\U0001F7E2" if event["type"] == "open" else "\U0001F534"
                                msg = f"{icon} {event["message"]}"
                                await bot.send_message(
                                    chat_id=self.bot_chat_id, text=msg
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
        except Exception as e:
            self.logger.info(f"Notifier exited with error")
            self.logger.exception(f"An error occurred: [{type(e).__name__}] {str(e)}")
            return 1
