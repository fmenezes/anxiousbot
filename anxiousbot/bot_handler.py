import asyncio

from telegram import Bot, Update

from anxiousbot import exponential_backoff
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.log import get_logger


class BotHandler:
    def __init__(
        self,
        config_handler: ConfigHandler,
    ):
        self._config_handler = config_handler
        self._logger = get_logger(__name__)
        self._loop = True
        self._bot = Bot(self._config_handler.bot_token)
        self._messages = []
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._bot.initialize()

    async def enqueue_message(
        self, text: str, chat_id: int | None = None, priority=False
    ) -> None:
        new_entry = {
            "chat_id": (chat_id or self._config_handler.bot_chat_id),
            "text": text,
        }
        async with self._lock:
            if priority:
                self._messages = [new_entry] + self._messages
            else:
                self._messages += [new_entry]

    async def watch(self) -> None:
        while self._loop:
            try:
                async with self._lock:
                    if len(self._messages) == 0:
                        message = None
                    else:
                        message = self._messages[0]
                        self._messages = self._messages[1:]
                if message is None:
                    await asyncio.sleep(1)
                    continue
                await exponential_backoff(
                    self._bot.send_message,
                    chat_id=message["chat_id"],
                    text=message["text"],
                    read_timeout=35,
                    write_timeout=35,
                    connect_timeout=35,
                    pool_timeout=35,
                )
            except Exception as e:
                self._logger.exception(
                    f"An error occurred while dequeuing messages: [{type(e).__name__}] {str(e)}"
                )
                await asyncio.sleep(0.5)

    async def aclose(self) -> None:
        self._loop = False
        await self._bot.shutdown()
