import asyncio
import os
import signal
import traceback
from typing import List, Optional

import ccxt.pro as ccxt
from ccxt.base.errors import ExchangeClosedByUser
from dotenv import load_dotenv

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "XRP/USDT", "LTC/USDT"]

class ArbitrageBot:
    def __init__(
        self,
        binance_api_key: Optional[str] = None,
        binance_secret: Optional[str] = None,
        kucoin_api_key: Optional[str] = None,
        kucoin_secret: Optional[str] = None,
        kucoin_passphrase: Optional[str] = None,
        bitget_api_key: Optional[str] = None,
        bitget_secret: Optional[str] = None,
        symbols: Optional[List[str]] = None,
    ):
        # Load API keys from environment variables if not provided
        self.binance_api_key = binance_api_key or os.getenv("BINANCE_API_KEY")
        self.binance_secret = binance_secret or os.getenv("BINANCE_SECRET")
        self.kucoin_api_key = kucoin_api_key or os.getenv("KUCOIN_API_KEY")
        self.kucoin_secret = kucoin_secret or os.getenv("KUCOIN_SECRET")
        self.kucoin_passphrase = kucoin_passphrase or os.getenv("KUCOIN_PASSPHRASE")
        self.bitget_api_key = bitget_api_key or os.getenv("BITGET_API_KEY")
        self.bitget_secret = bitget_secret or os.getenv("BITGET_SECRET")
        self.symbols = symbols or DEFAULT_SYMBOLS

        binance_client = ccxt.binance(
            {
                "apiKey": self.binance_api_key,
                "secret": self.binance_secret,
                "enableRateLimit": True,
            }
        )

        kucoin_client = ccxt.kucoin(
            {
                "apiKey": self.kucoin_api_key,
                "secret": self.kucoin_secret,
                "password": self.kucoin_passphrase,
                "enableRateLimit": True,
            }
        )

        bitget_client = ccxt.bitget(
            {
                "apiKey": self.bitget_api_key,
                "secret": self.bitget_secret,
                "enableRateLimit": True,
            }
        )

        self.exchanges = {}
        for client in [binance_client, kucoin_client, bitget_client]:
            self.exchanges[client.id] = {
                "prices": {},
                "asks": {},
                "client": client
            }

        # Setup signal handler for Ctrl+C
        self.setup_signal_handlers()

    def setup_signal_handlers(self):
        # Handle SIGINT (Ctrl+C)
        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, signal, frame):
        print("Ctrl+C pressed. Cleaning up resources...")
        asyncio.create_task(self.cleanup())

    async def cleanup(self):
        for exchange_name, exchange_data in self.exchanges.items():
            await exchange_data["client"].close()
        print("Resources cleaned up. Exiting...")

    async def fetch_all_fees(self):
        """
        Fetch markets for all exchanges if they haven't been fetched yet.

        Returns:
        - None
        """
        for exchange_name in self.exchanges:
            await self.fetch_fees(exchange_name)

    async def fetch_fees(self, exchange_name):
        """
        Fetch trading fees for a specific exchange if they haven't been fetched yet.

        Parameters:
        - exchange_name (str): Name of the exchange (e.g., 'binance', 'kucoin', 'bitget').

        Returns:
        - None
        """
        exchange_data = self.exchanges[exchange_name]
        client = exchange_data["client"]

        try:
            # Example: Fetch fees for trading
            await client.load_markets()
            exchange_data["markets"] = client.markets
            exchange_data["fees"] = await client.fetch_trading_fees()
            exchange_data["funding_fees"] = {}
            coins = []
            for symbol in self.symbols:
                coins += symbol.split('/')
            coins = set(coins)
            for coin in coins:
                exchange_data["funding_fees"][coin] = await client.fetch_deposit_withdraw_fee(coin)
            print(f"Fetched trading fees for {exchange_name}")
        except Exception as e:
            print(f"Error fetching trading fees for {exchange_name}: {e}")

    def match_asks(self, buy_ask, sell_ask):
        buy_index = 0
        sell_index = 0
        max_amount = 0
        potential_profit = 0.0

        while buy_index < len(buy_ask) and sell_index < len(sell_ask):
            buy_price = buy_ask[buy_index][0]
            buy_amount = buy_ask[buy_index][1]
            sell_price = sell_ask[sell_index][0]
            sell_amount = sell_ask[sell_index][1]

            # Ensure buy price is less than or equal to sell price for a match
            if buy_price <= sell_price:
                matched_amount = min(buy_amount, sell_amount)

                # Update the metrics
                max_amount += matched_amount
                potential_profit += matched_amount * (sell_price - buy_price)

                # Update the amounts
                buy_ask[buy_index][1] -= matched_amount
                sell_ask[sell_index][1] -= matched_amount

                # Remove orders that are fully matched
                if buy_ask[buy_index][1] == 0:
                    buy_index += 1
                if sell_ask[sell_index][1] == 0:
                    sell_index += 1
            else:
                # If the prices don't match, exit the loop
                break

        return {
            'max_amount': max_amount,
            'potential_profit': potential_profit
        }

    async def process_arbitrage(
        self, symbol, buy_exchange, buy_price, buy_asks, sell_exchange, sell_price, sell_asks
    ):
        """
        Process arbitrage opportunity based on buy and sell prices.

        Parameters:
        - symbol (str): Trading pair symbol.
        - buy_exchange (str): Exchange name where buy opportunity exists.
        - buy_price (float): Buy price.
        - sell_exchange (str): Exchange name where sell opportunity exists.
        - sell_price (float): Sell price.

        Returns:
        - None
        """
        matched_asks = self.match_asks(buy_asks, sell_asks)
        
        coin = symbol.split("/")[0]

        buy_withdrawal_fee = (
            self.exchanges[buy_exchange].get("funding_fees", {}).get(coin, {}).get("withdraw", {}).get(
                "fee") or 0.0
        )
        sell_deposit_fee = (
            self.exchanges[sell_exchange].get("funding_fees", {}).get(coin, {}).get("deposit", {}).get(
                "fee") or 0.0
        )

        matched_asks['potential_profit'] -= buy_withdrawal_fee
        matched_asks['potential_profit'] -= sell_deposit_fee

        return matched_asks

    async def trade_arbitrage(self, exchange_name, symbol, ticker, order_book):
        """
        Function to process trade updates and check for arbitrage opportunities.

        Parameters:
        - exchange_name (str): Name of the exchange.
        - symbol (str): Trading pair symbol.
        - price (float): Trade price.

        Returns:
        - None
        """
        # Update prices for the exchange
        price = ticker["last"]
        asks = order_book['asks']
        self.exchanges[exchange_name]["prices"][symbol] = price
        self.exchanges[exchange_name]["asks"][symbol] = asks

        # Check for arbitrage opportunities
        other_exchanges = [ex for ex in self.exchanges.keys() if ex != exchange_name]

        opportunities = []

        for other_exchange in other_exchanges:
            if symbol in self.exchanges[other_exchange]["prices"] and symbol in self.exchanges[other_exchange]["asks"]:
                other_price = self.exchanges[other_exchange]["prices"][symbol]
                other_asks = self.exchanges[other_exchange]["asks"][symbol]

                data = await self.process_arbitrage(
                    symbol, exchange_name, price, asks, other_exchange, other_price, other_asks
                )

                opportunities += [
                    {
                        'buy_exchange': exchange_name,
                        'buy_price': price,
                        'buy_asks': asks,
                        'sell_exchange': other_exchange,
                        'sell_price': other_price,
                        'sell_asks': other_asks,
                        **data
                    }
                ]
                
                data = await self.process_arbitrage(
                    symbol, other_exchange, other_price, other_asks, exchange_name, price, asks
                )

                opportunities += [
                    {
                        'buy_exchange': other_exchange,
                        'buy_price': other_price,
                        'buy_asks': other_asks,
                        'sell_exchange': exchange_name,
                        'sell_price': price,
                        'sell_asks': asks,
                        **data
                    }
                ]

        opportunities.sort(
            key=lambda x: x['potential_profit'], reverse=True)
        opportunity = opportunities[0]
        if opportunity['potential_profit'] > 0:
            print(
                f"Arbitrage opportunity! Buy {symbol} on {opportunity['buy_exchange']} sell on {opportunity['sell_exchange']}. Profit: {opportunity['potential_profit']:.2f} if trading {opportunity['max_amount']:.2f}"
            )


    async def subscribe_exchange(self, exchange_name, symbols):
        """
        Subscribe to exchange WebSocket for trade updates.

        Parameters:
        - exchange_name (str): Name of the exchange.
        - symbols (list): List of trading pairs to subscribe.

        Returns:
        - None
        """

        async def watch_symbol(client, symbol):
            while True:
                try:
                    ticker = await client.watch_ticker(symbol)
                    order_book = await client.watch_order_book(symbol)
                    await self.trade_arbitrage(client.id, symbol, ticker, order_book)
                except ExchangeClosedByUser:
                    print(f"Task for {symbol} on {client.name} was closed.")
                    break  # Exit the loop when task is cancelled
                except asyncio.CancelledError:
                    print(f"Task for {symbol} on {client.name} was cancelled.")
                    break  # Exit the loop when task is cancelled
                except Exception as e:
                    print(
                        f"Error watching {symbol} on {client.name}: [{type(e).__name__}] {str(e)}"
                    )
                    traceback.print_exc()
                    await asyncio.sleep(1)  # Add a delay before retrying

        exchange_data = self.exchanges[exchange_name]
        client = exchange_data["client"]

        try:
            # Subscribe to the WebSocket feed for each symbol
            tasks = [watch_symbol(client, symbol) for symbol in symbols]
            # Ensure all tasks complete
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            print(f"Error subscribing to {exchange_name}: {e}")

    async def run(self):
        """
        Main function to initialize WebSocket subscriptions for Binance, KuCoin, and Bitget.
        """
        try:
            # Fetch markets for all exchanges
            await self.fetch_all_fees()

            # Subscribe to WebSocket for each exchange and symbol
            tasks = [
                asyncio.create_task(
                    self.subscribe_exchange(exchange_name, self.symbols)
                )
                for exchange_name in self.exchanges
            ]

            await asyncio.gather(*tasks)
        finally:
            await self.cleanup()


def main() -> None:
    # Load environment variables from .env file
    load_dotenv(override=True)

    # Example usage with optional parameters (can be passed directly or fallback to .env)
    bot = ArbitrageBot()

    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
