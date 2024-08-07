from telegram import Update
from telegram.ext import Application, CallbackContext, CommandHandler

from anxiousbot.config_handler import ConfigHandler
from anxiousbot.exchange_handler import ExchangeHandler
from anxiousbot.log import get_logger
from anxiousbot.trade_handler import TradeHandler


class App:
    def __init__(self):
        self._logger = get_logger(__name__)
        self._config_handler = ConfigHandler()
        self._exchange_handler = ExchangeHandler(self._config_handler)
        self._trade_handler = TradeHandler(self._exchange_handler)

    async def _set_bot_settings(self, app: Application) -> None:
        await app.bot.set_my_commands([("balance", "fetch balance")])
        await app.bot.set_my_short_description("anxiousbot trading without patience")
        await app.bot.set_my_description("anxiousbot trading without patience")
        await self._exchange_handler.setup_loggedin_exchanges()
        app.add_handler(CommandHandler("balance", self._handle_balance))

    async def _handle_balance(self, update: Update, context: CallbackContext) -> None:
        result = await self._trade_handler.fetch_balance()
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
        if msg == "":
            msg = "No balance available"
        await update.effective_message.reply_text(msg)

    def execute(self) -> int:
        app = (
            Application.builder()
            .token(self._config_handler.bot_token)
            .read_timeout(35)
            .pool_timeout(35)
            .write_timeout(35)
            .connect_timeout(35)
            .post_init(self._set_bot_settings)
            .build()
        )
        app.run_polling()
        return 0

    @staticmethod
    def run() -> int:
        app = App()
        return app.execute()
