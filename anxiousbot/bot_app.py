from typing import Any, Dict, List, Tuple

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
    TRADE_STATE_ASK_SYMBOL,
    TRADE_STATE_ASK_SIDE,
    TRADE_STATE_ASK_VOLUME,
    TRADE_STATE_END,
    TRANSFER_STATE_ASK_VOLUME,
    TRANSFER_STATE_ASK_EXCHANGE_FROM,
    TRANSFER_STATE_ASK_EXCHANGE_TO,
    TRANSFER_STATE_ASK_NETWORK,
    TRANSFER_STATE_END,
    PREVIEW_TRADE_STATE_ASK_SYMBOL,
    PREVIEW_TRADE_STATE_ASK_SIDE,
    PREVIEW_TRADE_STATE_END,
) = range(12)


class App:
    def __init__(self):
        self._logger = get_logger(__name__)
        self._config_handler = ConfigHandler()
        self._exchange_handler = ExchangeHandler(self._config_handler)
        self._trade_handler = TradeHandler(self._config_handler, self._exchange_handler)

    async def _set_bot_settings(self, app: Application) -> None:
        await app.bot.set_my_commands(
            [
                ("balance", "fetch balance"),
                ("trade", "run trade operation"),
                ("preview_trade", "run calculations to preview a trade"),
                ("transfer", "run transfer operation"),
                ("cancel", "cancel current operation"),
            ]
        )
        await app.bot.set_my_short_description("anxiousbot trading without patience")
        await app.bot.set_my_description("anxiousbot trading without patience")
        await self._exchange_handler.setup_loggedin_exchanges()
        app.add_handler(
            ConversationHandler(
                [CommandHandler("trade", self._handle_trade)],
                states={
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
        app.add_handler(
            ConversationHandler(
                [CommandHandler("transfer", self._handle_transfer)],
                states={
                    TRANSFER_STATE_ASK_VOLUME: [
                        MessageHandler(filters.TEXT, self._handle_transfer_ask_volume)
                    ],
                    TRANSFER_STATE_ASK_EXCHANGE_FROM: [
                        MessageHandler(
                            filters.TEXT, self._handle_transfer_ask_exchange_from
                        )
                    ],
                    TRANSFER_STATE_ASK_EXCHANGE_TO: [
                        MessageHandler(
                            filters.TEXT, self._handle_transfer_ask_exchange_to
                        )
                    ],
                    TRANSFER_STATE_ASK_NETWORK: [
                        MessageHandler(filters.TEXT, self._handle_transfer_ask_network)
                    ],
                    TRANSFER_STATE_END: [
                        MessageHandler(filters.TEXT, self._handle_transfer_end)
                    ],
                },
                fallbacks=[CommandHandler("cancel", self._handle_transfer_cancel)],
            )
        )
        app.add_handler(
            ConversationHandler(
                [CommandHandler("preview_trade", self._handle_preview_trade)],
                states={
                    PREVIEW_TRADE_STATE_ASK_SYMBOL: [
                        MessageHandler(
                            filters.TEXT, self._handle_preview_trade_ask_symbol
                        )
                    ],
                    PREVIEW_TRADE_STATE_ASK_SIDE: [
                        MessageHandler(
                            filters.TEXT, self._handle_preview_trade_ask_side
                        )
                    ],
                    PREVIEW_TRADE_STATE_END: [
                        MessageHandler(filters.TEXT, self._handle_preview_trade_end)
                    ],
                },
                fallbacks=[CommandHandler("cancel", self._handle_preview_trade_cancel)],
            )
        )
        app.add_handler(CommandHandler("balance", self._handle_balance))

    def _exchange_markup(
        self, *args: Tuple, **kwargs: Dict[str, Any]
    ) -> ReplyKeyboardMarkup:
        buttons = [
            KeyboardButton(id) for id in self._trade_handler.valid_exchange_ids()
        ]
        rows = []
        while len(buttons) > 0:
            rows += [buttons[0:3]]
            buttons = buttons[3:]
        return ReplyKeyboardMarkup(
            rows,
            resize_keyboard=True,
            one_time_keyboard=True,
            selective=True,
            *args,
            **kwargs,
        )

    def _side_markup(
        self, *args: Tuple, **kwargs: Dict[str, Any]
    ) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [[KeyboardButton(entry) for entry in self._trade_handler.valid_sides()]],
            resize_keyboard=True,
            one_time_keyboard=True,
            selective=True,
            *args,
            **kwargs,
        )

    async def _handle_trade(self, update: Update, context: CallbackContext) -> int:
        await update.effective_message.reply_text(
            "Which exchange would you like to trade?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._exchange_markup(),
        )
        return TRADE_STATE_ASK_SYMBOL

    async def _handle_trade_ask_symbol(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_exchange = update.effective_message.text
        if self._input_exchange not in self._trade_handler.valid_exchange_ids():
            await update.effective_message.reply_text(
                f"Exchange {self._input_exchange} invalid. Which exchange would you like to trade?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._exchange_markup(),
            )
            return TRADE_STATE_ASK_SYMBOL

        await update.effective_message.reply_text(
            "Which symbol would you like to trade?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=ForceReply(selective=True),
        )
        return TRADE_STATE_ASK_SIDE

    async def _handle_trade_ask_side(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_symbol = update.effective_message.text
        if self._input_symbol not in self._trade_handler.valid_symbols():
            await update.effective_message.reply_text(
                f"Symbol {self._input_symbol} is invalid. Which symbol would you like to trade?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=ForceReply(selective=True),
            )
            return TRADE_STATE_ASK_SIDE
        await update.effective_message.reply_text(
            "Which side would you like to trade?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._side_markup(),
        )
        return TRADE_STATE_ASK_VOLUME

    async def _handle_trade_ask_volume(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        self._input_side = update.effective_message.text
        if self._input_side not in self._trade_handler.valid_sides():
            await update.effective_message.reply_text(
                f"Side {self._input_side} is invalid. Which side would you like to trade?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._side_markup(),
            )
            return TRADE_STATE_ASK_VOLUME
        await update.effective_message.reply_text(
            f"How much would you like to trade? (type /all for full balance)",
            reply_to_message_id=update.effective_message.id,
            reply_markup=ForceReply(selective=True),
        )
        return TRADE_STATE_END

    async def _handle_trade_end(self, update: Update, context: CallbackContext) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_trade_cancel(update, context)
        if update.effective_message.text == "/all":
            self._input_volume = None
        else:
            self._input_volume = update.effective_message.text
            try:
                self._input_volume = float(self._input_volume)
            except:
                await update.effective_message.reply_text(
                    f"Volume {self._input_volume} is invalid. How much would you like to trade? (type /all for full balance)",
                    reply_to_message_id=update.effective_message.id,
                    reply_markup=ForceReply(selective=True),
                )
                return TRADE_STATE_END
        message = await update.effective_message.reply_text(
            f"Trading {self._input_side} {self._input_volume or '/all'} {self._input_symbol} at {self._input_exchange}...",
            reply_to_message_id=update.effective_message.id,
        )
        try:
            init_balance = await self._exchange_handler.exchange(
                self._input_exchange
            ).fetch_balance()
            init_balance = init_balance.get("free")

            response = await self._trade_handler.trade(
                self._input_exchange,
                self._input_symbol,
                self._input_side,
                self._input_volume,
            )

            final_balance = await self._exchange_handler.exchange(
                self._input_exchange
            ).fetch_balance()
            final_balance = final_balance.get("free")

            base, quote = self._input_symbol.split("/")
            expected = 0.0
            cost = response["output"]["fees"]["cost"]
            if self._input_side == "buy":
                if response["output"]["fees"]["currency"] == quote:
                    cost /= response["output"]["price"]
                coin = base
                expected = response["output"]["volume"]
            else:
                if response["output"]["fees"]["currency"] == base:
                    cost *= response["output"]["price"]
                coin = quote
                expected = response["output"]["volume"] * response["output"]["price"]
            expected -= cost
            actual = final_balance[coin] - init_balance[coin]

            msg = f'Trade {self._input_side} {response["output"]["volume"]} {self._input_symbol} at {self._input_exchange} completed.\n'
            msg += f'Expected {expected} {coin} got {actual} {coin} with cost {response["output"]["fees"]["cost"]} {response["output"]["fees"]["currency"]}.'
            await message.edit_text(msg)
        except Exception as e:
            self._logger.exception("error trading")
            await message.edit_text(f"Error trading [{type(e).__name__}] {e}.")
        return ConversationHandler.END

    async def _handle_trade_cancel(
        self, update: Update, context: CallbackContext
    ) -> int:
        await update.effective_message.reply_text(
            f"Trade cancelled.", reply_to_message_id=update.effective_message.id
        )
        return ConversationHandler.END

    async def _handle_balance(self, update: Update, context: CallbackContext) -> None:
        message = await update.effective_message.reply_text(
            "fetching balance...", reply_to_message_id=update.effective_message.id
        )
        result = await self._trade_handler.fetch_balance()
        msg = ""
        for exchange_id, data in result.items():
            match data["status"]:
                case "NOT_AUTH":
                    continue
                case "ERROR":
                    msg += f"{exchange_id}: Error: {data['exception']}\n"
                case "OK":
                    msg += f"{exchange_id}: OK\n"
                    for symbol, value in data["balance"].get("free").items():
                        if value > 0:
                            msg += f"  {symbol} {value:.8f}\n"
        if msg == "":
            msg = "No balance available"
        await message.edit_text(msg)

    async def _handle_transfer(self, update: Update, context: CallbackContext) -> int:
        await update.effective_message.reply_text(
            "Which coin would you like to transfer?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=ForceReply(selective=True),
        )
        return TRANSFER_STATE_ASK_VOLUME

    async def _handle_transfer_ask_volume(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_transfer_cancel(update, context)
        self._input_coin = update.effective_message.text
        if self._input_coin not in self._trade_handler.valid_coins():
            await update.effective_message.reply_text(
                f"Coin {self._input_coin} is invalid. Which coin would you like to transfer?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=ForceReply(selective=True),
            )
            return TRANSFER_STATE_ASK_VOLUME
        await update.effective_message.reply_text(
            "How much would you like to transfer?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=ForceReply(selective=True),
        )
        return TRANSFER_STATE_ASK_EXCHANGE_FROM

    async def _handle_transfer_ask_exchange_from(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_transfer_cancel(update, context)
        self._input_volume = update.effective_message.text
        try:
            self._input_volume = float(self._input_volume)
        except:
            await update.effective_message.reply_text(
                f"Volume {self._input_volume} is invalid. How much would you like to transfer?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=ForceReply(selective=True),
            )
            return TRANSFER_STATE_ASK_EXCHANGE_FROM
        await update.effective_message.reply_text(
            "Which exchange would you like to transfer from?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._exchange_markup(api_kwargs={"force_reply": True}),
        )
        return TRANSFER_STATE_ASK_EXCHANGE_TO

    async def _handle_transfer_ask_exchange_to(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_transfer_cancel(update, context)
        self._input_exchange_from = update.effective_message.text
        if self._input_exchange_from not in self._trade_handler.valid_exchange_ids():
            await update.effective_message.reply_text(
                f"Exchange {self._input_exchange_from} is invalid. Which exchange would you like to transfer from?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._exchange_markup(),
            )
            return TRANSFER_STATE_ASK_EXCHANGE_TO
        await update.effective_message.reply_text(
            "Which exchange would you like to transfer to?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._exchange_markup(),
        )
        return TRANSFER_STATE_ASK_NETWORK

    async def _handle_transfer_ask_network(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_transfer_cancel(update, context)
        self._input_exchange_to = update.effective_message.text
        if self._input_exchange_to not in self._trade_handler.valid_exchange_ids():
            await update.effective_message.reply_text(
                f"Exchange {self._input_exchange_to} is invalid. Which exchange would you like to transfer to?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._exchange_markup(),
            )
            return TRANSFER_STATE_ASK_NETWORK
        await update.effective_message.reply_text(
            "Which network would you like to transfer with?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._network_markup(
                self._input_coin, [self._input_exchange_from, self._input_exchange_to]
            ),
        )
        return TRANSFER_STATE_END

    def _network_markup(
        self, coin: str, exchange_ids: List[str], *args: Tuple, **kwargs: Dict[str, Any]
    ) -> ReplyKeyboardMarkup:
        buttons = [
            KeyboardButton(id)
            for id in self._trade_handler.valid_network_ids(coin, exchange_ids)
        ]
        rows = []
        while len(buttons) > 0:
            rows += [buttons[0:3]]
            buttons = buttons[3:]
        return ReplyKeyboardMarkup(
            rows,
            resize_keyboard=True,
            one_time_keyboard=True,
            selective=True,
            *args,
            **kwargs,
        )

    async def _handle_transfer_end(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_transfer_cancel(update, context)
        self._input_network = update.effective_message.text
        if self._input_network not in self._trade_handler.valid_network_ids(
            self._input_coin, [self._input_exchange_from, self._input_exchange_to]
        ):
            await update.effective_message.reply_text(
                f"Network {self._input_network} is invalid. Which network would you like to transfer with?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._network_markup(
                    self._input_coin,
                    [self._input_exchange_from, self._input_exchange_to],
                ),
            )
            return TRANSFER_STATE_END
        message = await update.effective_message.reply_text(
            f"Transfering {self._input_volume} {self._input_coin} from {self._input_exchange_from} at {self._input_exchange_to} via {self._input_network}...",
            reply_to_message_id=update.effective_message.id,
        )
        try:
            await self._trade_handler.transfer(
                self._input_coin,
                self._input_volume,
                self._input_exchange_from,
                self._input_exchange_to,
                self._input_network,
            )
            await message.edit_text(
                f"Transfer {self._input_volume} {self._input_coin} from {self._input_exchange_from} at {self._input_exchange_to} via {self._input_network} complete"
            )
        except Exception as e:
            self._logger.exception("error transfering")
            await message.edit_text(f"Error transfering [{type(e).__name__}] {e}.")
        return ConversationHandler.END

    async def _handle_transfer_cancel(
        self, update: Update, context: CallbackContext
    ) -> int:
        await update.effective_message.reply_text(
            f"Transfer cancelled.", reply_to_message_id=update.effective_message.id
        )
        return ConversationHandler.END

    async def _handle_preview_trade(
        self, update: Update, context: CallbackContext
    ) -> int:
        await update.effective_message.reply_text(
            "Which exchange would you like to preview the trade?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._exchange_markup(),
        )
        return PREVIEW_TRADE_STATE_ASK_SYMBOL

    async def _handle_preview_trade_ask_symbol(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_preview_trade_cancel(update, context)
        self._input_exchange = update.effective_message.text
        if self._input_exchange not in self._trade_handler.valid_exchange_ids():
            await update.effective_message.reply_text(
                f"Exchange {self._input_exchange} invalid. Which exchange would you like to preview the trade?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._exchange_markup(),
            )
            return PREVIEW_TRADE_STATE_ASK_SYMBOL

        await update.effective_message.reply_text(
            "Which symbol would you like to preview the trade?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=ForceReply(selective=True),
        )
        return PREVIEW_TRADE_STATE_ASK_SIDE

    async def _handle_preview_trade_ask_side(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_preview_trade_cancel(update, context)
        self._input_symbol = update.effective_message.text
        if self._input_symbol not in self._trade_handler.valid_symbols():
            await update.effective_message.reply_text(
                f"Symbol {self._input_symbol} is invalid. Which symbol would you like to preview the trade?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=ForceReply(selective=True),
            )
            return PREVIEW_TRADE_STATE_ASK_SIDE
        await update.effective_message.reply_text(
            "Which side would you like to preview the trade?",
            reply_to_message_id=update.effective_message.id,
            reply_markup=self._side_markup(),
        )
        return PREVIEW_TRADE_STATE_END

    async def _handle_preview_trade_end(
        self, update: Update, context: CallbackContext
    ) -> int:
        if update.effective_message.text == "/cancel":
            return await self._handle_preview_trade_cancel(update, context)
        self._input_side = update.effective_message.text
        if self._input_side not in self._trade_handler.valid_sides():
            await update.effective_message.reply_text(
                f"Side {self._input_side} is invalid. Which side would you like to preview the trade?",
                reply_to_message_id=update.effective_message.id,
                reply_markup=self._side_markup(),
            )
            return PREVIEW_TRADE_STATE_END
        message = await update.effective_message.reply_text(
            f"Calulating {self._input_side} {self._input_symbol} at {self._input_exchange}...",
            reply_to_message_id=update.effective_message.id,
        )
        try:
            response = await self._trade_handler.preview_trade(
                self._input_exchange,
                self._input_symbol,
                self._input_side,
            )

            from_coin = response["coin"]["from"]
            to_coin = response["coin"]["to"]
            init_balance = response["balance"]["initial"]
            final_balance = response["balance"]["final"]
            market_price = response["price"]
            cost = response["cost"]
            if cost[from_coin] > 0:
                cost = f"{cost[from_coin]} {from_coin}"
            else:
                cost = f"{cost[to_coin]} {to_coin}"

            await message.edit_text(
                f"Calculated {self._input_side} {self._input_symbol} at {self._input_exchange}, {init_balance[from_coin]} {from_coin} -> {final_balance[to_coin]} {to_coin} at price {market_price} with cost {cost}."
            )
        except Exception as e:
            self._logger.exception("error calculating")
            await message.edit_text(f"Error calculating [{type(e).__name__}] {e}.")
        return ConversationHandler.END

    async def _handle_preview_trade_cancel(
        self, update: Update, context: CallbackContext
    ) -> int:
        await update.effective_message.reply_text(
            f"Preview trade cancelled.", reply_to_message_id=update.effective_message.id
        )
        return ConversationHandler.END

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


if __name__ == "__main__":
    exit(App.run())
