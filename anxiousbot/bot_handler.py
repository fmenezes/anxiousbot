from telegram import Bot, Update

from anxiousbot import exponential_backoff
from anxiousbot.config_handler import ConfigHandler
from anxiousbot.log import get_logger
from anxiousbot.redis_handler import RedisHandler
from anxiousbot.trader_handler import TraderHandler


class BotHandler:
    def __init__(
        self,
        config_handler: ConfigHandler,
        redis_handler: RedisHandler,
        trader_handler: TraderHandler,
    ):
        self._config_handler = config_handler
        self._redis_handler = redis_handler
        self._trader_handler = trader_handler
        self._logger = get_logger(__name__)
        self._loop = True
        self._bot = Bot(self._config_handler.bot_token)

    async def initialize(self) -> None:
        await self._bot.initialize()
        await self._bot.set_my_commands([("balance", "fetch balance")])
        await self._bot.set_my_short_description("anxiousbot trading without patience")
        await self._bot.set_my_description("anxiousbot trading without patience")

    async def _handle_fetch_balance(self, update: Update) -> None:
        result = await self._trader_handler.fetch_balance()
        msg = ""
        for exchange_id, data in result.items():
            match data["status"]:
                case "NOT_AUTH":
                    continue
                case "ERROR":
                    msg += f"{exchange_id}: Error: {data["exception"]}\n"
                case "OK":
                    msg += f"{exchange_id}: OK\n"
                    for symbol, value in data["balance"].get("free").items():
                        if value > 0:
                            msg += f"  {symbol} {value:.8f}\n"

        await exponential_backoff(
            self.send_message,
            chat_id=update.effective_message.chat_id,
            text=msg,
        )

    async def send_message(
        self, text: str, chat_id: int | None = None, *args, **kwargs
    ) -> None:
        await exponential_backoff(
            self._bot.send_message,
            chat_id=chat_id or self._config_handler.bot_chat_id,
            text=text,
            read_timeout=35,
            write_timeout=35,
            connect_timeout=35,
            pool_timeout=35,
        )

    async def watch(self) -> None:
        _last_update_id = await self._redis_handler.get_last_update_id()

        while self._loop:
            try:
                updates = await self._bot.get_updates(
                    offset=_last_update_id, timeout=10, allowed_updates=Update.MESSAGE
                )
                for update in updates:
                    if (
                        _last_update_id is not None
                        and update.update_id <= _last_update_id
                    ):
                        continue
                    if update.message and update.message.text:
                        match update.message.text:
                            case "/balance":
                                await self._handle_fetch_balance(update)
                    _last_update_id = update.update_id
                    await self._redis_handler.set_last_update_id(_last_update_id)
            except Exception as e:
                self._logger.exception(
                    f"An error occurred while processing bot updates: [{type(e).__name__}] {str(e)}"
                )

    async def close(self) -> None:
        self._loop = False
        await self._bot.shutdown()
