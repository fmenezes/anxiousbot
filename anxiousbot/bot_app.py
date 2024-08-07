from typing import List

from telegram import ForceReply, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from anxiousbot.config_handler import ConfigHandler
from anxiousbot.exchange_handler import ExchangeHandler
from anxiousbot.log import get_logger
from anxiousbot.trade_handler import TradeHandler

(
    TRADE_STATE_ASK_EXCHANGE,
    TRADE_STATE_ASK_SYMBOL,
    TRADE_STATE_ASK_SIDE,
    TRADE_STATE_ASK_VOLUME,
    TRADE_STATE_END,
) = range(5)


class App:
    def __init__(self):
        self._logger = get_logger(__name__)
        self._config_handler = ConfigHandler()
        self._exchange_handler = ExchangeHandler(self._config_handler)
        self._trade_handler = TradeHandler(self._exchange_handler)

    async def _set_bot_settings(self, app: Application) -> None:
        await app.bot.set_my_commands(
            [
                ("balance", "fetch balance"),
                ("trade", "run trade operation"),
                ("cancel", "cancel current trade operation"),
            ]
        )
        await app.bot.set_my_short_description("anxiousbot trading without patience")
        await app.bot.set_my_description("anxiousbot trading without patience")
        await self._exchange_handler.setup_loggedin_exchanges()
        app.add_handler(
            ConversationHandler(
                [CommandHandler("trade", self._handle_trade)],
                states={
                    TRADE_STATE_ASK_EXCHANGE: [
                        MessageHandler(filters.TEXT, self._handle_trade)
                    ],
                    TRADE_STATE_ASK_SYMBOL: [
                        MessageHandler(filters.TEXT, self._handle_trade_ask_symbol)
                    ],
                    TRADE_STATE_ASK_SIDE: [
                        MessageHandler(filters.TEXT, self._handle_trade_ask_side)
                    ],
                    TRADE_STATE_ASK_VOLUME: [
                        MessageHandler(filters.TEXT, self._handle_trade_ask_volume)
                    ],
                    TRADE_STATE_END: [
                        MessageHandler(filters.TEXT, self._handle_trade_end)
                    ],
                },
                fallbacks=[CommandHandler("cancel", self._handle_trade_cancel)],
            )
        )
        app.add_handler(CommandHandler("balance", self._handle_balance))

    def _valid_exchanges(self) -> List[str]:
        return self._exchange_handler.authenticated_ids()

    def _exchange_markup(self) -> ReplyKeyboardMarkup:
        buttons = [KeyboardButton(id) for id in self._valid_exchanges()]
        rows = []
        while len(buttons) > 0:
            rows += [buttons[0:3]]
            buttons = buttons[3:]
        return ReplyKeyboardMarkup(
            rows, resize_keyboard=True, one_time_keyboard=True, selective=True
        )

    def _valid_sides(self) -> List[str]:
        return ["buy", "sell"]

    def _side_markup(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [[KeyboardButton(entry) for entry in self._valid_sides()]],
            resize_keyboard=True,
            one_time_keyboard=True,
            selective=True,
        )

    async def _handle_trade(self, update: Update, context: CallbackContext) -> int:
        await update.effective_message.reply_text(
            "Which exchange would you like to trade?",
            reply_markup=self._exchange_markup(),
        )
        return TRADE_STATE_ASK_SYMBOL

    async def _handle_trade_ask_symbol(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_exchange = update.effective_message.text
        if self._input_exchange not in self._valid_exchanges():
            await update.effective_message.reply_text(
                f"Exchange {self._input_exchange} invalid. Which exchange would you like to trade?",
                reply_markup=self._exchange_markup(),
            )
            return TRADE_STATE_ASK_SYMBOL

        await update.effective_message.reply_text(
            "Which symbol would you like to trade?",
            reply_markup=ForceReply(selective=True),
        )
        return TRADE_STATE_ASK_SIDE

    async def _handle_trade_ask_side(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_symbol = update.effective_message.text
        if self._input_symbol not in self._config_handler.symbols_param.keys():
            await update.effective_message.reply_text(
                f"Symbol {self._input_symbol} is invalid. Which symbol would you like to trade?",
                reply_markup=ForceReply(selective=True),
            )
            return TRADE_STATE_ASK_SIDE
        await update.effective_message.reply_text(
            "Which side would you like to trade?", reply_markup=self._side_markup()
        )
        return TRADE_STATE_ASK_VOLUME

    async def _handle_trade_ask_volume(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_side = update.effective_message.text
        if self._input_side not in ["buy", "sell"]:
            await update.effective_message.reply_text(
                f"Side {self._input_side} is invalid. Which side would you like to trade?",
                reply_markup=self._side_markup(),
            )
            return TRADE_STATE_ASK_VOLUME
        await update.effective_message.reply_text(
            f"How much would you like to trade?",
            reply_markup=ForceReply(selective=True),
        )
        return TRADE_STATE_END

    async def _handle_trade_end(self, update: Update, context: CallbackContext) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_volume = update.effective_message.text
        try:
            self._input_volume = float(self._input_volume)
        except:
            await update.effective_message.reply_text(
                f"Volume {self._input_volume} is invalid. How much would you like to trade?",
                reply_markup=ForceReply(selective=True),
            )
            return TRADE_STATE_END
        message = await update.effective_message.reply_text(
            f"Trading {self._input_side} {self._input_volume} {self._input_symbol} at {self._input_exchange}..."
        )
        try:
            await self._trade_handler.trade(
                self._input_exchange,
                self._input_symbol,
                self._input_side,
                self._input_volume,
            )
            await message.edit_text(
                f"Traded {self._input_side} {self._input_volume} {self._input_symbol} at {self._input_exchange}."
            )
        except Exception as e:
            await message.edit_text(f"Error trading [{type(e).__name__}] {e}.")
        return ConversationHandler.END

    async def _handle_trade_cancel(
        self, update: Update, context: CallbackContext
    ) -> int:
        await update.effective_message.reply_text(f"Trade cancelled.")
        return ConversationHandler.END

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
