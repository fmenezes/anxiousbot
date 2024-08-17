import copy
from typing import Any, Dict, List, Literal, Tuple

from anxiousbot.exchange_handler import ExchangeHandler


class ExchangeHandlerException(Exception):
    pass


class CalculationHandler:
    def __init__(self, exchange_handler: ExchangeHandler):
        self._exchange_handler = exchange_handler

    def _get_volume_price(self, operation: int) -> Tuple[float | None, float | None]:
        side = self._sides[operation]
        order_book = self._order_books[operation]
        depth = order_book["asks" if side == "buy" else "bids"]
        while True:
            if len(depth) <= 0:
                return None, None
            price, volume = depth[0]
            if price > 0 and volume > 0:
                return round(price, 8), round(volume, 8)
            depth = depth[1:]

    def _match_order_book_buy_operation(self, operation: int) -> float:
        exchange = self._exchanges[operation]
        order_book = self._order_books[operation]
        symbol = order_book["symbol"]
        price, volume = self._get_volume_price(operation)
        if price is None or volume is None:
            self._next[operation] = False
            return 0

        basecoin, quotecoin = symbol.split("/")

        if exchange not in self._balances:
            self._balances[exchange] = {}
        if basecoin not in self._balances[exchange]:
            self._balances[exchange][basecoin] = 0.0
        if quotecoin not in self._balances[exchange]:
            self._balances[exchange][quotecoin] = 0.0
        if exchange not in self._costs:
            self._costs[exchange] = {}
        if basecoin not in self._costs[exchange]:
            self._costs[exchange][basecoin] = 0
        if quotecoin not in self._costs[exchange]:
            self._costs[exchange][quotecoin] = 0

        client = self._exchange_handler.exchange(exchange)
        if client is None:
            raise ExchangeHandlerException(f"exchange {exchange} is not available")

        if volume <= 0:
            order_book["asks"] = order_book["asks"][1:]
            self._next[operation] = len(order_book["asks"]) > 0
            return 0

        available_quote = round(self._balances[exchange][quotecoin], 8)
        available_base = round(available_quote / price, 8)
        fees = client.calculate_fee(symbol, "market", "buy", available_base, price)
        if fees["currency"] == quotecoin:
            cost_in_base = round(fees["cost"] / price, 8)
        else:
            cost_in_base = round(fees["cost"], 8)
        available_base -= cost_in_base
        matched_volume = min(available_base, volume)
        if matched_volume < 0.000001:
            self._next[operation] = False
            return 0
        fees = client.calculate_fee(symbol, "market", "buy", matched_volume, price)
        self._balances[exchange][basecoin] = round(
            self._balances[exchange][basecoin] + matched_volume, 8
        )
        self._balances[exchange][quotecoin] = round(
            self._balances[exchange][quotecoin] - (matched_volume / price), 8
        )
        if fees["currency"] == quotecoin:
            self._costs[exchange][quotecoin] += fees["cost"]
            cost_in_quote = round(fees["cost"], 8)
        else:
            self._costs[exchange][basecoin] += fees["cost"]
            cost_in_quote = round(fees["cost"] * price, 8)
        self._balances[exchange][quotecoin] -= cost_in_quote
        volume -= matched_volume
        order_book["asks"][0][1] = volume
        self._next[operation] = True
        return matched_volume

    def _match_order_book_sell_operation(self, operation: int) -> float:
        exchange = self._exchanges[operation]
        order_book = self._order_books[operation]
        symbol = order_book["symbol"]
        price, volume = self._get_volume_price(operation)
        if price is None or volume is None:
            self._next[operation] = False
            return 0

        basecoin, quotecoin = symbol.split("/")

        if exchange not in self._balances:
            self._balances[exchange] = {}
        if basecoin not in self._balances[exchange]:
            self._balances[exchange][basecoin] = 0.0
        if quotecoin not in self._balances[exchange]:
            self._balances[exchange][quotecoin] = 0.0
        if exchange not in self._costs:
            self._costs[exchange] = {}
        if basecoin not in self._costs[exchange]:
            self._costs[exchange][basecoin] = 0
        if quotecoin not in self._costs[exchange]:
            self._costs[exchange][quotecoin] = 0

        client = self._exchange_handler.exchange(exchange)
        if client is None:
            raise ExchangeHandlerException(f"exchange {exchange} is not available")

        if volume <= 0:
            order_book["bids"] = order_book["bids"][1:]
            self._next[operation] = len(order_book["bids"]) > 0
            return 0

        available_base = round(self._balances[exchange][basecoin], 8)
        fees = client.calculate_fee(symbol, "market", "sell", available_base, price)
        if fees["currency"] == quotecoin:
            cost_in_base = round(fees["cost"] * price, 8)
        else:
            cost_in_base = round(fees["cost"], 8)
        available_base -= cost_in_base
        matched_volume = min(available_base, volume)
        if matched_volume < 0.000001:
            self._next[operation] = False
            return 0
        fees = client.calculate_fee(symbol, "market", "sell", matched_volume, price)
        self._balances[exchange][basecoin] = round(
            self._balances[exchange][basecoin] - matched_volume, 8
        )
        self._balances[exchange][quotecoin] = round(
            self._balances[exchange][quotecoin] + (matched_volume * price), 8
        )
        if fees["currency"] == quotecoin:
            self._costs[exchange][quotecoin] += fees["cost"]
            cost_in_base = round(fees["cost"] * price, 8)
        else:
            self._costs[exchange][basecoin] += fees["cost"]
            cost_in_base = round(fees["cost"], 8)
        self._balances[exchange][basecoin] -= cost_in_base
        volume -= matched_volume
        order_book["bids"][0][1] = volume
        self._next[operation] = True
        return matched_volume

    def _match_order_book_operation(self, operation: int) -> float:
        if not self._next[operation]:
            return 0
        side = self._sides[operation]
        volume = 0
        if side == "buy":
            volume = self._match_order_book_buy_operation(operation)
        else:
            volume = self._match_order_book_sell_operation(operation)
        if volume > 0 and operation < len(self._operations) - 1:
            self._next[operation + 1] = True
        return volume

    def _get_rate(self) -> float | None:
        rate = 1.0
        for operation in range(len(self._operations)):
            side = self._sides[operation]
            price, _ = self._get_volume_price(operation)
            if price is None:
                return None
            if side == "buy":
                rate = round(rate / price, 8)
            else:
                rate = round(rate * price, 8)
        return rate

    def _match_operation(self) -> None:
        rate = self._get_rate()
        if rate is None or rate < 1:
            self._next = [False] * len(self._operations)
            return

        for operation in reversed(range(len(self._operations))):
            if self._next[operation]:
                self._match_order_book_operation(operation)
                break

    def calculate(
        self,
        all_balances: Dict[str, Dict[str, float]],
        operations: List[Tuple[str, Literal["buy", "sell"], Dict[str, Any]]],
    ) -> Dict[str, Any]:
        self._balances = copy.deepcopy(all_balances)
        self._costs = {}
        self._exchanges = []
        self._sides = []
        self._order_books = []
        self._next = []
        self._operations = operations

        for exchange, side, order_book in operations:
            self._exchanges += [exchange]
            self._sides += [side]
            self._order_books += [order_book]
            self._next += [False]
        self._next[0] = True

        while True in self._next:
            self._match_operation()

        exchange, side, order_book = operations[0]
        base, quote = order_book["symbol"].split("/")

        if side == "buy":
            profit_coin = quote
        else:
            profit_coin = base

        last_exchange = operations[-1][0]
        gain = (
            self._balances[last_exchange][profit_coin]
            - all_balances[exchange][profit_coin]
        )
        gain_percentage = (
            self._balances[last_exchange][profit_coin]
            / all_balances[exchange][profit_coin]
            * 100
        )
        return {
            "balance": {
                "initial": all_balances,
                "final": self._balances,
            },
            "profit_coin": profit_coin,
            "profit": gain,
            "profit_percentage": gain_percentage,
            "costs": self._costs,
        }
